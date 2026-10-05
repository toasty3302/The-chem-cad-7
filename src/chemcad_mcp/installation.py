"""Locate licensed runtime resources without starting CHEMCAD."""

from __future__ import annotations

import os
import re
from pathlib import Path


def installation_directory() -> Path:
    override = os.environ.get("CHEMCAD_MCP_INSTALL_DIR")
    if override:
        candidates = [Path(override)]
    else:
        candidates = []
        if os.name == "nt":
            import winreg

            from .configure import CLSID

            try:
                with winreg.OpenKey(
                    winreg.HKEY_CLASSES_ROOT,
                    rf"CLSID\{CLSID}\LocalServer32",
                    0,
                    winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
                ) as key:
                    command = winreg.QueryValueEx(key, None)[0]
                match = re.match(r'\s*"([^"]+)"|\s*(.*?\.exe)\b', command, re.I)
                if match:
                    candidates.append(Path(match[1] or match[2]).parent)
            except OSError:
                pass
        candidates.append(
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Chemstations"
            / "CHEMCAD NXT"
        )
    for directory in candidates:
        if directory.is_dir() and (directory / "$COMP.LAB").is_file():
            return directory.resolve()
    raise FileNotFoundError(
        "CHEMCAD installation not found; set CHEMCAD_MCP_INSTALL_DIR"
    )


def examples_directory() -> Path:
    override = os.environ.get("CHEMCAD_MCP_EXAMPLES_DIR")
    directory = (
        Path(override)
        if override
        else (
            Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
            / "Chemstations"
            / "CHEMCAD NXT"
            / "Examples"
        )
    )
    return directory.resolve(strict=True)


def parameter_definitions(category: str) -> list[dict]:
    category = category.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_]{1,12}", category):
        raise ValueError("Invalid equipment category")
    path = installation_directory() / f"${category}.LAB"
    parameters = []
    for line in path.read_text(encoding="cp1252").splitlines():
        match = re.match(
            r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.+)", line
        )
        if match:
            position, unit, kind, fmt, required, print_zero = map(
                int, match.groups()[:6]
            )
            label = match[7].rstrip("\x1a").strip()
            parameters.append(
                {
                    # The legacy array's first element is the equipment ID.
                    "parameter_id": position + 1,
                    "specification_position": position,
                    "name": re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_"),
                    "label": label,
                    "engineering_unit_id": unit,
                    "integer": kind == 1,
                    "required": bool(required),
                }
            )
    if not parameters:
        raise ValueError(f"No parameter definitions in {path}")
    return parameters
