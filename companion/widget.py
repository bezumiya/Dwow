"""Updates Discord's Profile Widget V2 with the character state.

WARNING: uses an undocumented EXPERIMENTAL endpoint (API v9, identities) —
Discord may change or remove it without notice. Rich Presence is the stable
base; this module is an optional layer that fails without taking down the rest.
Reverse-engineering reference: https://www.rohan.run/writing/discord-widgets

The field names in `dynamic` must match EXACTLY the Data Fields created in
the Developer Portal widget editor:
  who (Text) · zone (Text) · guild (Text) · objective (Text, "Nível N+1") ·
  level (Number) · hp (Number) · xp (Number, 0-100) · xp_max (Number, always
  100) · portrait (Image)
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from decoder import CharacterState

log = logging.getLogger("dwow.widget")

RAW_ICONS = "https://raw.githubusercontent.com/Gethe/wow-ui-textures/live/ICONS"

# public portraits by (race, gender) — same files as assets_discord;
# female worgen and male pandaren have no dedicated in-game icon (fallback)
_PORTRAITS = {
    ("human", "m"): "Achievement_Character_Human_Male.PNG",
    ("human", "f"): "Achievement_Character_Human_Female.PNG",
    ("dwarf", "m"): "Achievement_Character_Dwarf_Male.PNG",
    ("dwarf", "f"): "Achievement_Character_Dwarf_Female.PNG",
    ("gnome", "m"): "Achievement_Character_Gnome_Male.PNG",
    ("gnome", "f"): "Achievement_Character_Gnome_Female.PNG",
    ("nightelf", "m"): "Achievement_Character_Nightelf_Male.PNG",
    ("nightelf", "f"): "Achievement_Character_Nightelf_Female.PNG",
    ("draenei", "m"): "Achievement_Character_Draenei_Male.PNG",
    ("draenei", "f"): "Achievement_Character_Draenei_Female.PNG",
    ("worgen", "m"): "achievement_worganhead.PNG",
    ("worgen", "f"): "achievement_worganhead.PNG",
    ("orc", "m"): "Achievement_Character_Orc_Male.PNG",
    ("orc", "f"): "Achievement_Character_Orc_Female.PNG",
    ("undead", "m"): "Achievement_Character_Undead_Male.PNG",
    ("undead", "f"): "Achievement_Character_Undead_Female.PNG",
    ("tauren", "m"): "Achievement_Character_Tauren_Male.PNG",
    ("tauren", "f"): "Achievement_Character_Tauren_Female.PNG",
    ("troll", "m"): "Achievement_Character_Troll_Male.PNG",
    ("troll", "f"): "Achievement_Character_Troll_Female.PNG",
    ("bloodelf", "m"): "Achievement_Character_Bloodelf_Male.PNG",
    ("bloodelf", "f"): "Achievement_Character_Bloodelf_Female.PNG",
    ("goblin", "m"): "achievement_Goblinhead.PNG",
    ("goblin", "f"): "achievement_FemaleGoblinhead.PNG",
    ("pandaren", "m"): "Achievement_Character_Pandaren_Female.PNG",
    ("pandaren", "f"): "Achievement_Character_Pandaren_Female.PNG",
}


def portrait_url(race_token: str, gender: str) -> str | None:
    token = race_token.lower()
    token = {"scourge": "undead"}.get(token, token)
    name = _PORTRAITS.get((token, "f" if gender == "f" else "m"))
    return f"{RAW_ICONS}/{name}" if name else None


class WidgetClient:
    def __init__(
        self,
        application_id: str,
        bot_token: str,
        user_id: str,
        min_interval: float = 45.0,
        keepalive_interval: float = 300.0,
        level_cap: int = 0,
    ):
        self.url = (
            f"https://discord.com/api/v9/applications/{application_id}"
            f"/users/{user_id}/identities/0/profile"
        )
        self.bot_token = bot_token
        self.min_interval = min_interval
        self.keepalive_interval = keepalive_interval
        self._last_key: tuple | None = None
        self._last_sent = 0.0
        self._next_allowed = 0.0
        self._fail_streak = 0
        self._disabled = False
        self.level_cap = level_cap

    def _build(self, st: CharacterState) -> dict:
        who = " ".join(p for p in (st.race, st.class_name, str(st.level)) if p)
        if st.instance_type in ("party", "raid", "scenario", "pvp", "arena"):
            zone = st.instance_name or st.zone
        else:
            zone = st.zone
        xp = st.xp_pct
        # a configured level_cap avoids a false "Nível máximo!" on a fresh ding
        # (XP 0 right after hitting 60/70 on a flavor whose real cap is 90)
        if self.level_cap:
            at_cap = st.level >= self.level_cap
        else:
            at_cap = xp == 0 and st.level in (60, 70, 90)
        if at_cap:
            xp = 100  # at max level the bar shows full, not empty
        objective = "Nível máximo!" if at_cap else f"Nível {st.level + 1}"
        dynamic = [
            {"type": 1, "name": "who", "value": who or "?"},
            {"type": 1, "name": "zone", "value": ("💀 " if st.dead else "") + (zone or "…")},
            {"type": 1, "name": "guild", "value": st.guild or "—"},
            {"type": 1, "name": "objective", "value": objective},
            {"type": 2, "name": "level", "value": st.level},
            {"type": 2, "name": "hp", "value": st.hp_pct},
            {"type": 2, "name": "xp", "value": xp},
            {"type": 2, "name": "xp_max", "value": 100},
        ]
        url = portrait_url(st.race_token, st.gender)
        if url:
            dynamic.append({"type": 3, "name": "portrait", "value": {"url": url}})
        return {"username": st.name or "?", "data": {"dynamic": dynamic}}

    def update(self, st: CharacterState) -> None:
        if self._disabled:
            return
        now = time.time()
        if now < self._next_allowed:
            return
        # hp in steps of 10 so the widget doesn't spam updates on every regen tick;
        # xp as a whole % — the 45s minimum interval already caps the cadence
        key = (st.presence_key(), st.hp_pct // 10, st.xp_pct)
        if key == self._last_key and now - self._last_sent < self.keepalive_interval:
            return

        body = json.dumps(self._build(st)).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            method="PATCH",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bot {self.bot_token}",
                "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 1.0.0)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30):
                pass
        except urllib.error.HTTPError as exc:
            self._handle_http_error(exc, now)
            return
        except Exception as exc:
            log.warning("Widget: falha de rede (%s) — tento de novo depois.", exc)
            self._next_allowed = now + self.min_interval
            return
        self._last_key = key
        self._last_sent = now
        self._next_allowed = now + self.min_interval
        self._fail_streak = 0
        log.info("Widget atualizado: %s (%s)", st.name, st.zone)

    def _handle_http_error(self, exc: urllib.error.HTTPError, now: float) -> None:
        if exc.code == 401:
            log.error("Widget: bot token inválido (401) — widget desativado nesta sessão.")
            self._disabled = True
            return
        if exc.code == 429:
            retry = float(exc.headers.get("Retry-After") or 60)
            log.warning("Widget: rate limit (429), aguardando %.0fs.", retry)
            self._next_allowed = now + retry
            return
        self._fail_streak += 1
        detail = ""
        try:
            detail = exc.read()[:200].decode("utf-8", errors="replace")
        except Exception:
            pass
        if exc.code in (403, 404):
            log.warning(
                "Widget: HTTP %s (%s). Prováveis causas: app sem acesso ao experimento "
                "de widgets, ou app não autorizado na sua conta — rode widget_auth.py.",
                exc.code, detail,
            )
        else:
            log.warning("Widget: HTTP %s (%s).", exc.code, detail)
        self._next_allowed = now + self.min_interval
        if self._fail_streak >= 5:
            log.error("Widget: %d falhas seguidas — desativado nesta sessão (endpoint experimental).", self._fail_streak)
            self._disabled = True
