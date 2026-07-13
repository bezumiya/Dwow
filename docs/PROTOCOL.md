# DiscordWow pixel protocol — version 1

**🇧🇷 [Versão em português](PROTOCOLO.md)**

Data-export channel from the addon (Lua, inside WoW) to the companion app
(Python, outside the game). The addon draws a strip of colored cells in the
top-left corner of the screen; the companion captures the window and decodes
the colors.

**Any change to this protocol must be mirrored in two places:**
`addon/DiscordWow/Encoder.lua` (encoder) and `companion/decoder.py` (decoder).

## Geometry

- Each **cell** is a square of `CELL_PX` physical pixels (default: **3**).
  The companion reads only the center pixel of each cell, so slight
  anti-aliasing blur on the edges does not corrupt the read.
- Cells are laid out left to right, wrapping every `CELLS_PER_ROW` cells
  (default: **128**), anchored at the top-left corner of the screen (0,0).
- The addon uses `SetIgnoreParentScale` + `SetScale(768 / physicalHeight)` so
  that 1 UI unit = 1 physical pixel, regardless of the player's UI scale.

## Cell layout

Each cell carries 3 bytes (R, G, B).

| Cell | Contents |
|---|---|
| 0 | Magic A: RGB **(192, 255, 238)** — anchor/calibration |
| 1 | Magic B: RGB **(13, 21, 234)** — anchor/calibration |
| 2 | R = protocol version (**1**), G = payload size (low byte), B = size (high byte) |
| 3 | R = sequence counter (0–255, increments every redraw; heartbeat), G/B = reserved (0) |
| 4 | **Adler-24** checksum of the payload: R = bits 23–16, G = bits 15–8, B = bits 7–0 |
| 5+ | Payload: UTF-8 bytes, 3 per cell, last cell zero-padded |

The companion validates both magics with a tolerance of ±4 per channel
(detects an overlay covering the strip, gamma/HDR shifting colors, or the
wrong window). The remaining bytes are read with no tolerance — the checksum
guards against corruption.

## Adler-24 checksum

Classic Adler-32 (mod 65521) truncated to the low 24 bits so it fits in one
cell: in Python, `zlib.adler32(payload) & 0xFFFFFF`; in Lua, a direct
implementation in `Encoder.lua` (`ns.Adler24`).

## Payload

UTF-8 string with `|`-separated fields, in this order (the addon replaces any
`|` inside a value with `/`):

| # | Field | Example | Notes |
|---|---|---|---|
| 1 | name | `Grubento` | `UnitName("player")` |
| 2 | realm | `Firemaw` | `GetRealmName()` |
| 3 | class_token | `WARRIOR` | language-independent; used as asset key |
| 4 | class_name | `Guerreiro` | localized |
| 5 | race | `Orc` | localized |
| 6 | level | `47` | integer |
| 7 | zone | `Profundezas Rocha Negra` | `GetRealZoneText()` |
| 8 | subzone | `Taverna` | may be empty |
| 9 | instance_name | `Blackrock Depths` | empty outside instances |
| 10 | instance_type | `party` | `none`, `party`, `raid`, `pvp`, `arena` or `scenario` (MoP) |
| 11 | hp_pct | `100` | 0–100 |
| 12 | dead | `0` | `1` = dead or ghost |
| 13 | xp_pct | `62` | 0–100 |
| 14 | group_size | `5` | 0 = solo |
| 15 | group_max | `5` | instance maxPlayers (e.g. 3, 5, 10, 15, 25, 40); fallback 5/40 outside instances |
| 16 | guild | `Os Bravos` | may be empty |
| 17 | race_token | `NightElf` | optional appendix; race file token (`Scourge` = undead) |
| 18 | gender | `m` | optional appendix; `m` or `f` (`UnitSex` 3 = f) |
| 19 | flags | `34` | appendix; bitfield: 1 taxi, 2 combat, 4 resting, 8 mounted (never together with taxi), 16 swimming, 32 AFK, 64 ghost, 128 stealthed, 256 flying (`IsFlying`), 512 falling (2 consecutive ticks), 1024 fishing |
| 20 | target | `Ragnaros` | appendix; current live hostile target (empty if none) |
| 21 | target_hp | `43` | appendix; target health in % |
| 22 | target_class | `worldboss` | appendix; target's `UnitClassification` |
| 23 | money | `1234567` | appendix; money in copper (÷10000 = gold) |
| 24 | faction | `Horde` | appendix; `UnitFactionGroup` token (infers the taxi creature) |
| 25 | form | `Forma de Viagem` | appendix; localized name of the active shapeshift form, empty when none |
| 26 | form_id | `783` | appendix; spellID of the form (0 when the client uses the old signature without spellID) |
| 27 | activity | `hearth:Orgrimmar` | appendix; current special activity: `token` or `token:arg` (table below), empty when none |
| 28 | difficulty | `2` | appendix; `difficultyID` from `GetInstanceInfo` (0 outside instances; 2=Heroic, 3=10p, 4=25p, 5=10H, 6=25H, 7=LFR, 8=Challenge, 9=40p) |
| 29 | target_level | `43` | appendix; `UnitLevel("target")` of the hostile target (`-1` = "??", 0 = no target) |
| 30 | mount_spell | `64658` | appendix; spellID of the active mount via `C_MountJournal.GetMountInfoByID` (`isActive`); 0 when dismounted |
| 31 | mount_name | `Lobo Negro` | appendix; localized name of the active mount |

