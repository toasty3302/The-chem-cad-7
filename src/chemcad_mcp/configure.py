"""Windows client configuration, with backups and no COM activation."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import tomlkit

CLIENTS = ("claude-code", "claude-desktop", "codex", "opencode")
CLSID = "{2B03C5E1-25B6-11D4-BBD3-0050DACD255C}"
_STRING = r'"(?:\\.|[^"\\])*"'
_COMMENTS = re.compile(_STRING + r"|//[^\r\n]*|/\*[\s\S]*?\*/")
_TRAILING_COMMA = re.compile(_STRING + r"|,(?=\s*[}\]])")


def _clean_jsonc(text: str) -> str:
    """Mask comments and trailing commas without changing character offsets."""
    text = _COMMENTS.sub(
        lambda m: m[0] if m[0].startswith('"') else re.sub(r"[^\r\n]", " ", m[0]),
        text,
    )
    return _TRAILING_COMMA.sub(lambda m: m[0] if m[0].startswith('"') else " ", text)


def read_config(path: Path):
    if not path.exists():
        return {}, ""
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".toml":
        value = tomlkit.parse(text)
    else:
        value = json.loads(_clean_jsonc(text) if path.suffix == ".jsonc" else text)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a configuration object: {path}")
    return value, text


def server_config(client: str, python: Path) -> tuple[str, dict]:
    python = str(python)
    args = ["-m", "chemcad_mcp.server"]
    env = {"CHEMCAD_MCP_TIMEOUT": "180"}
    if client == "opencode":
        return "mcp", {
            "type": "local",
            "command": [python, *args],
            "enabled": True,
            "timeout": 200000,
            "environment": env,
        }
    if client == "codex":
        return "mcp_servers", {
            "command": python,
            "args": args,
            "startup_timeout_sec": 45,
            "tool_timeout_sec": 200,
            "enabled": True,
            "env": env,
        }
    config = {"command": python, "args": args, "env": env}
    if client == "claude-code":
        config["type"] = "stdio"
    return "mcpServers", config


def client_paths(config_root: Path | None = None) -> dict[str, list[Path]]:
    """Respect custom client locations; config_root isolates setup for tests."""
    user_root = config_root or Path.home()
    if config_root is not None:
        appdata = user_root / "AppData" / "Roaming"
        codex_dir = user_root / ".codex"
        opencode_dir = user_root / ".config" / "opencode"
        claude_path = user_root / ".claude.json"
        explicit_opencode = None
    else:
        appdata = Path(os.environ.get("APPDATA", user_root / "AppData" / "Roaming"))
        codex_dir = Path(os.environ.get("CODEX_HOME") or user_root / ".codex")
        opencode_dir = (
            Path(os.environ.get("XDG_CONFIG_HOME") or user_root / ".config")
            / "opencode"
        )
        claude_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        claude_path = (
            Path(claude_dir) / ".claude.json"
            if claude_dir
            else user_root / ".claude.json"
        )
        explicit_opencode = os.environ.get("OPENCODE_CONFIG")
    # Update both existing files so a JSONC override cannot hide the JSON entry.
    opencode_paths = [opencode_dir / "opencode.json", opencode_dir / "opencode.jsonc"]
    opencode_paths = [
        path for path in opencode_paths if path.exists()
    ] or opencode_paths[:1]
    if explicit_opencode:
        opencode_paths.append(Path(explicit_opencode).expanduser().resolve())
    return {
        "claude-code": [claude_path],
        "claude-desktop": [appdata / "Claude" / "claude_desktop_config.json"],
        "codex": [codex_dir / "config.toml"],
        "opencode": list(dict.fromkeys(opencode_paths)),
    }


def _members(clean: str, start: int):
    """Find direct object member value spans in comment-masked JSON."""
    if clean[start] != "{":
        raise ValueError("Expected an object for the MCP section")
    decoder = json.JSONDecoder()
    members = {}
    index = start + 1
    while True:
        while clean[index].isspace() or clean[index] == ",":
            index += 1
        if clean[index] == "}":
            return members, index
        key_start = index
        key, index = decoder.raw_decode(clean, index)
        while clean[index].isspace():
            index += 1
        if clean[index] != ":":
            raise ValueError("Expected ':' after configuration key")
        index += 1
        while clean[index].isspace():
            index += 1
        value_start = index
        _, index = decoder.raw_decode(clean, index)
        members[key] = (key_start, value_start, index)


def _set_json_member(text: str, start: int, key: str, value: dict) -> str:
    clean = _clean_jsonc(text)
    members, closing = _members(clean, start)
    if key in members:
        key_start, value_start, value_end = members[key]
        indent = re.match(r"[ \t]*", text[text.rfind("\n", 0, key_start) + 1 :])[0]
        rendered = json.dumps(value, indent=2, ensure_ascii=False).replace(
            "\n", "\n" + indent
        )
        return text[:value_start] + rendered + text[value_end:]
    closing_indent = re.match(r"[ \t]*", text[text.rfind("\n", 0, closing) + 1 :])[0]
    indent = closing_indent + "  "
    rendered = json.dumps(value, indent=2, ensure_ascii=False).replace(
        "\n", "\n" + indent
    )
    insertion = f"\n{indent}{json.dumps(key)}: {rendered}\n{closing_indent}"
    prefix = text[:closing]
    if members:
        last_end = list(members.values())[-1][2]
        # A trailing comma may already exist before comments and the closing brace.
        commentless = _COMMENTS.sub(
            lambda m: m[0] if m[0].startswith('"') else "", text[last_end:closing]
        )
        if "," not in commentless:
            prefix = text[:last_end] + "," + text[last_end:closing]
    return prefix + insertion + text[closing:]


def merged_config(path: Path, section: str, server: dict) -> str | None:
    """Return only the requested change; preserve TOML/JSONC comments elsewhere."""
    original, text = read_config(path)
    existing_section = original.get(section, {})
    if not isinstance(existing_section, dict):
        raise ValueError(f"Expected an object for {section} in {path}")
    if existing_section.get("chemcad") == server:
        return None
    expected = copy.deepcopy(original)
    expected.setdefault(section, {})["chemcad"] = server
    if path.suffix == ".toml":
        document = tomlkit.parse(text)
        if section not in document:
            document[section] = tomlkit.table()
        document[section]["chemcad"] = server
        result = tomlkit.dumps(document)
        parsed = tomlkit.parse(result)
    else:
        text = text or "{}\n"
        clean = _clean_jsonc(text)
        root_start = len(clean) - len(clean.lstrip())
        members, _ = _members(clean, root_start)
        if section in members:
            result = _set_json_member(text, members[section][1], "chemcad", server)
        else:
            result = _set_json_member(text, root_start, section, {"chemcad": server})
        parsed = json.loads(_clean_jsonc(result))
    if parsed != expected:
        raise ValueError(f"Refusing to modify unrelated settings in {path}")
    return result


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def configure(
    clients, python: Path, output_dir: Path, *, generate_only=False, config_root=None
):
    targets = client_paths(config_root)
    plans = []
    # Validate every existing selected config before touching any of them.
    for client in dict.fromkeys(clients):
        section, server = server_config(client, python)
        for path in targets[client]:
            if not generate_only:
                plans.append((path, merged_config(path, section, server)))
    for client in dict.fromkeys(clients):
        section, server = server_config(client, python)
        extension = "toml" if client == "codex" else "json"
        snippet = {section: {"chemcad": server}}
        text = (
            tomlkit.dumps(snippet)
            if extension == "toml"
            else json.dumps(snippet, indent=2) + "\n"
        )
        _atomic_write(output_dir / f"{client}.{extension}", text)
    print(f"Generated client snippets: {output_dir}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for path, text in plans:
        if text is None:
            print(f"Already configured: {path}")
            continue
        if path.exists():
            backup = path.with_name(
                path.name + f".before-chemcad-{stamp}-{uuid.uuid4().hex[:8]}"
            )
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")
        _atomic_write(path, text)
        print(f"Configured: {path}")


def check_chemcad_registration():
    """Read both registry views. Never creates a COM object or starts CHEMCAD."""
    import winreg

    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT,
                rf"CLSID\{CLSID}\LocalServer32",
                0,
                winreg.KEY_READ | view,
            ) as key:
                value, _ = winreg.QueryValueEx(key, None)
                if value:
                    return
        except FileNotFoundError:
            pass
    raise RuntimeError(
        "CHEMCAD.VBServer is not registered. Install/repair a licensed CHEMCAD "
        "installation with COM automation, then rerun setup. "
        "Use -SkipChemcadCheck only to prepare configs without the engine."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", choices=CLIENTS, nargs="+", default=list(CLIENTS))
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--skip-chemcad-check", action="store_true")
    parser.add_argument(
        "--config-root", type=Path, help="Isolated client home for testing"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path.cwd() / "work" / "client-configs"
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("CHEMCAD MCP supports native Windows only")
    try:
        if not args.skip_chemcad_check:
            check_chemcad_registration()
            print("CHEMCAD COM registration found (engine was not started).")
        configure(
            args.clients,
            Path(sys.executable).resolve(),
            args.output_dir,
            generate_only=args.generate_only,
            config_root=args.config_root,
        )
    except (OSError, ValueError, RuntimeError, tomlkit.exceptions.ParseError) as error:
        # Do not include parser exceptions: they may echo sensitive config values.
        print(
            f"Setup failed ({type(error).__name__}). Check the selected config files and permissions.",
            file=sys.stderr,
        )
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
