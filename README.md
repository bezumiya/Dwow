# Dwow

**🇧🇷 [Versão em português](README.pt-BR.md)** · **Latest release: v0.3.0**

> [!WARNING]
> **Dwow is still under active development.** Features, protocol details,
> configuration, and project structure may change significantly over time.
> Future updates may require additional setup or migration steps.

> [!NOTE]
> **Unofficial server compatibility:** Dwow will likely also work on private
> servers that use a compatible game client and addon APIs. The main limitation
> is the 3D character render: characters from unofficial servers do not exist
> on Battle.net and therefore cannot be found through Blizzard's API. In this
> case, Rich Presence will continue using the bundled race and gender portraits
> as a fallback. Compatibility is not guaranteed when a server modifies the
> client or its addon APIs.

Rich Presence for **World of Warcraft Classic** and **Project Ascension** that
shows on your Discord profile — in real time — what your character is doing:
fighting a boss, queued for a dungeon (with the actual LFG eye icon), flying on
your own mount, fishing, dead after a wipe… over 45 distinct states, in English
or Portuguese.

> [!IMPORTANT]
> **Project Ascension is officially supported starting with Dwow v0.3.0.**
> Download the dedicated `Dwow-Addon-Ascension` package and select
> `"client": "ascension"` in the companion configuration. This support was
> tested live on the Ascension 3.3.5 client, including window capture,
> fractional pixel decoding, character state, AFK flags, and Discord updates.

## Supported clients and packages

Dwow uses one shared addon and companion core with a small profile for each
game client. Releases generate separate, ready-to-install addon archives:

| Client | Addon package | Companion profile |
|---|---|---|
| Classic Era / Hardcore / Season of Discovery | `Dwow-Addon-Classic-Era-*` | `classic_era` |
| Anniversary | `Dwow-Addon-Anniversary-*` | `anniversary` |
| Burning Crusade Classic | `Dwow-Addon-TBC-Classic-*` | `tbc_classic` |
| Mists of Pandaria Classic | `Dwow-Addon-MoP-Classic-*` | `mop_classic` |
| Project Ascension (3.3.5) | `Dwow-Addon-Ascension-*` | `ascension` |

Ascension support uses the same protocol and Rich Presence code, with a legacy
addon manifest, older API fallbacks, its own window title, and adaptive
fractional-pixel decoding. Battle.net character renders are unavailable for
unofficial-server characters, so local race/gender portraits are used.

## Examples

<p align="center">
  <img src="dwow-aliance.png" width="49%" alt="Dwow displaying an Alliance character on Discord Rich Presence">
  <img src="dwow-horde.png" width="49%" alt="Dwow displaying a Horde character on Discord Rich Presence">
</p>

Rich Presence examples for **Alliance** and **Horde** characters, including
portrait, class, level, XP, mount, location, and session time.

## Limitations

- **The Discord card does not update every second.** The addon collects and
  exports character state once per second, but the companion enforces a minimum
  interval of roughly 15 seconds between updates. Discord also applies its own
  caching and propagation delay, so changes may take a few seconds to appear
  on the profile.
- **The 3D character render is not updated in real time.** The image comes from
  the Battle.net API, which usually refreshes the character only after logging
  out and allowing Blizzard to synchronize the data. Recent equipment or
  appearance changes may continue showing the previous render.
- **Very short states may never appear.** An activity that starts and ends
  within Discord's update window can be replaced by the next state before it
  reaches the card.
- **The addon cannot force instant updates.** This limitation exists outside
  Lua: the addon continues transmitting pixels normally, while the companion
  and Discord control when Rich Presence is published and displayed.

