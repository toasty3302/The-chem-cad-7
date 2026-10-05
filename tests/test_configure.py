import copy
import json
from pathlib import Path

import pytest
import tomlkit

from chemcad_mcp.configure import (
    CLIENTS,
    _clean_jsonc,
    client_paths,
    configure,
    merged_config,
    read_config,
    server_config,
)


@pytest.mark.parametrize("client", CLIENTS)
def test_generated_snippets_use_actual_python_path(client, tmp_path):
    python = Path("C:/Users/Someone's Name/My Repo/.venv/Scripts/python.exe")
    configure(
        [client],
        python,
        tmp_path / "output",
        generate_only=True,
        config_root=tmp_path / "user",
    )
    suffix = "toml" if client == "codex" else "json"
    document, _ = read_config(tmp_path / "output" / f"{client}.{suffix}")
    section, expected = server_config(client, python)
    assert document == {section: {"chemcad": expected}}
    assert not (tmp_path / "user").exists()


@pytest.mark.parametrize("client", CLIENTS)
def test_registration_preserves_settings_backs_up_and_is_idempotent(client, tmp_path):
    targets = client_paths(tmp_path / "user")
    path = targets[client][0]
    path.parent.mkdir(parents=True)
    section, server = server_config(
        client, tmp_path / "Repo with spaces" / "python.exe"
    )
    original = {
        "model": "user-model",
        "private_setting": {"token": "do-not-print-this"},
        section: {"other": {"command": "untouched"}, "chemcad": {"command": "old"}},
    }
    text = tomlkit.dumps(original) if client == "codex" else json.dumps(original)
    path.write_text(text, encoding="utf-8")
    configure(
        [client],
        tmp_path / "Repo with spaces" / "python.exe",
        tmp_path / "output",
        config_root=tmp_path / "user",
    )
    expected = copy.deepcopy(original)
    expected[section]["chemcad"] = server
    assert read_config(path)[0] == expected
    backups = list(path.parent.glob(path.name + ".before-chemcad-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == text
    after = path.read_bytes()
    configure(
        [client],
        tmp_path / "Repo with spaces" / "python.exe",
        tmp_path / "output",
        config_root=tmp_path / "user",
    )
    assert path.read_bytes() == after
    assert list(path.parent.glob(path.name + ".before-chemcad-*")) == backups


@pytest.mark.parametrize("trailing", ["", ","])
@pytest.mark.parametrize(
    "section",
    ["", '"mcp": {},', '"mcp": {"other": {"type": "local", "command": ["keep"]}},'],
)
def test_jsonc_insertion_preserves_comments_strings_and_trailing_commas(
    tmp_path, trailing, section
):
    path = tmp_path / "opencode.jsonc"
    original = (
        "{\n// keep header\n"
        f"{section}\n"
        '"permission": {"bash": "ask"}, /* keep middle */\n'
        '"literal": "// not a comment /* still a string */ , } and \\"quotes\\""'
        f"{trailing}\n// keep footer\n}}\n"
    )
    path.write_text(original, encoding="utf-8")
    _, server = server_config("opencode", Path("C:/Repo/python.exe"))
    updated = merged_config(path, "mcp", server)
    parsed = json.loads(_clean_jsonc(updated))
    assert parsed["mcp"]["chemcad"] == server
    assert parsed["literal"] == json.loads(_clean_jsonc(original))["literal"]
    for comment in ("// keep header", "/* keep middle */", "// keep footer"):
        assert comment in updated


def test_jsonc_replacement_preserves_unrelated_comments(tmp_path):
    path = tmp_path / "opencode.jsonc"
    path.write_text(
        """{
      "mcp": {
        // keep other server
        "other": {"command": ["other"],},
        "chemcad": {"command": ["old"]}, // keep trailing comment
      },
      "model": "untouched", // keep preferences
    }""",
        encoding="utf-8",
    )
    _, server = server_config("opencode", Path("C:/Repo/python.exe"))
    updated = merged_config(path, "mcp", server)
    assert "// keep other server" in updated
    assert "// keep trailing comment" in updated
    assert "// keep preferences" in updated
    assert json.loads(_clean_jsonc(updated))["mcp"]["other"] == {"command": ["other"]}


@pytest.mark.parametrize(
    "original",
    [
        '# keep model comment\nmodel = "mine"\n',
        '[mcp_servers.other] # keep other server\ncommand = "other"\n',
        'mcp_servers = {other = {command = "other"}, chemcad = {command = "old"}}\n',
        '[mcp_servers."chemcad"]\ncommand = "old"\n\n[permissions]\nmode = "keep"\n',
    ],
)
def test_toml_quoted_inline_and_regular_tables(tmp_path, original):
    path = tmp_path / "config.toml"
    path.write_text(original, encoding="utf-8")
    _, server = server_config("codex", Path("C:/Someone's Name/python.exe"))
    result = merged_config(path, "mcp_servers", server)
    parsed = tomlkit.parse(result)
    assert parsed["mcp_servers"]["chemcad"] == server
    for line in original.splitlines():
        if line.startswith("# keep") or "# keep other server" in line:
            assert line in result


def test_malformed_config_aborts_before_any_client_changes(tmp_path):
    root = tmp_path / "user"
    root.mkdir()
    first = root / ".claude.json"
    first.write_text('{"model": "keep"}', encoding="utf-8")
    broken = root / ".codex" / "config.toml"
    broken.parent.mkdir()
    broken.write_text("this is not valid TOML", encoding="utf-8")
    with pytest.raises(tomlkit.exceptions.ParseError):
        configure(
            ["claude-code", "codex"],
            Path("python.exe"),
            tmp_path / "output",
            config_root=root,
        )
    assert first.read_text(encoding="utf-8") == '{"model": "keep"}'
    assert not list(root.rglob("*.before-chemcad-*"))
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("value", [None, 42, [], "bad"])
def test_invalid_section_fails_safely(tmp_path, value):
    path = tmp_path / "config.json"
    original = json.dumps({"mcpServers": value})
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="Expected an object"):
        merged_config(path, "mcpServers", {"command": "new"})
    assert path.read_text(encoding="utf-8") == original


def test_custom_locations_and_isolation(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "custom-codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "custom-claude"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "custom-appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "custom-xdg"))
    monkeypatch.setenv("OPENCODE_CONFIG", str(tmp_path / "extra.jsonc"))
    paths = client_paths()
    assert paths["codex"] == [tmp_path / "custom-codex" / "config.toml"]
    assert paths["claude-code"] == [tmp_path / "custom-claude" / ".claude.json"]
    assert paths["claude-desktop"] == [
        tmp_path / "custom-appdata" / "Claude" / "claude_desktop_config.json"
    ]
    assert paths["opencode"] == [
        tmp_path / "custom-xdg" / "opencode" / "opencode.json",
        tmp_path / "extra.jsonc",
    ]
    isolated = client_paths(tmp_path / "isolated")
    assert isolated["codex"] == [tmp_path / "isolated" / ".codex" / "config.toml"]
    assert all(
        path.is_relative_to(tmp_path / "isolated")
        for paths in isolated.values()
        for path in paths
    )


def test_existing_json_and_jsonc_both_updated(tmp_path):
    root = tmp_path / "user"
    opencode = root / ".config" / "opencode"
    opencode.mkdir(parents=True)
    (opencode / "opencode.json").write_text('{"model": "keep-json"}', encoding="utf-8")
    (opencode / "opencode.jsonc").write_text(
        '{/* keep */ "model": "keep-jsonc",}', encoding="utf-8"
    )
    configure(["opencode"], Path("python.exe"), tmp_path / "output", config_root=root)
    for path in client_paths(root)["opencode"]:
        document, text = read_config(path)
        assert document["mcp"]["chemcad"]["command"] == [
            "python.exe",
            "-m",
            "chemcad_mcp.server",
        ]
        assert document["model"] == f"keep-{path.suffix[1:]}"
        if path.suffix == ".jsonc":
            assert "/* keep */" in text
