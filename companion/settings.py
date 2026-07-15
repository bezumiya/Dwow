"""Configuration loading and validation for the Dwow companion."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.json")
EXAMPLE_PATH = Path(__file__).with_name("config.example.json")

LANGUAGES = {"pt", "pt-br", "pt_br", "en", "en-us", "en_us"}
REGIONS = {"us", "eu", "kr", "tw"}
FLAVORS = {"era", "mop", "anniversary"}


class ConfigError(ValueError):
    pass


def _number(cfg: dict, key: str, minimum: float, maximum: float) -> None:
    try:
        value = float(cfg[key])
    except (KeyError, TypeError, ValueError):
        raise ConfigError(f"{key} precisa ser um número") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} precisa estar entre {minimum:g} e {maximum:g}")


def validate_config(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("a raiz do config.json precisa ser um objeto")
    cfg = deepcopy(raw)
    app_id = str(cfg.get("application_id", "")).strip()
    if not app_id.isdigit():
        raise ConfigError("application_id precisa ser o ID numérico do app no Discord")
    cfg["application_id"] = app_id

    defaults = {
        "window_title": "World of Warcraft", "poll_seconds": 1.0,
        "presence_min_interval": 15.0, "clear_after_seconds": 60.0,
        "language": "pt", "large_image_key": "wow_classic",
        "use_race_image": True, "show_realm": True, "show_guild": True,
        "show_xp": True, "show_gold": True,
    }
    for key, value in defaults.items():
        cfg.setdefault(key, value)
    _number(cfg, "poll_seconds", 0.2, 60)
    _number(cfg, "presence_min_interval", 1, 300)
    _number(cfg, "clear_after_seconds", 5, 3600)
    if float(cfg["clear_after_seconds"]) < float(cfg["poll_seconds"]):
        raise ConfigError("clear_after_seconds não pode ser menor que poll_seconds")

    language = str(cfg["language"]).lower()
    if language not in LANGUAGES:
        raise ConfigError("language precisa ser pt-BR ou en-US")
    cfg["language"] = "pt" if language.startswith("pt") else "en"

    bnet = cfg.setdefault("bnet", {})
    if not isinstance(bnet, dict):
        raise ConfigError("bnet precisa ser um objeto")
    # Environment variables avoid keeping secrets in config.json.
    bnet["client_id"] = os.getenv("DWOW_BNET_CLIENT_ID", bnet.get("client_id", ""))
    bnet["client_secret"] = os.getenv(
        "DWOW_BNET_CLIENT_SECRET", bnet.get("client_secret", ""))
    bnet.setdefault("enabled", False)
    bnet.setdefault("region", "us")
    bnet.setdefault("flavor", "era")
    bnet["region"] = str(bnet["region"]).lower()
    bnet["flavor"] = str(bnet["flavor"]).lower()
    if bnet["region"] not in REGIONS:
        raise ConfigError(f"bnet.region precisa ser: {', '.join(sorted(REGIONS))}")
    if bnet["flavor"] not in FLAVORS:
        raise ConfigError(f"bnet.flavor precisa ser: {', '.join(sorted(FLAVORS))}")
    if bnet["enabled"] and not (bnet["client_id"] and bnet["client_secret"]):
        raise ConfigError(
            "bnet.enabled=true exige client_id/client_secret no config ou "
            "DWOW_BNET_CLIENT_ID/DWOW_BNET_CLIENT_SECRET no ambiente")
    return cfg


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        raise ConfigError(
            f"config não encontrada: {path}. Copie {EXAMPLE_PATH.name} para config.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"JSON inválido em {path.name}, linha {exc.lineno}, coluna {exc.colno}: {exc.msg}") from exc
    return validate_config(raw)