```
┌────────────────────┐   encoded pixels        ┌──────────────────────┐
│  WoW Classic       │ ──── (on screen) ─────► │  Companion (Python)  │
│  + Dwow addon      │                         │  capture → decode    │
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

Download the ZIP for your game flavor from [GitHub Releases](https://github.com/bezumiya/Dwow/releases),
then extract the `Dwow` folder into your AddOns directory. You can also copy
`addon/Dwow` directly when installing from source:

When installing from source, copy `addon/Dwow` into the AddOns directory and
copy the matching manifest over `Dwow.toc`:

```
World of Warcraft\_classic_era_\Interface\AddOns\Dwow   (Classic Era / Hardcore / SoD)
World of Warcraft\_classic_\Interface\AddOns\Dwow       (MoP Classic)
World of Warcraft\_anniversary_\Interface\AddOns\Dwow   (Anniversary)
C:\Ascension\Launcher\resources\ascension-live\Interface\AddOns\Dwow (Ascension)
```

| Client | Source manifest |
|---|---|
| Classic Era / Anniversary | `Dwow_Vanilla.toc` |
| TBC Classic | `Dwow_TBC.toc` |
| MoP Classic | `Dwow_Mists.toc` |
| Ascension | `Dwow_Ascension.toc` |

In game, `/dwow` toggles the export and `/dwow status` prints the current
payload (useful for troubleshooting).

### 2. Create a Discord application

1. Go to <https://discord.com/developers/applications> → **New Application**.
   Name it `World of Warcraft Classic` (this name shows as the game title).
2. Copy the **Application ID**.
3. (Optional, for portraits) Under **Rich Presence → Art Assets**, upload
   your art with keys `wow_classic`, `class_<class>` and
   `race_<race>_<male|female>`.

   All **38 upload-ready images** are available in [`assets_discord`](assets_discord/README.md),
   including the required keys and Developer Portal setup instructions.

### 3. Configure the companion

```bash
cd companion
copy config.example.json config.json
```

Edit `config.json`:

| Key | Meaning |
|---|---|
| `application_id` | your Discord Application ID (required) |
| `client` | `classic_era`, `anniversary`, `tbc_classic`, `mop_classic`, or `ascension`; selects safe defaults |
| `window_title` | optional override for the selected client's window title |
| `language` | `"auto"`, `"pt"` or `"en"` — card language; auto detects Windows |
| `log_language` | `"auto"`, `"pt"` or `"en"` — operational log language |
| `capture_method` | `"auto"` tries fast BitBlt and falls back to PrintWindow |
| `clear_after_seconds` | delay before clearing after the WoW window closes |
| `stale_clear_after_seconds` | longer tolerance for temporary invalid captures while WoW remains open |
| `infer_afk_after_seconds` | infer AFK after this long unfocused when a minimized window cannot be captured (`0` disables) |
| `use_race_image`, `show_realm`, `show_guild`, `show_xp`, `show_gold` | toggle card details |
| `bnet.*` | optional: your character's 3D render via the Battle.net API — create a free client at <https://develop.battle.net>, fill `client_id`/`client_secret`, set `enabled: true`, pick `region` (`us`/`eu`) and `flavor` (`era`/`mop`/`anniversary`) |

For Project Ascension, set `"client": "ascension"`. This selects the
`Ascension` window automatically and disables Battle.net rendering.

> **Never commit `config.json`** — it holds your secrets and is gitignored.

### 4. Run

```bash
python main.py
```

Before running normally, check the complete setup with:

```bash
python main.py --diagnose
```

The diagnostic validates the configuration, WoW capture, pixel protocol and
Discord connection without publishing a Rich Presence card.

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
- **Robust capture**: lazy BitBlt/PrintWindow fallback, game-window matching,
  DPI awareness, viewport-addon relocation, frozen-game detection and checksum.
- **Diagnostic logs**: capture method, failure/recovery episodes, AFK transitions,
  clear reasons and a five-minute health summary, localized from Windows.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Read failures/checksum errors | auto capture preserves the last presence and tries the fallback; check `/dwow status`, MSAA and windowed/borderless if failures persist |
| Presence never updates | Discord desktop must be running before the companion; check `application_id` |
| Blurry/outdated render | the Battle.net render only refreshes on logout; brand-new characters 404 for a few hours (race portrait is used meanwhile) |
| Queue eye missing | `/reload` after updating the addon; LFD/RF queues exist on MoP only |

## License / disclaimer

Personal project, not affiliated with Blizzard Entertainment or Discord.
World of Warcraft and its assets are © Blizzard Entertainment. The addon only
reads official API data and renders pixels; no warranty is given.

## Release notes

See [CHANGELOG.md](CHANGELOG.md) for version history and upgrade notes.
