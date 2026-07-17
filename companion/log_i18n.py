"""Tiny runtime locale selector for operational logs (Portuguese/English)."""
from __future__ import annotations

import locale

_language = "pt"


def detect_language() -> str:
    """English Windows locales use English; every other locale defaults to PT."""
    try:
        value = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""
    except Exception:
        value = ""
    return "en" if value.lower().startswith("en") else "pt"


def configure(language: str) -> None:
    global _language
    _language = "en" if str(language).lower().startswith("en") else "pt"


def text(pt: str, en: str) -> str:
    return en if _language == "en" else pt
