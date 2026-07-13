# DiscordWow

**🇧🇷 [Versão em português](README.pt-BR.md)**

Rich Presence for **World of Warcraft Classic** (Classic Era, Anniversary and
MoP Classic) that shows on your Discord profile — in real time — what your
character is doing: fighting a boss, queued for a dungeon (with the actual LFG
eye icon), flying on your own mount, fishing, dead after a wipe… over 45
distinct states, in English or Portuguese.

```
┌────────────────────┐   encoded pixels        ┌──────────────────────┐
│  WoW Classic       │ ──── (on screen) ─────► │  Companion (Python)  │
│  + DiscordWow addon│                         │  capture → decode    │
│  (official API,    │                         │  → Rich Presence     │
│   zero injection)  │                         └──────────┬───────────┘
└────────────────────┘                                    ▼
                                                      Discord
```

**Why pixels?** WoW addons are sandboxed: no network access, no file writes
during play. The addon draws character data as a tiny strip of colored cells
(3 px tall) in the top-left corner; the companion reads that strip by
capturing the game window — the same technique CraftPresence uses. Details in
[docs/PROTOCOL.md](docs/PROTOCOL.md).

**Safe:** the addon only uses the official addon API; the companion only
*reads* the screen — no injection, no memory reading, no input automation.
Never combine this project with input automation: that is Blizzard's red line.

## Requirements

- Windows 10/11, Discord desktop app running
- Python 3.10+ with `pypresence` and `Pillow` (`pip install pypresence pillow`)
- WoW in **windowed or borderless** mode, anti-aliasing (MSAA) disabled

## Setup

### 1. Install the addon

Copy `addon/DiscordWow` into the AddOns folder of the flavor you play:

```
World of Warcraft\_classic_era_\Interface\AddOns\DiscordWow   (Classic Era / Hardcore / SoD)
World of Warcraft\_classic_\Interface\AddOns\DiscordWow       (MoP Classic)
World of Warcraft\_anniversary_\Interface\AddOns\DiscordWow   (Anniversary)
```

In game, `/dwow` toggles the export and `/dwow status` prints the current
payload (useful for troubleshooting).

### 2. Create a Discord application

1. Go to <https://discord.com/developers/applications> → **New Application**.
   Name it `World of Warcraft Classic` (this name shows as the game title).
2. Copy the **Application ID**.
3. (Optional, for portraits) Under **Rich Presence → Art Assets**, upload
   your art with keys `wow_classic`, `class_<class>` and
   `race_<race>_<male|female>`.

### 3. Configure the companion

```bash
cd companion
copy config.example.json config.json
```

Edit `config.json`:

| Key | Meaning |
|---|---|
| `application_id` | your Discord Application ID (required) |
| `language` | `"pt"` or `"en"` — language of the card phrases |
| `use_race_image`, `show_realm`, `show_guild`, `show_xp`, `show_gold` | toggle card details |
| `bnet.*` | optional: your character's 3D render via the Battle.net API — create a free client at <https://develop.battle.net>, fill `client_id`/`client_secret`, set `enabled: true`, pick `region` (`us`/`eu`) and `flavor` (`era`/`mop`/`anniversary`) |
| `widget.*` | experimental Profile Widget support (off by default) |

> **Never commit `config.json`** — it holds your secrets and is gitignored.

### 4. Run

```bash
python main.py
```

With WoW and Discord open, your profile updates within ~15 s (Discord's rate
limit). The presence clears automatically ~60 s after the game closes.

**Auto-start (recommended):** register a hidden logon task so the companion is
always waiting for the game — run once in PowerShell:

```powershell
cd companion
.\install_autostart.ps1            # installs and starts (invisible, logs to companion.log)
.\install_autostart.ps1 -Remove    # uninstalls
```

## Features

- **45+ states** with priority ordering: death/wipe, boss encounters (with
  HP%), PvP flag/orb carrying, drowning and fatigue timers, taxi flights by
  faction, professions, auction house, mail, vendor/repair, duels,
  resurrections, idling…
- **Dungeon/raid queue**: the real LFG eye texture appears as the small icon
  while queued (LFD/RF on MoP, LFG Tool on Era/Anniversary, BG queues
  everywhere); a queue pop takes over the card for a few seconds.
- **Your actual mount**: its name in the phrase and its own icon in the small
  slot — your character always stays as the large image; live states (flying,
  forms, death…) show as the small icon.
- **Druid/shaman/priest/lock forms**: bear, cat, moonkin, travel, flight,
  ghost wolf, shadowform… each with its own icon, updated live.
- **3D character render** (optional, Battle.net API) as the card image, with
  race portraits as fallback.
- **Robust capture**: game-window matching, DPI awareness, viewport-addon
  strip relocation, frozen-game detection, checksummed payload.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "no valid data" in the log | character must be in world; check `/dwow status`; disable MSAA; use windowed/borderless |
| Presence never updates | Discord desktop must be running before the companion; check `application_id` |
| Blurry/outdated render | the Battle.net render only refreshes on logout; brand-new characters 404 for a few hours (race portrait is used meanwhile) |
| Queue eye missing | `/reload` after updating the addon; LFD/RF queues exist on MoP only |

## License / disclaimer

Personal project, not affiliated with Blizzard Entertainment or Discord.
World of Warcraft and its assets are © Blizzard Entertainment. The addon only
reads official API data and renders pixels; no warranty is given.