### Activity tokens (field 27)

The addon picks ONE token per tick (the check order in `BuildActivity` is the
priority). Format `token` or `token:argument`; the argument never contains `|`.

| Token | Arg | Meaning |
|---|---|---|
| `flag` | — | carrying a battleground flag/orb (auras 23333/23335/34976 + Kotmogu orbs 121164/121175/121176/121177) |
| `boss:{name}` | encounter name | active boss fight (`ENCOUNTER_START/END`) |
| `breath:{pct}` | breath % | underwater losing air (`GetMirrorTimerProgress`, only with `scale < 0` = draining) |
| `fatigue:{pct}` | fatigue % | in deadly fatigue waters (`EXHAUSTION` timer draining) |
| `hearth:{place}` | bind location | casting Hearthstone (8690) or Astral Recall (556) |
| `teleport:{city}` / `portal:{city}` | city | mage teleport/portal (audited spellID table) |
| `smelt` `disenchant` `mine` `herb` `skin` `prospect` `mill` | — | profession cast in progress (matched by spell name) |
| `firstaid` | — | channeling a bandage (name == `GetSpellInfo(746)`) |
| `res:{name}` | resurrector | `RESURRECT_REQUEST` (expires on revive or after 60 s) |
| `spirit:{s}` | seconds | ghost near the Spirit Healer |
| `duel:{name}` | opponent | `DUEL_REQUESTED`→`DUEL_FINISHED` (cleared on loading/10 min) |
| `trade:{name}` | partner | trade window open (`UnitName("NPC")`) |
| `cinematic` | — | `CINEMATIC_START/STOP` + `PLAY_MOVIE/STOP_MOVIE` |
| `vehicle:{name}` | vehicle | `UnitInVehicle` (MoP) |
| `bgwin` `bgloss` `bgtie` | — | `GetBattlefieldWinner` vs own faction |
| `ah` `mail` `bank` `guildbank` `vendor` `repair` `trainer` `stable` `barber` `read` `taximap` `petition` | — | UI panels (SHOW/CLOSED pairs; `repair` requires cost > 0) |
| `invite:{name}` | inviter | pending group invite (expires 60 s/on joining) |
| `feign` | — | Feign Death (aura 5384; `UnitIsFeignDeath` does not work on the player itself) |
| `eat` `drink` `eatdrink` | — | auras named == `GetSpellInfo(433)`/`(430)` |
| `floatfall` | — | falling with Slow Fall/Levitate (auras 130/1706) |
| `waterwalk` | — | Water Walking (auras 546/3714/11319) while out of water |
| `tram` | — | instanceID 369 (Deeprun Tram), no IsInInstance gate |
| `ffa` | — | `UnitIsPVPFreeForAll` |
| `skull` | — | `GetRaidTargetIndex("player") == 8` |
| `lowdur:{pct}` | durability % | average < 25% or a broken piece (slots 1–18, polled every 10 s) |
| `bgqueue:{bg}` / `bgconfirm:{bg}` | map | battleground queue/invite (`GetBattlefieldStatus`) |
| `lfd` `rf` | — | queued in the Dungeon/Raid Finder (`GetLFGMode`, MoP only) |
| `lfgpop` | — | queue popped: proposal/role check pending (urgent, high priority) |
| `lfgapp` / `lfglist` | — | applied to a premade group / own group listed (`C_LFGList`, all flavors) |
| `idle:{min}` | minutes | idle ≥ 5 min with no combat/cast/movement |

New fields may only be **appended at the end** (the decoder ignores extra
fields); removing or reordering fields requires a protocol version bump.

The payload is capped at **`MAX_PAYLOAD_BYTES` = 600 bytes**; the addon
truncates the excess by bytes (a UTF-8 character cut in half becomes U+FFFD in
the decoder — cosmetic, never an error).

## Strip location

The strip normally sits at (0,0), but viewport addons (which shift the
`WorldFrame` to make room for UI art) can move it. The decoder first tries the
last known origin; if the magic is not there, it scans the top-left region
(`SEARCH_W`×`SEARCH_H` = 600×300 px) for the Magic A/Magic B pair and caches
the new origin.

## Behavior

- The addon redraws the strip **once per second**, even with no data change —
  the sequence counter advances and serves as a heartbeat.
- `/dwow` in game toggles the strip (hidden = the companion loses the magic
  and clears the presence after `clear_after_seconds`).
- The companion only sends a Discord update when the relevant data changes
  **and** respecting the minimum 15 s interval between updates (Discord's
  historical presence limit).
