"""Build installable Dwow addon and companion ZIP archives."""
from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
ADDON = ROOT / "addon" / "Dwow"
COMPANION = ROOT / "companion"

ADDON_FILES = ("Protocol.lua", "Encoder.lua", "Events.lua", "Core.lua", "Discord.tga")
ADDON_VARIANTS = {
    "Classic-Era": "Dwow_Vanilla.toc",
    "Anniversary": "Dwow_Vanilla.toc",
    "TBC-Classic": "Dwow_TBC.toc",
    "MoP-Classic": "Dwow_Mists.toc",
    "Ascension": "Dwow_Ascension.toc",
}
COMPANION_FILES = (
    "main.py", "capture.py", "decoder.py", "protocol.py", "presence.py",
    "locales.py", "bnet.py", "settings.py", "profiles.py", "version.py", "requirements.txt",
    "config.example.json", "install_autostart.ps1",
)


def _version() -> str:
    text = (COMPANION / "version.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def validate() -> str:
    version = _version()
    missing = [p for p in ADDON_FILES if not (ADDON / p).is_file()]
    missing += [p for p in COMPANION_FILES if not (COMPANION / p).is_file()]
    if missing:
        raise SystemExit("Missing release files: " + ", ".join(missing))
    for toc_name in set(ADDON_VARIANTS.values()) | {"Dwow.toc"}:
        toc = (ADDON / toc_name).read_text(encoding="utf-8")
        if f"## Version: {version}" not in toc:
            raise SystemExit(f"{toc_name} version does not match companion {version}")
        if "Protocol.lua\nEncoder.lua\nEvents.lua\nCore.lua" not in toc.replace("\r\n", "\n"):
            raise SystemExit(f"{toc_name} has an invalid load order")
    return version


def build() -> list[Path]:
    version = validate()
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    outputs = []
    for label, toc_name in ADDON_VARIANTS.items():
        path = DIST / f"Dwow-Addon-{label}-v{version}.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(ADDON / toc_name, "Dwow/Dwow.toc")
            for name in ADDON_FILES:
                archive.write(ADDON / name, f"Dwow/{name}")
        outputs.append(path)
    path = DIST / f"Dwow-Companion-Windows-v{version}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in COMPANION_FILES:
            archive.write(COMPANION / name, f"Dwow-Companion/{name}")
        archive.write(ROOT / "README.pt-BR.md", "Dwow-Companion/README.pt-BR.md")
        archive.write(ROOT / "README.md", "Dwow-Companion/README.md")
        archive.write(ROOT / "CHANGELOG.md", "Dwow-Companion/CHANGELOG.md")
        archive.write(ROOT / "CHANGELOG.pt-BR.md", "Dwow-Companion/CHANGELOG.pt-BR.md")
    outputs.append(path)
    return outputs


if __name__ == "__main__":
    if "--check" in sys.argv:
        print(f"Release layout OK (v{validate()}).")
    else:
        for output in build():
            print(output.relative_to(ROOT))
