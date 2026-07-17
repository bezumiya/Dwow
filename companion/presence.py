"""Discord layer: builds and sends the Rich Presence via pypresence (local IPC).

This is the only layer that changes in Phase 4 (migration to the C++ Social SDK);
the rest of the companion doesn't know Discord exists.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request

from pypresence import Presence

import locales
from log_i18n import text as T
from decoder import CharacterState

log = logging.getLogger("dwow.presence")

# the game's token for undead is "Scourge"; the assets use "undead"
RACE_ALIASES = {"scourge": "undead"}

# movement forms that deserve the headline (spellID → emoji):
# Travel, Aquatic, Ghost Wolf, Flight, Swift Flight
TRAVEL_FORMS = {783: "🦌", 1066: "🐬", 2645: "🐺", 33943: "🦅", 40120: "🦅"}

# Wowhead CDN icons (56px) upscaled to 512 via proxy — the card's large
# image reacts to state in real time, since the armory render only
# changes on logout
_ICON_CDN = "https://wow.zamimg.com/images/wow/icons/large/{icon}.jpg"
_UPSCALE = "https://wsrv.nl/?url={url}&w=512&h=512&fit=cover&output=png&sharp=1"


def _icon(name: str) -> str:
    url = _ICON_CDN.format(icon=name)
    return _UPSCALE.format(url=urllib.parse.quote(url.removeprefix("https://"), safe=""))


# the REAL Dungeon Finder eye: the game's Interface\LFGFRAME\LFG-Eye texture
# (Gethe/wow-ui-textures mirror) — open frame of the animation sheet
# (64px cell at 256,64), cropped with precrop and upscaled to 512
LFG_EYE_URL = (
    "https://wsrv.nl/?url="
    + urllib.parse.quote(
        "raw.githubusercontent.com/Gethe/wow-ui-textures/live/LFGFRAME/LFG-Eye.PNG",
        safe="")
    + "&cx=256&cy=64&cw=64&ch=64&precrop=1&w=512&h=512&fit=cover&output=png&sharp=1"
)


# shapeshift form (spellID → icon); covers druid, shaman, priest and lock
FORM_ICONS = {
    768: "ability_druid_catform",
    5487: "ability_racial_bearform",
    9634: "ability_racial_bearform",
    24858: "spell_nature_forceofnature",
    33891: "ability_druid_treeoflife",
    783: "ability_druid_travelform",
    1066: "ability_druid_aquaticform",
    33943: "ability_druid_flightform",
    40120: "ability_druid_flightform",
    2645: "spell_nature_spiritwolf",
    15473: "spell_shadow_shadowform",
    103958: "spell_shadow_demonform",
}
TAXI_ICONS = {"Alliance": "ability_mount_gryphon_01", "Horde": "ability_mount_wyvern_01"}
MOUNT_ICONS = {"Alliance": "ability_mount_ridinghorse", "Horde": "ability_mount_whitedirewolf"}

# spellID → official icon name via Wowhead. NEVER blocks: on the first
# request it fires a thread and returns None (the caller uses the generic);
# the result is cached for later ticks. Failure becomes a cached None.
_spell_icon_cache: dict[int, str | None] = {}
_spell_icon_pending: set[int] = set()
_spell_icon_lock = threading.Lock()


def _spell_icon_fetch(spell_id: int) -> None:
    icon = None
    try:
        req = urllib.request.Request(
            f"https://nether.wowhead.com/tooltip/spell/{spell_id}",
            headers={"User-Agent": "Dwow companion"})
        with urllib.request.urlopen(req, timeout=4) as r:
            icon = json.loads(r.read()).get("icon") or None
    except Exception as exc:
        log.info(T("Wowhead: sem ícone para spell %s (%s); usando genérico.",
                   "Wowhead: no icon for spell %s (%s); using generic icon."), spell_id, exc)
    with _spell_icon_lock:
        _spell_icon_cache[spell_id] = icon
        _spell_icon_pending.discard(spell_id)


def _spell_icon(spell_id: int) -> str | None:
    with _spell_icon_lock:
        if spell_id in _spell_icon_cache:
            return _spell_icon_cache[spell_id]
        if spell_id not in _spell_icon_pending:
            _spell_icon_pending.add(spell_id)
            threading.Thread(target=_spell_icon_fetch, args=(spell_id,),
                             daemon=True).start()
    return None


def _dynamic_image(st: CharacterState) -> str | None:
    """Icon reflecting the state RIGHT NOW (form, mount, death); goes to the
    small THUMBNAIL — the large image is always the character (render/portrait),
    per the user's request. Same priority order as _state_text."""
    if st.ghost:
        return _icon("spell_holy_guardianspirit")
    if st.dead:
        return _icon("inv_misc_bone_humanskull_01")
    if st.form_id in FORM_ICONS:
        return _icon(FORM_ICONS[st.form_id])
    if st.is_on_taxi:
        # unknown faction → keep the portrait instead of guessing gryphon
        return _icon(TAXI_ICONS[st.faction]) if st.faction in TAXI_ICONS else None
    if st.instance_type in ("party", "raid", "scenario"):
        # inside an instance the headline is "Dungeon/Raid: X" — a fishing/
        # stealth icon here would contradict the phrase; class icon is coherent
        return None
    if st.fishing:
        return _icon("trade_fishing")
    if st.stealthed:
        return _icon("ability_stealth")
    if st.flying:
        # icon of the ACTUAL mount when the addon managed to identify it
        if st.mount_spell:
            icon = _spell_icon(st.mount_spell)
            if icon:
                return _icon(icon)
        return _icon("ability_mount_drake_red")
    # mounted on the ground the character stays as the large image (the
    # stretched 56px icon looks bad); the mount goes to the small thumbnail
    return None

