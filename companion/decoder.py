"""Dwow pixel protocol decoder (v1).

Mirror of addon/Dwow/Encoder.lua — see docs/PROTOCOLO.md before
changing any constant here.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass

CELL_PX = 3
CELLS_PER_ROW = 128
PROTOCOL_VERSION = 1
HEADER_CELLS = 5
MAGIC_A = (192, 255, 238)
MAGIC_B = (13, 21, 234)
MAGIC_TOLERANCE = 4
MAX_PAYLOAD_BYTES = 600

# region scanned by find_origin when the strip is not at (0,0) —
# viewport addons shift the WorldFrame and the strip along with it
SEARCH_W = 600
SEARCH_H = 300

FIELDS = [
    "name", "realm", "class_token", "class_name", "race", "level",
    "zone", "subzone", "instance_name", "instance_type",
    "hp_pct", "dead", "xp_pct", "group_size", "group_max", "guild",
]
# protocol v1 appendices (positions 17+): optional, absence is not an error
OPTIONAL_FIELDS = [
    "race_token", "gender", "flags", "target", "target_hp", "target_class",
    "money", "faction", "form", "form_id", "activity", "difficulty",
    "target_level", "mount_spell", "mount_name",
]

# flags field bits (mirror of Core.lua)
FLAG_TAXI = 1
FLAG_COMBAT = 2
FLAG_RESTING = 4
FLAG_MOUNTED = 8
FLAG_SWIMMING = 16
FLAG_AFK = 32
FLAG_GHOST = 64
FLAG_STEALTH = 128
FLAG_FLYING = 256
FLAG_FALLING = 512
FLAG_FISHING = 1024


class DecodeError(Exception):
    pass


@dataclass(frozen=True)
class CharacterState:
    name: str
    realm: str
    class_token: str
    class_name: str
    race: str
    level: int
    zone: str
    subzone: str
    instance_name: str
    instance_type: str
    hp_pct: int
    dead: bool
    xp_pct: int
    group_size: int
    group_max: int
    guild: str
    race_token: str = ""
    gender: str = ""  # "m" or "f"
    flags: int = 0
    target: str = ""
    target_hp: int = 0
    target_class: str = ""  # UnitClassification: worldboss/rareelite/elite/rare/normal
    money: int = 0  # in copper
    faction: str = ""  # "Alliance" or "Horde" (token, not localized)
    form: str = ""  # localized name of the active shapeshift form
    form_id: int = 0  # form spellID (0 when the client doesn't expose it)
    activity: str = ""  # special activity: "token" or "token:arg" (PROTOCOLO.md)
    difficulty: int = 0  # difficultyID from GetInstanceInfo (0 outside instances)
    target_level: int = 0  # hostile target level (-1 = "??", 0 = no target)
    mount_spell: int = 0  # active mount spellID (0 = dismounted/unknown)
    mount_name: str = ""  # localized name of the active mount
    seq: int = 0

    @property
    def is_on_taxi(self) -> bool:
        return bool(self.flags & FLAG_TAXI)

    @property
    def in_combat(self) -> bool:
        return bool(self.flags & FLAG_COMBAT)

    @property
    def resting(self) -> bool:
        return bool(self.flags & FLAG_RESTING)

    @property
    def mounted(self) -> bool:
        return bool(self.flags & FLAG_MOUNTED)

    @property
    def swimming(self) -> bool:
        return bool(self.flags & FLAG_SWIMMING)

    @property
    def afk(self) -> bool:
        return bool(self.flags & FLAG_AFK)

    @property
    def ghost(self) -> bool:
        return bool(self.flags & FLAG_GHOST)

    @property
    def stealthed(self) -> bool:
        return bool(self.flags & FLAG_STEALTH)

    @property
    def flying(self) -> bool:
        return bool(self.flags & FLAG_FLYING)

    @property
    def falling(self) -> bool:
        return bool(self.flags & FLAG_FALLING)

    @property
    def fishing(self) -> bool:
        return bool(self.flags & FLAG_FISHING)

    @property
    def gold(self) -> int:
        return self.money // 10000

    def activity_parts(self) -> tuple[str, str]:
        """('token', 'arg') — arg is empty when the token has no argument."""
        token, _, arg = self.activity.partition(":")
        return token, arg

    def presence_key(self) -> tuple:
        """Everything that, when changed, justifies a Discord update (seq and hp are
        left out to avoid bursts of updates on every regen tick)."""
        return (
            self.name, self.realm, self.class_token, self.race, self.race_token,
            self.gender, self.level, self.zone, self.subzone, self.instance_name,
            self.instance_type, self.dead, self.group_size, self.group_max,
            self.guild, self.flags, self.target, self.target_class,
            self.target_hp // 25,  # fight progress in 25% steps
        )


def _cell_center(index: int, origin: tuple[int, int]) -> tuple[int, int]:
    col = index % CELLS_PER_ROW
    row = index // CELLS_PER_ROW
    return (
        origin[0] + col * CELL_PX + CELL_PX // 2,
        origin[1] + row * CELL_PX + CELL_PX // 2,
    )


def _read_cell(img, index: int, origin: tuple[int, int]) -> tuple[int, int, int]:
    x, y = _cell_center(index, origin)
    if x >= img.width or y >= img.height:
        raise DecodeError(f"célula {index} fora da imagem capturada ({img.width}x{img.height})")
    return img.getpixel((x, y))[:3]


def _close(a, b, tol: int = MAGIC_TOLERANCE) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def iter_origins(img, limit: int = 16):
    """Yields origin candidates (magic cell pair) in the top-left corner.
    UI art can mimic the magic colors within tolerance, so the caller
    should TRY to decode each candidate (the checksum decides) instead
    of trusting the first one."""
    px = img.load()
    max_y = min(img.height, SEARCH_H)
    max_x = min(img.width - CELL_PX - 1, SEARCH_W)
    found = 0
    for y in range(max_y):
        for x in range(max_x):
            if _close(px[x, y][:3], MAGIC_A) and _close(px[x + CELL_PX, y][:3], MAGIC_B):
                yield (x, y)
                found += 1
                if found >= limit:
                    return


def find_origin(img) -> tuple[int, int] | None:
    """First origin candidate, or None (compatibility; prefer
    iter_origins + decode attempt)."""
    return next(iter_origins(img, limit=1), None)


def decode(img, origin: tuple[int, int] = (0, 0)) -> CharacterState:
    """Decodes the WoW window image. Raises DecodeError with the reason."""
    if not (
        _close(_read_cell(img, 0, origin), MAGIC_A)
        and _close(_read_cell(img, 1, origin), MAGIC_B)
    ):
        raise DecodeError("magic não encontrado — faixa oculta (/dwow), overlay por cima ou janela errada")

    version, len_lo, len_hi = _read_cell(img, 2, origin)
    if version != PROTOCOL_VERSION:
        raise DecodeError(f"protocolo v{version} incompatível (companion espera v{PROTOCOL_VERSION})")

    length = len_lo + 256 * len_hi
    if not (0 < length <= MAX_PAYLOAD_BYTES):
        raise DecodeError(f"tamanho de payload inválido: {length}")

    seq = _read_cell(img, 3, origin)[0]
    r, g, b = _read_cell(img, 4, origin)
    checksum = (r << 16) | (g << 8) | b

    raw = bytearray()
    for i in range((length + 2) // 3):
        raw.extend(_read_cell(img, HEADER_CELLS + i, origin))
    payload = bytes(raw[:length])

    if zlib.adler32(payload) & 0xFFFFFF != checksum:
        raise DecodeError("checksum divergente — anti-aliasing/HDR/filtro de cor corrompendo os pixels?")

    parts = payload.decode("utf-8", errors="replace").split("|")
    if len(parts) < len(FIELDS):
        raise DecodeError(f"payload com {len(parts)} campos (esperado ≥ {len(FIELDS)})")

    def _int(s: str) -> int:
        try:
            return int(s)
        except ValueError:
            return 0

    return CharacterState(
        name=parts[0], realm=parts[1], class_token=parts[2], class_name=parts[3],
        race=parts[4], level=_int(parts[5]), zone=parts[6], subzone=parts[7],
        instance_name=parts[8], instance_type=parts[9], hp_pct=_int(parts[10]),
        dead=parts[11] == "1", xp_pct=_int(parts[12]), group_size=_int(parts[13]),
        group_max=_int(parts[14]), guild=parts[15],
        race_token=parts[16] if len(parts) > 16 else "",
        gender=parts[17] if len(parts) > 17 else "",
        flags=_int(parts[18]) if len(parts) > 18 else 0,
        target=parts[19] if len(parts) > 19 else "",
        target_hp=_int(parts[20]) if len(parts) > 20 else 0,
        target_class=parts[21] if len(parts) > 21 else "",
        money=_int(parts[22]) if len(parts) > 22 else 0,
        faction=parts[23] if len(parts) > 23 else "",
        form=parts[24] if len(parts) > 24 else "",
        form_id=_int(parts[25]) if len(parts) > 25 else 0,
        activity=parts[26] if len(parts) > 26 else "",
        difficulty=_int(parts[27]) if len(parts) > 27 else 0,
        target_level=_int(parts[28]) if len(parts) > 28 else 0,
        mount_spell=_int(parts[29]) if len(parts) > 29 else 0,
        mount_name=parts[30] if len(parts) > 30 else "",
        seq=seq,
    )


def decode_with_relocation(
    img, origin: tuple[int, int] = (0, 0), allow_scan: bool = True
) -> tuple[CharacterState, tuple[int, int]]:
    """Decodes at the known origin; if the strip isn't there, searches the image.
    Returns (state, origin) so the caller can cache the origin between frames.
    allow_scan=False skips the (expensive) pixel scan — the caller limits it
    to once every few seconds of continuous failure."""
    try:
        return decode(img, origin), origin
    except DecodeError:
        if not allow_scan:
            raise
        # try ALL candidates: a stable magic false positive (similar UI
        # art) must not block the real strip further along
        for found in iter_origins(img):
            if found == origin:
                continue
            try:
                return decode(img, found), found
            except DecodeError:
                continue
        raise
