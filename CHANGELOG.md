# Changelog

**[Português (Brasil)](CHANGELOG.pt-BR.md)**

## v0.3.0 — Project Ascension and multi-client releases

### Added

- Official Project Ascension 3.3.5 support, tested live with Discord Rich Presence.
- Dedicated `Dwow_Ascension.toc` manifest and `Dwow-Addon-Ascension` release package.
- Companion profiles for Classic Era, Anniversary, TBC Classic, MoP Classic,
  and Ascension.
- Adaptive fractional-pixel decoding for legacy Wrath-derived clients.
- English-first documentation for Discord art assets, with a PT-BR translation.

### Improved

- Faster BitBlt capture with safe PrintWindow fallback.
- More resilient AFK, minimized-window, stale-capture, and frozen-game handling.
- Capture recovery, health, AFK transition, and presence publication logs.
- Automatic English or Portuguese operational logs based on the system language.
- Legacy API fallbacks for timers, textures, group information, movement, and mounts.

### Packaging

- Releases now provide separate addon ZIPs for Classic Era, Anniversary,
  TBC Classic, MoP Classic, and Ascension, plus one shared Windows companion.
- Existing users should download the addon ZIP matching their client.
- Ascension users must set `"client": "ascension"`; Battle.net rendering is
  disabled automatically because unofficial characters are not in Blizzard's API.