# the PHRASES live in locales.py (pt/en); only the token sets live here,
# since they are language-neutral.
# lfd/rf/lfgapp/lfglist have no phrase on purpose: being in queue shows up
# only as the LFG eye in small_image, without hiding what the player is doing.

# tokens that only make sense as "ambient mood", evaluated after
# flight/form/mount so they don't mask interesting locomotion.
# bgqueue/bgconfirm are NOT included: a queue pop is urgent and gone in seconds
AMBIENT_TOKENS = {
    "feign", "eat", "drink", "eatdrink", "waterwalk", "tram", "ffa", "skull",
    "lowdur", "idle",
}

# in dungeon/raid/BG queue → the LFG eye replaces the class icon
QUEUE_TOKENS = {"lfd", "rf", "lfgpop", "lfgapp", "lfglist", "bgqueue", "bgconfirm"}


def _trunc16(s: str, limit: int = 128) -> str:
    """Truncates by Discord's limit, which counts UTF-16 units (like
    JavaScript's .length): an astral emoji counts as 2, not 1."""
    if len(s.encode("utf-16-le")) // 2 <= limit:
        return s
    while len(s.encode("utf-16-le")) // 2 > limit:
        s = s[:-1]
    # don't leave a variation selector (U+FE0F) or ZWJ (U+200D) dangling at the cut
    return s.rstrip("️‍")


