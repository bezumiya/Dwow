"""Protocol round-trip test: generates the image the addon would draw
(same rules as Encoder.lua) and validates the decoder. Runs without WoW and
without Discord:  python test_roundtrip.py
"""
from __future__ import annotations

import zlib

from PIL import Image

import decoder


def build_cells(payload: bytes, seq: int = 7) -> list[tuple[int, int, int]]:
    ck = zlib.adler32(payload) & 0xFFFFFF
    cells = [
        decoder.MAGIC_A,
        decoder.MAGIC_B,
        (decoder.PROTOCOL_VERSION, len(payload) % 256, len(payload) // 256),
        (seq, 0, 0),
        ((ck >> 16) & 0xFF, (ck >> 8) & 0xFF, ck & 0xFF),
    ]
    for i in range(0, len(payload), 3):
        chunk = payload[i:i + 3]
        chunk += b"\x00" * (3 - len(chunk))
        cells.append((chunk[0], chunk[1], chunk[2]))
    return cells


def render(cells: list[tuple[int, int, int]], offset: tuple[int, int] = (0, 0)) -> Image.Image:
    cell, per_row = decoder.CELL_PX, decoder.CELLS_PER_ROW
    rows = (len(cells) + per_row - 1) // per_row
    ox, oy = offset
    # dark-gray background simulating the game behind the strip
    img = Image.new("RGB", (per_row * cell + ox, (rows + 2) * cell + oy), (24, 30, 18))
    px = img.load()
    for i, (r, g, b) in enumerate(cells):
        cx = ox + (i % per_row) * cell
        cy = oy + (i // per_row) * cell
        for dx in range(cell):
            for dy in range(cell):
                px[cx + dx, cy + dy] = (r, g, b)
    return img


PAYLOAD_FIELDS = [
    "Grubento", "Firemaw", "WARRIOR", "Guerreiro", "Orc", "47",
    "Vale Estrangulacérrimo", "Acampamento Grom'gol", "", "none",
    "83", "0", "62", "0", "5", "Os Bravos do Brasil",
    "Orc", "m",  # v1 appendices: race_token, gender
    "34", "Ragnaros", "43", "worldboss", "1234567",  # flags, target, hp, classification, copper
    "Horde", "", "0", "",  # faction, form, form_id, activity
    "0", "45", "0", "",  # difficulty, target_level, mount_spell, mount_name
]


def test_roundtrip() -> None:
    payload = "|".join(PAYLOAD_FIELDS).encode("utf-8")
    st = decoder.decode(render(build_cells(payload, seq=42)))
    assert st.name == "Grubento", st.name
    assert st.class_token == "WARRIOR"
    assert st.class_name == "Guerreiro"
    assert st.race == "Orc"
    assert st.race_token == "Orc" and st.gender == "m"
    assert st.in_combat and st.afk  # flags 34 = combat + AFK
    assert not st.is_on_taxi and not st.ghost
    assert st.target == "Ragnaros" and st.target_hp == 43 and st.target_class == "worldboss"
    assert st.money == 1234567 and st.gold == 123
    assert st.level == 47
    assert st.zone == "Vale Estrangulacérrimo", st.zone  # UTF-8 with accents
    assert st.subzone == "Acampamento Grom'gol"
    assert st.instance_type == "none"
    assert st.hp_pct == 83 and st.xp_pct == 62
    assert st.dead is False
    assert st.difficulty == 0 and st.target_level == 45
    assert st.group_size == 0 and st.group_max == 5
    assert st.guild == "Os Bravos do Brasil"
    assert st.seq == 42


def test_multirow() -> None:
    fields = list(PAYLOAD_FIELDS)
    fields[15] = "Guilda Com Nome Absurdamente Comprido " * 8  # forces a 2nd row of cells
    payload = "|".join(fields).encode("utf-8")
    assert 5 + (len(payload) + 2) // 3 > decoder.CELLS_PER_ROW, "payload deveria quebrar linha"
    st = decoder.decode(render(build_cells(payload)))
    assert st.guild.startswith("Guilda Com Nome Absurdamente Comprido")


def test_checksum_detects_corruption() -> None:
    payload = "|".join(PAYLOAD_FIELDS).encode("utf-8")
    img = render(build_cells(payload))
    x, y = decoder.CELL_PX * 8 + 1, 1  # corrupts one payload cell
    img.putpixel((x, y), (255, 0, 0))
    try:
        decoder.decode(img)
    except decoder.DecodeError as exc:
        assert "checksum" in str(exc)
    else:
        raise AssertionError("corrupção não detectada")


def test_backward_compat_16_fields() -> None:
    """Original v1 payload (without the race_token/gender appendices) is still valid."""
    payload = "|".join(PAYLOAD_FIELDS[:16]).encode("utf-8")
    st = decoder.decode(render(build_cells(payload)))
    assert st.name == "Grubento"
    assert st.race_token == "" and st.gender == ""


def test_origin_relocation() -> None:
    """Displaced strip (viewport addon): decode at (0,0) fails, the scan finds it."""
    payload = "|".join(PAYLOAD_FIELDS).encode("utf-8")
    img = render(build_cells(payload, seq=9), offset=(37, 13))
    try:
        decoder.decode(img)  # default origin must not work
    except decoder.DecodeError:
        pass
    else:
        raise AssertionError("decode em (0,0) deveria falhar com faixa deslocada")
    st, origin = decoder.decode_with_relocation(img, (0, 0))
    assert origin == (37, 13), origin
    assert st.name == "Grubento" and st.seq == 9
    # with the origin cached, the fast path decodes directly
    assert decoder.decode(img, origin).zone == "Vale Estrangulacérrimo"


def test_phrases() -> None:
    """Presence phrase engine: priority and content per game state."""
    from dataclasses import replace

    from presence import PresenceClient

    pc = PresenceClient("0")  # does not connect in __init__
    base = decoder.decode(render(build_cells("|".join(PAYLOAD_FIELDS).encode("utf-8"))))

    boss = pc._build(base)["state"]
    assert "Lutando contra Ragnaros (43%)" in boss, boss
    assert boss.startswith("💤 AFK"), boss  # flags 34 includes AFK

    taxi = pc._build(replace(base, flags=1))["state"]
    assert taxi == "🦇 Voando de wyvern sobre Vale Estrangulacérrimo", taxi

    taxi_ally = pc._build(replace(base, flags=1, faction="Alliance"))["state"]
    assert taxi_ally == "🦅 Voando de grifo sobre Vale Estrangulacérrimo", taxi_ally

    ghost = pc._build(replace(base, flags=64, dead=True))["state"]
    assert ghost.startswith("👻 Fantasma"), ghost

    resting = pc._build(replace(base, flags=4))["state"]
    assert resting == "🛏️ Descansando — Acampamento Grom'gol", resting

    dungeon = pc._build(replace(base, flags=0, instance_name="Blackrock Depths",
                                instance_type="party"))["state"]
    assert dungeon == "🏰 Masmorra: Blackrock Depths", dungeon

    raid_h = pc._build(replace(base, flags=0, instance_name="Trono do Trovão",
                               instance_type="raid", difficulty=6))["state"]
    assert raid_h == "⚔️ Raid: Trono do Trovão (25 Heroica)", raid_h

    details = pc._build(replace(base, flags=0))["details"]
    assert details == "Grubento — Orc Guerreiro 47 · XP 62%", details

    tooltip = pc._build(replace(base, flags=0))["large_text"]
    assert "💰 123g" in tooltip, tooltip

    mounted = pc._build(replace(base, flags=decoder.FLAG_MOUNTED))["state"]
    assert mounted.startswith("🐎 Cavalgando"), mounted

    poor = pc._build(replace(base, flags=0, money=9999))["large_text"]
    assert "💰" not in poor, poor  # less than 1 gold doesn't show "0g"

    # Discord's limit is in UTF-16 units (an emoji counts as 2), not code points
    long_state = pc._build(replace(base, flags=decoder.FLAG_AFK, zone="Z" * 200))["state"]
    assert len(long_state.encode("utf-16-le")) // 2 <= 128, len(long_state)
    assert long_state.startswith("💤 AFK")

    fishing = pc._build(replace(base, flags=decoder.FLAG_FISHING))["state"]
    assert fishing == "🎣 Pescando — Acampamento Grom'gol", fishing

    flying = pc._build(replace(base, flags=decoder.FLAG_MOUNTED | decoder.FLAG_FLYING))["state"]
    assert flying.startswith("🐉 Voando montado"), flying

    flight_form = pc._build(replace(
        base, flags=decoder.FLAG_FLYING, form="Forma de Voo Ligeiro", form_id=40120))["state"]
    assert flight_form == "🦅 Forma de Voo Ligeiro — sobrevoando Vale Estrangulacérrimo", flight_form

    travel = pc._build(replace(base, flags=0, form="Forma de Viagem", form_id=783))["state"]
    assert travel.startswith("🦌 Forma de Viagem"), travel

    wolf = pc._build(replace(base, flags=0, form="Lobo Fantasma", form_id=2645))["state"]
    assert wolf.startswith("🐺 Lobo Fantasma"), wolf

    falling = pc._build(replace(base, flags=decoder.FLAG_FALLING))["state"]
    assert falling.startswith("🪂 Em queda livre"), falling

    danger = pc._build(replace(base, flags=decoder.FLAG_COMBAT, hp_pct=18))["state"]
    assert danger.endswith("· ❗18% HP"), danger

    def act(a, **kw):
        return pc._build(replace(base, flags=0, target="", **kw, activity=a))["state"]

    assert act("ah") == "💰 Especulando na Casa de Leilões — o verdadeiro endgame"
    assert act("hearth:Orgrimmar") == "🏡 Voltando para casa — Orgrimmar"
    assert act("flag").startswith("🚩 CARREGANDO A BANDEIRA"), act("flag")
    assert act("breath:37") == "🫧 Prendendo o fôlego (37% de ar) — Vale Estrangulacérrimo"
    assert act("mine") == "⛏️ Minerando um veio — Vale Estrangulacérrimo"
    assert act("idle:7").startswith("🪑 Parado há 7 min"), act("idle:7")
    assert act("duel:Thrall") == "🤺 Em duelo com Thrall — honra em jogo!"

    boss = pc._build(replace(
        base, flags=decoder.FLAG_COMBAT, activity="boss:Onyxia", target="Guarda Onyxiano",
        instance_name="Covil de Onyxia", instance_type="raid"))["state"]
    assert boss == "🐉 Enfrentando Onyxia — Covil de Onyxia", boss

    spirit = pc._build(replace(
        base, flags=decoder.FLAG_GHOST, dead=True, activity="spirit:23"))["state"]
    assert spirit == "⚰️ Na fila do Curandeiro Espiritual — renasce em 23s", spirit

    wipe = pc._build(replace(base, flags=0, dead=True, target="", group_size=5,
                             instance_name="Blackrock Depths",
                             instance_type="party"))["state"]
    assert wipe.startswith("☠️ Wipe em Blackrock Depths"), wipe

    # dead ALONE in a dungeon is not a wipe
    solo_dead = pc._build(replace(base, flags=0, dead=True, target="", group_size=1,
                                  instance_name="Blackrock Depths",
                                  instance_type="party"))["state"]
    assert solo_dead.startswith("💀 Morto em Blackrock Depths"), solo_dead

    res = pc._build(replace(base, flags=0, dead=True, target="",
                            activity="res:Sacerdotisa"))["state"]
    assert res == "✨ Sacerdotisa está me trazendo de volta à vida", res

    # ambient activity doesn't mask interesting locomotion: mounted + eating
    riding = pc._build(replace(base, flags=decoder.FLAG_MOUNTED, target="",
                               activity="idle:7"))["state"]
    assert riding.startswith("🐎 Cavalgando"), riding
    # BG queue is NOT ambient: shows even while mounted
    queued = pc._build(replace(base, flags=decoder.FLAG_MOUNTED, target="",
                               activity="bgqueue:Warsong Gulch"))["state"]
    assert queued == "⏳ Na fila para Warsong Gulch — afiando as lâminas", queued
    # queue pop beats everything except combat/death
    pop = pc._build(replace(base, flags=decoder.FLAG_MOUNTED, target="",
                            activity="lfgpop"))["state"]
    assert pop == "👁️ A FILA POPOU — aceita logo, o grupo espera!", pop

    # deadly fatigue
    assert act("fatigue:22") == "🥵 Fadiga mortal (22%) — nada de volta, AGORA!"

    # target level in regular combat
    lvl = pc._build(replace(base, flags=decoder.FLAG_COMBAT, activity="",
                            target="Kobold", target_class="normal",
                            target_level=43))["state"]
    assert "Kobold nv.43" in lvl, lvl
    boss_lvl = pc._build(replace(base, flags=decoder.FLAG_COMBAT, activity="",
                                 target="Kobold", target_class="normal",
                                 target_level=-1))["state"]
    assert "Kobold ??" in boss_lvl, boss_lvl

    # target HP 0 doesn't become "(0%)"
    nohp = pc._build(replace(base, flags=decoder.FLAG_COMBAT, activity="",
                             target_hp=0))["state"]
    assert "(0%)" not in nohp, nohp

    # unknown faction: neutral taxi, no guessing gryphon
    neutral = pc._build(replace(base, flags=1, faction=""))["state"]
    assert neutral == "✈️ Em voo de táxi sobre Vale Estrangulacérrimo", neutral

    # in queue → LFG eye in small_image, but the PHRASE keeps showing what the
    # player is doing (the queue doesn't become the headline; only the pop does)
    eye = pc._build(replace(base, flags=4, target="", activity="lfd"))
    assert "LFG-Eye" in eye["small_image"], eye["small_image"]
    assert eye["state"].startswith("🛏️ Descansando"), eye["state"]
    assert eye["small_text"] == "Na fila de masmorra", eye["small_text"]
    # active form: the character STAYS as the large image; the form icon
    # goes to the thumbnail (user request: never swap the main image)
    bear = pc._build(replace(base, flags=0, target="", form_id=5487,
                             form="Forma de Urso"))
    assert bear["large_image"] == "race_orc_male", bear["large_image"]
    assert "bearform" in bear["small_image"], bear["small_image"]

    # identified mount: name in the phrase and the mount's own icon
    import presence as presence_mod
    presence_mod._spell_icon_cache[64658] = "ability_mount_blackdirewolf"
    ride2 = pc._build(replace(base, flags=decoder.FLAG_MOUNTED, target="",
                              mount_spell=64658, mount_name="Lobo Negro"))
    assert ride2["state"].startswith("🐎 Montado em Lobo Negro"), ride2["state"]
    # on the ground: character stays large; mount becomes the thumbnail
    assert ride2["large_image"] == "race_orc_male", ride2["large_image"]
    assert "blackdirewolf" in ride2["small_image"], ride2["small_image"]
    assert ride2["small_text"] == "Lobo Negro", ride2["small_text"]
    fly2 = pc._build(replace(base, flags=decoder.FLAG_FLYING, target="",
                             mount_spell=64658, mount_name="Lobo Negro"))
    assert fly2["state"].startswith("🐉 Voando de Lobo Negro"), fly2["state"]
    # flying: character large, mount icon in the thumbnail
    assert fly2["large_image"] == "race_orc_male", fly2["large_image"]
    assert "blackdirewolf" in fly2["small_image"], fly2["small_image"]
    assert fly2["small_text"] == "Lobo Negro", fly2["small_text"]

    # English language: same priorities, translated phrases
    pc_en = PresenceClient("0", language="en")
    en_rest = pc_en._build(replace(base, flags=4, target=""))["state"]
    assert en_rest == "🛏️ Resting — Acampamento Grom'gol", en_rest
    en_taxi = pc_en._build(replace(base, flags=1, target=""))["state"]
    assert en_taxi == "🦇 Flying a wyvern over Vale Estrangulacérrimo", en_taxi
    en_boss = pc_en._build(replace(
        base, flags=decoder.FLAG_COMBAT, activity="boss:Onyxia", target="Onyxia",
        target_hp=88, instance_name="Onyxia's Lair", instance_type="raid"))["state"]
    assert en_boss == "🐉 Facing Onyxia (88%) — Onyxia's Lair", en_boss
    en_det = pc_en._build(replace(base, flags=0, target=""))["details"]
    assert en_det == "Grubento — Orc Guerreiro 47 · XP 62%", en_det

def test_no_magic() -> None:
    img = Image.new("RGB", (600, 30), (10, 10, 10))
    try:
        decoder.decode(img)
    except decoder.DecodeError as exc:
        assert "magic" in str(exc)
    else:
        raise AssertionError("imagem sem faixa deveria falhar")


def test_freeze_guard() -> None:
    """Frozen payload detection: seq unchanged > threshold = dead frame."""
    from main import FreezeGuard

    fg = FreezeGuard(threshold=30.0)
    assert not fg.tick(seq=5, now=0.0)    # first frame is never frozen
    assert not fg.tick(seq=5, now=29.0)   # within the window
    assert fg.tick(seq=5, now=31.0)       # froze
    assert not fg.tick(seq=6, now=32.0)   # seq changed → alive again
    fg2 = FreezeGuard(threshold=30.0)
    fg2.tick(seq=9, now=0.0)
    fg2.reset()                            # window disappeared (relog)
    assert not fg2.tick(seq=9, now=100.0)  # same seq after reset is not a freeze


def test_locale_parity() -> None:
    """PT and EN must have the same keys and the same {x} placeholders — a
    token translated in only one language would become a runtime KeyError in the other."""
    import re

    import locales

    pt, en = locales.PT, locales.EN
    assert set(pt) == set(en), set(pt) ^ set(en)
    for sub in ("activity_simple", "activity_arg", "queue_small", "difficulty"):
        assert set(pt[sub]) == set(en[sub]), (sub, set(pt[sub]) ^ set(en[sub]))
    ph = lambda s: set(re.findall(r"\{(\w+)\}", s))
    for k in pt:
        if isinstance(pt[k], str):
            assert ph(pt[k]) == ph(en[k]), (k, ph(pt[k]) ^ ph(en[k]))
        elif k in ("activity_simple", "activity_arg"):
            for tok in pt[k]:
                assert ph(pt[k][tok]) == ph(en[k][tok]), (k, tok)


def test_trunc16_composed() -> None:
    """AFK + combat + long zone: truncation respects 128 UTF-16 units and the
    HP warning stays within the limit when it fits."""
    from dataclasses import replace

    from presence import PresenceClient

    pc = PresenceClient("0")
    base = decoder.decode(render(build_cells("|".join(PAYLOAD_FIELDS).encode("utf-8"))))
    st = pc._build(replace(
        base, flags=decoder.FLAG_AFK | decoder.FLAG_COMBAT, hp_pct=18,
        zone="Z" * 120, target="Ragnaros", target_level=60))["state"]
    assert len(st.encode("utf-16-le")) // 2 <= 128, len(st)
    assert st.startswith("💤 AFK"), st
    # short phrase: the HP warning survives intact
    st2 = pc._build(replace(
        base, flags=decoder.FLAG_COMBAT, hp_pct=18, target="Rag"))["state"]
    assert st2.endswith("❗18% HP"), st2


if __name__ == "__main__":
    tests = [
        test_roundtrip,
        test_multirow,
        test_checksum_detects_corruption,
        test_backward_compat_16_fields,
        test_origin_relocation,
        test_phrases,
        test_no_magic,
        test_freeze_guard,
        test_locale_parity,
        test_trunc16_composed,
    ]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"\n{len(tests)}/{len(tests)} testes passaram.")
