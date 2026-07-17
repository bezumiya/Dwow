"""Configuration loading and validation for the Dwow companion."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

from profiles import apply_profile

CONFIG_PATH = Path(__file__).with_name("config.json")
EXAMPLE_PATH = Path(__file__).with_name("config.example.json")

LANGUAGES = {"auto", "pt", "pt-br", "pt_br", "en", "en-us", "en_us"}
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
    try:
        apply_profile(cfg)
    except ValueError as exc:
        raise ConfigError(str(exc)) from None
    app_id = str(cfg.get("application_id", "")).strip()
    if not app_id.isdigit():
        raise ConfigError("application_id precisa ser o ID numérico do app no Discord")
    cfg["application_id"] = app_id

    defaults = {
        "poll_seconds": 1.0,
        "presence_min_interval": 15.0, "clear_after_seconds": 60.0,
        "stale_clear_after_seconds": 900.0, "capture_method": "auto",
        "infer_afk_after_seconds": 300.0,
        "language": "auto", "log_language": "auto", "large_image_key": "wow_classic",
        "use_race_image": True, "show_realm": True, "show_guild": True,
        "show_xp": True, "show_gold": True,
    }
    for key, value in defaults.items():
        cfg.setdefault(key, value)
    _number(cfg, "poll_seconds", 0.2, 60)
    _number(cfg, "presence_min_interval", 1, 300)
    _number(cfg, "clear_after_seconds", 5, 3600)
    _number(cfg, "stale_clear_after_seconds", 60, 86400)
    _number(cfg, "infer_afk_after_seconds", 0, 3600)
    if float(cfg["clear_after_seconds"]) < float(cfg["poll_seconds"]):
        raise ConfigError("clear_after_seconds não pode ser menor que poll_seconds")

    language = str(cfg["language"]).lower()
    if language not in LANGUAGES:
        raise ConfigError("language precisa ser auto, pt-BR ou en-US")
    from log_i18n import detect_language
    cfg["language"] = detect_language() if language == "auto" else (
        "pt" if language.startswith("pt") else "en")
    log_language = str(cfg.get("log_language", "auto")).lower()
    if log_language not in LANGUAGES:
        raise ConfigError("log_language precisa ser auto, pt-BR ou en-US")
    cfg["log_language"] = detect_language() if log_language == "auto" else (
        "pt" if log_language.startswith("pt") else "en")
    cfg["capture_method"] = str(cfg["capture_method"]).lower()
    if cfg["capture_method"] not in {"auto", "bitblt", "printwindow"}:
        raise ConfigError("capture_method precisa ser auto, bitblt ou printwindow")

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