class PresenceClient:
    def __init__(
        self,
        application_id: str,
        min_interval: float = 15.0,
        keepalive_interval: float = 120.0,
        large_image_key: str = "wow_classic",
        use_race_image: bool = True,
        show_realm: bool = True,
        show_guild: bool = True,
        show_xp: bool = True,
        show_gold: bool = True,
        language: str = "pt",
    ):
        self.L = locales.get(language)
        self.application_id = application_id
        self.min_interval = min_interval
        self.keepalive_interval = keepalive_interval
        self.large_image_key = large_image_key
        self.use_race_image = use_race_image
        self.show_realm = show_realm
        self.show_guild = show_guild
        self.show_xp = show_xp
        self.show_gold = show_gold
        # optional: callable(st) -> URL of the character's 3D render (bnet.py)
        self.render_resolver = None
        self.rpc: Presence | None = None
        self.last_sent = 0.0
        self.last_key: tuple | None = None
        self.session_start: int | None = None
        self._warned_offline = False

    def _connect(self) -> bool:
        if self.rpc is not None:
            return True
        try:
            rpc = Presence(self.application_id)
            rpc.connect()
        except Exception as exc:
            if not self._warned_offline:
                log.warning(T("Discord indisponível (%s); novas tentativas continuarão.",
                              "Discord unavailable (%s); retries will continue."), exc)
                self._warned_offline = True
            return False
        self.rpc = rpc
        self._warned_offline = False
        log.info(T("Conectado ao Discord.", "Connected to Discord."))
        return True

    def _state_text(self, st: CharacterState) -> str:
        """Picks the card's phrase by priority: death > flight > combat >
        instance > stealth > swimming > mount > resting > exploring."""
        zone = st.zone or "Azeroth"
        place = f"{zone} — {st.subzone}" if st.subzone and st.subzone != zone else zone
        inst = st.instance_name or zone
        spot = st.subzone or zone
        boss_worthy = st.target_class in ("worldboss", "rareelite", "elite", "rare")
        tok, arg = st.activity_parts()
        L = self.L
        ctx = {"arg": arg, "zone": zone, "place": place, "spot": spot,
               "inst": inst, "form": st.form, "mount": st.mount_name}
        SIMPLE, ARG = L["activity_simple"], L["activity_arg"]

        def _t(key, **extra):
            return L[key].format(**ctx, **extra)

        def _tpl(table):
            return table[tok].format(**ctx)

        if st.ghost and tok == "spirit":
            s = _t("spirit")
        elif (st.ghost or st.dead) and tok == "res":
            s = _t("res")
        elif st.ghost:
            s = _t("ghost")
        elif st.dead:
            if st.instance_type in ("party", "raid") and st.group_size > 1:
                s = _t("dead_wipe")
            elif st.instance_type in ("party", "raid"):
                s = _t("dead_inst")
            else:
                s = _t("dead")
        elif tok == "flag":
            s = _t("flag")
        elif tok == "breath":
            s = _t("breath")
        elif tok == "fatigue":
            s = _t("fatigue")
        elif st.is_on_taxi:
            if st.faction == "Horde":
                s = _t("taxi", emoji="🦇", ride=L["ride_horde"])
            elif st.faction == "Alliance":
                s = _t("taxi", emoji="🦅", ride=L["ride_alliance"])
            else:
                s = _t("taxi_neutral")
        elif st.in_combat and tok == "boss":
            # ENCOUNTER_START gives the boss's official name, even when targeting an add
            hp = f" ({st.target_hp}%)" if st.target == arg and st.target_hp > 0 else ""
            s = _t("boss", hp=hp)
        elif st.in_combat and st.target and boss_worthy:
            where = inst if st.instance_type in ("party", "raid") else zone
            hp = f" ({st.target_hp}%)" if st.target_hp > 0 else ""
            s = _t("fight_elite", target=st.target, hp=hp, where=where)
        elif st.in_combat and st.target:
            if st.target_level == -1:
                lvl = L["target_lvl_boss"]
            elif st.target_level > 0:
                lvl = L["target_lvl"].format(lvl=st.target_level)
            else:
                lvl = ""
            s = _t("combat_target", target=st.target, lvl=lvl)
        elif st.in_combat:
            s = _t("combat")
        elif tok == "boss":
            # encounter phase break (alive, out of combat): the fight
            # remains the headline
            s = _t("boss", hp="")
        elif tok in ("bgconfirm", "lfgpop"):
            # queue pop expires in seconds — takes priority over everything but combat
            s = _tpl(ARG if tok == "bgconfirm" else SIMPLE)
        elif tok in ("hearth", "teleport", "portal"):
            s = _tpl(ARG)
        elif tok in ("bgwin", "bgloss", "bgtie"):
            s = _t(tok)
        elif st.instance_type == "pvp":
            s = _t("battleground")
        elif st.instance_type == "arena":
            s = _t("arena")
        elif tok in SIMPLE and tok not in AMBIENT_TOKENS:
            s = _tpl(SIMPLE)
        elif tok in ARG and tok not in AMBIENT_TOKENS:
            s = _tpl(ARG)
        elif st.instance_type in ("party", "raid", "scenario"):
            diff = L["difficulty"].get(st.difficulty, "")
            suffix = f" ({diff})" if diff else ""
            key = {"raid": "inst_raid", "party": "inst_party"}.get(
                st.instance_type, "inst_other")
            s = _t(key, diff=suffix)
        elif st.fishing:
            s = _t("fishing")
        elif st.flying and st.form:
            s = _t("fly_form")
        elif st.flying and st.mount_name:
            s = _t("fly_mount")
        elif st.flying:
            s = _t("fly")
        elif st.stealthed:
            s = _t("stealth")
        elif st.form_id in TRAVEL_FORMS and st.form:
            s = _t("travel_form", emoji=TRAVEL_FORMS[st.form_id])
        # falling is transient and more informative than swimming/riding (you
        # can jump off a cliff while mounted with Slow Fall active)
        elif tok == "floatfall":
            s = _t("floatfall")
        elif st.falling:
            s = _t("falling")
        elif st.swimming:
            s = _t("swim")
        elif st.mounted and st.mount_name:
            s = _t("mount_named")
        elif st.mounted:
            s = _t("mount")
        elif tok in AMBIENT_TOKENS:
            s = _tpl(SIMPLE if tok in SIMPLE else ARG)
        elif st.resting:
            s = _t("resting")
        else:
            s = place
        # danger is information: low HP in combat goes into the phrase
        if st.in_combat and not (st.dead or st.ghost) and 0 < st.hp_pct < 35:
            s += L["hp_warn"].format(hp=st.hp_pct)
        if st.afk:
            s = L["afk_prefix"] + s
        return s

    def _build(self, st: CharacterState) -> dict:
        # "Orc Guerreiro 47" — skips empty parts without leaving a double space
        who = " ".join(p for p in (st.race, st.class_name, str(st.level)) if p)
        details = f"{st.name} — {who}" if st.name else who
        if self.show_xp and 0 < st.xp_pct < 100:
            details += self.L["xp_label"].format(xp=st.xp_pct)

        state = self._state_text(st)
        if len(state) < 2:  # Discord rejects a state shorter than 2 characters
            state = self.L["loading"]

        large_parts = []
        if self.show_realm and st.realm:
            large_parts.append(st.realm)
        if self.show_guild and st.guild:
            large_parts.append(f"<{st.guild}>")
        if self.show_gold and st.gold > 0:
            large_parts.append(f"💰 {st.gold:,}g".replace(",", "."))
        large_text = " · ".join(large_parts) or None

        portrait = self.large_image_key
        if self.use_race_image and st.race_token:
            token = st.race_token.lower()
            token = RACE_ALIASES.get(token, token)
            gender = "female" if st.gender == "f" else "male"
            portrait = f"race_{token}_{gender}"

        # the large image is ALWAYS the character: 3D render when available,
        # otherwise the race portrait — states (flight, form, death…) don't change it
        large_image = portrait
        if self.render_resolver is not None:
            render = self.render_resolver(st)
            if render:
                large_image = render

        # small_image: in queue → LFG eye; live state (form, mount,
        # death, flight…) → state icon; otherwise → class icon
        dyn = _dynamic_image(st)
        tok, _ = st.activity_parts()
        if tok in QUEUE_TOKENS:
            small_image = LFG_EYE_URL
            qs = self.L["queue_small"]
            small_text = qs.get(tok, qs["default"])
        elif dyn is not None:
            small_image = dyn
            # with an identified mount (on ground or flying) its name is more
            # useful than race/class in the thumbnail caption
            small_text = st.mount_name \
                or " ".join(p for p in (st.race, st.class_name) if p) or None
        elif st.mounted and st.mount_spell and _spell_icon(st.mount_spell):
            # mounted on the ground: the mount becomes the thumbnail (56px stays sharp there)
            small_image = _icon(_spell_icon(st.mount_spell))
            small_text = st.mount_name or None
        else:
            small_image = f"class_{st.class_token.lower()}" if st.class_token else None
            small_text = " ".join(p for p in (st.race, st.class_name) if p) or None

        kwargs = {
            "details": _trunc16(details),
            "state": _trunc16(state),
            "start": self.session_start,
            "large_image": large_image,
            "large_text": _trunc16(large_text) if large_text else None,
            "small_image": small_image,
            "small_text": small_text,
        }
        if st.group_size > 1:
            kwargs["party_size"] = [st.group_size, max(st.group_max, st.group_size)]
        return kwargs

    def update(self, st: CharacterState) -> None:
        if not self._connect():
            return
        now = time.time()
        if self.session_start is None:
            self.session_start = int(now)
        kwargs = self._build(st)
        # the change key is the RENDERED payload: only what actually shows
        # on the card triggers an update (internal fields masked by the phrase don't count)
        key = tuple((k, str(v)) for k, v in sorted(kwargs.items()) if k != "start")
        # keepalive: resend every so often even without changes, so we don't
        # end up with an empty presence if Discord restarted under us
        if key == self.last_key and now - self.last_sent < self.keepalive_interval:
            return
        if now - self.last_sent < self.min_interval:
            return  # the loop calls again next tick; the update goes out when the window opens
        try:
            self.rpc.update(**kwargs)
        except Exception as exc:
            log.warning(T("Falha ao atualizar presence (%s); reconectando.",
                          "Presence update failed (%s); reconnecting."), exc)
            self._drop()
            # if the error persists, retry once per min_interval, not every tick
            self.last_sent = now
            return
        self.last_sent = now
        self.last_key = key
        log.info(T("Presence enviado: personagem=%s zona=%s AFK=%s.",
                   "Presence sent: character=%s zone=%s AFK=%s."),
                 st.name, st.zone, "on" if st.afk else "off")

    def clear(self, end_session: bool = True) -> None:
        # end_session=False: clears the card but keeps the session clock —
        # used when the game just froze/minimized; on return, the "elapsed"
        # doesn't lie by restarting from zero
        if end_session:
            self.session_start = None
        self.last_key = None
        if self.rpc is None:
            return
        try:
            self.rpc.clear()
            log.info(T("Presence limpo.", "Presence cleared."))
        except Exception:
            self._drop()

    def close(self) -> None:
        self.clear()
        if self.rpc is not None:
            try:
                self.rpc.close()
            except Exception:
                pass
            self.rpc = None

    def _drop(self) -> None:
        try:
            if self.rpc is not None:
                self.rpc.close()
        except Exception:
            pass
        self.rpc = None
        # the next connection starts with no activity at all: forget what was
        # already sent (else key == last_key blocks the resend); session_start stays
        self.last_key = None
        self.last_sent = 0.0
