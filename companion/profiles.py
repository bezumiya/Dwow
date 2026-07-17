"""Known game-client profiles for the shared Dwow companion core."""
from __future__ import annotations

PROFILES = {
    "classic_era": {
        "window_title": "World of Warcraft",
        "bnet_flavor": "era",
        "bnet_supported": True,
    },
    "anniversary": {
        "window_title": "World of Warcraft",
        "bnet_flavor": "anniversary",
        "bnet_supported": True,
    },
    "tbc_classic": {
        "window_title": "World of Warcraft",
        "bnet_flavor": "era",
        "bnet_supported": True,
    },
    "mop_classic": {
        "window_title": "World of Warcraft",
        "bnet_flavor": "mop",
        "bnet_supported": True,
    },
    "ascension": {
        "window_title": "Ascension",
        "bnet_flavor": "era",
        "bnet_supported": False,
    },
}

DEFAULT_PROFILE = "mop_classic"


def apply_profile(cfg: dict) -> dict:
    name = str(cfg.get("client", DEFAULT_PROFILE)).lower()
    if name not in PROFILES:
        raise ValueError(
            f"client must be one of: {', '.join(sorted(PROFILES))}")
    profile = PROFILES[name]
    cfg["client"] = name
    cfg.setdefault("window_title", profile["window_title"])
    bnet = cfg.get("bnet")
    if bnet is None:
        bnet = cfg["bnet"] = {}
    elif not isinstance(bnet, dict):
        # settings.validate_config emits the localized object-type error.
        return cfg
    bnet.setdefault("flavor", profile["bnet_flavor"])
    if not profile["bnet_supported"]:
        bnet["enabled"] = False
    return cfg
