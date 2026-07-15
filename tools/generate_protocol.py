"""Generate the Lua/Python protocol constants from protocol/schema.json.

Usage:
    python tools/generate_protocol.py          # update generated files
    python tools/generate_protocol.py --check  # fail when generated files drift
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "protocol" / "schema.json"
PY_PATH = ROOT / "companion" / "protocol.py"
LUA_PATH = ROOT / "addon" / "Dwow" / "Protocol.lua"


def _python(schema: dict) -> str:
    fields = schema["fields"]
    required = schema["required_field_count"]
    flags = schema["flags"]
    lines = [
        '"""Generated protocol constants. Do not edit by hand.',
        "Run: python tools/generate_protocol.py",
        '"""',
        "",
        f"PROTOCOL_VERSION = {schema['protocol_version']}",
        f"CELL_PX = {schema['cell_px']}",
        f"CELLS_PER_ROW = {schema['cells_per_row']}",
        f"MAX_PAYLOAD_BYTES = {schema['max_payload_bytes']}",
        f"MAGIC_A = {tuple(schema['magic_a'])!r}",
        f"MAGIC_B = {tuple(schema['magic_b'])!r}",
        f"REQUIRED_FIELD_COUNT = {required}",
        "",
        "FIELDS = [",
    ]
    lines.extend(f"    {field!r}," for field in fields[:required])
    lines += ["]", "", "OPTIONAL_FIELDS = ["]
    lines.extend(f"    {field!r}," for field in fields[required:])
    lines += ["]", "", "ALL_FIELDS = FIELDS + OPTIONAL_FIELDS", ""]
    for name, value in flags.items():
        lines.append(f"FLAG_{name.upper()} = {value}")
    return "\n".join(lines) + "\n"


def _lua(schema: dict) -> str:
    field_indexes = {name: index for index, name in enumerate(schema["fields"], 1)}
    lines = [
        "-- Generated protocol constants. Do not edit by hand.",
        "-- Run: python tools/generate_protocol.py",
        "local _, ns = ...",
        "",
        "ns.PROTOCOL = {",
        f"    VERSION = {schema['protocol_version']},",
        f"    CELL_PX = {schema['cell_px']},",
        f"    CELLS_PER_ROW = {schema['cells_per_row']},",
        f"    MAX_PAYLOAD_BYTES = {schema['max_payload_bytes']},",
        "    MAGIC_A = { " + ", ".join(map(str, schema["magic_a"])) + " },",
        "    MAGIC_B = { " + ", ".join(map(str, schema["magic_b"])) + " },",
        "    FLAGS = {",
    ]
    lines.extend(f"        {name.upper()} = {value}," for name, value in schema["flags"].items())
    lines += ["    },", "    FIELD_LIMITS = {"]
    lines.extend(
        f"        [{field_indexes[name]}] = {value},"
        for name, value in schema["field_limits"].items()
    )
    lines += ["    },", "}"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    outputs = {PY_PATH: _python(schema), LUA_PATH: _lua(schema)}
    stale = []
    for path, expected in outputs.items():
        actual = path.read_text(encoding="utf-8") if path.exists() else None
        if actual != expected:
            stale.append(path.relative_to(ROOT))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8", newline="\n")
    if args.check and stale:
        print("Generated protocol files are stale:")
        for path in stale:
            print(f"  - {path}")
        print("Run: python tools/generate_protocol.py")
        return 1
    if not args.check:
        print("Protocol files generated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
