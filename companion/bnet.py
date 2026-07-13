"""3D render of the player's own character via the Battle.net API (Character Media).

Optional: without credentials, the presence keeps using the race portraits.
The data only updates when the character logs out (API behavior), and new
characters can return 404 for hours — all handled with caching and backoff
so the main loop never stalls.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("dwow.bnet")

NAMESPACES = {
    "era": "profile-classic1x-{region}",
    "mop": "profile-classic-{region}",
    "anniversary": "profile-classicann-{region}",
}

# preference order for the assets returned by character-media;
# "avatar" (~84px) gets upscaled via proxy before going to Discord
ASSET_PRIORITY = ("main-raw", "main", "inset")
LOW_RES_ASSETS = ("avatar",)

# public image proxy (resizes with Lanczos + sharpening); takes the URL
# without the https:// scheme
UPSCALE_PROXY = "https://wsrv.nl/?url={url}&w=512&h=512&fit=cover&output=png&sharp=1"


def _upscale(url: str) -> str:
    return UPSCALE_PROXY.format(url=urllib.parse.quote(url.removeprefix("https://"), safe=""))

UA = "DiscordWow companion (projeto pessoal)"


def _slugify_realm(realm: str) -> str:
    return realm.lower().replace("'", "").replace(" ", "-")


class BnetRenders:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        region: str = "us",
        flavor: str = "era",
        cache_ttl: float = 600.0,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.region = region
        self.namespace = NAMESPACES.get(flavor, NAMESPACES["era"]).format(region=region)
        self.cache_ttl = cache_ttl
        self._token: str | None = None
        self._token_exp = 0.0
        # (realm, name) -> (url or None, timestamp)
        self._cache: dict[tuple[str, str], tuple[str | None, float]] = {}
        self._backoff_until = 0.0
        self._lowres_warned: set[str] = set()
        self._lock = threading.Lock()
        self._fetching: set[tuple[str, str]] = set()

    def _get_token(self) -> str | None:
        now = time.time()
        with self._lock:
            tok = self._token
            if tok and now < self._token_exp - 60:
                return tok
        creds = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        req = urllib.request.Request(
            "https://oauth.battle.net/token",
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": UA,
            },
        )
        # short timeout: this fetch runs inside the capture loop and must not
        # hold up the presence for long (happens at most once per cache_ttl)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        with self._lock:
            self._token = data["access_token"]
            self._token_exp = now + float(data.get("expires_in", 3600))
            return self._token

    def _fetch(self, name: str, realm: str) -> str | None:
        token = self._get_token()
        url = (
            f"https://{self.region}.api.blizzard.com/profile/wow/character/"
            f"{urllib.parse.quote(_slugify_realm(realm))}/"
            f"{urllib.parse.quote(name.lower())}/character-media"
            f"?namespace={self.namespace}&locale=en_US"
        )
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}", "User-Agent": UA}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assets = {a.get("key"): a.get("value") for a in data.get("assets", [])}
        for key in ASSET_PRIORITY:
            if assets.get(key):
                return assets[key]
        for key in LOW_RES_ASSETS:
            if assets.get(key):
                if name not in self._lowres_warned:
                    self._lowres_warned.add(name)
                    log.info(
                        "Battle.net: só há o busto pequeno (avatar) para %s — "
                        "usando upscale 512px via proxy de imagens.", name,
                    )
                return _upscale(assets[key])
        # older API format used loose fields instead of the assets list
        old = data.get("render_url") or data.get("avatar_url")
        return _upscale(old) if old else None

    def render_url(self, name: str, realm: str) -> str | None:
        """Character render URL, or None. NEVER blocks: returns whatever is in
        the cache and, if stale, kicks off the fetch in a background thread —
        the new value shows up on the next tick."""
        if not name or not realm:
            return None
        key = (_slugify_realm(realm), name.lower())
        now = time.time()
        with self._lock:
            cached = self._cache.get(key)
            fresh = cached and now - cached[1] < self.cache_ttl
            if not fresh and now >= self._backoff_until and key not in self._fetching:
                self._fetching.add(key)
                threading.Thread(
                    target=self._refresh, args=(key, name, realm), daemon=True
                ).start()
        return cached[0] if cached else None

    def _refresh(self, key: tuple[str, str], name: str, realm: str) -> None:
        try:
            url = self._fetch_guarded(name, realm)
            with self._lock:
                self._cache[key] = (url, time.time())
        finally:
            with self._lock:
                self._fetching.discard(key)

    def _fetch_guarded(self, name: str, realm: str) -> str | None:
        """_fetch with error handling; runs on the background thread, so EVERY
        write to shared state happens under the lock. Returns the value to
        cache (_refresh stores it)."""
        now = time.time()
        key = (_slugify_realm(realm), name.lower())
        with self._lock:
            cached = self._cache.get(key)
        try:
            url = self._fetch(name, realm)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                # character not synced yet (common for a new char / no logout)
                log.info("Battle.net: sem render para %s-%s ainda (404).", name, realm)
                return None
            with self._lock:
                if exc.code == 401:
                    # expired/revoked token: invalidate so it renews next time;
                    # if the credentials are wrong, the error will come from OAuth
                    self._token, self._token_exp = None, 0.0
                    self._backoff_until = now + 60
                else:
                    self._backoff_until = now + 300
            log.warning("Battle.net: HTTP %s ao buscar render — tento depois.", exc.code)
            return cached[0] if cached else None
        except Exception as exc:
            log.warning("Battle.net: falha de rede (%s) — tento depois.", exc)
            with self._lock:
                self._backoff_until = now + 300
            return cached[0] if cached else None
        if url:
            log.info("Battle.net: render 3D de %s-%s carregado.", name, realm)
        return url
