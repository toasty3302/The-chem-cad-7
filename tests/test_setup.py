import shutil
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

from chemcad_mcp import configure as setup

PROJECT = Path(__file__).resolve().parents[1]


def test_registration_checks_both_views_without_activating_com(monkeypatch):
    import winreg

    views = []

    def open_key(root, key, reserved, access):
        assert root == winreg.HKEY_CLASSES_ROOT
        assert key == rf"CLSID\{setup.CLSID}\LocalServer32"
        views.append(access)
        if access & winreg.KEY_WOW64_32KEY:
            raise FileNotFoundError
        return nullcontext(object())

    monkeypatch.setattr(winreg, "OpenKey", open_key)
    monkeypatch.setattr(
        winreg, "QueryValueEx", lambda *_: ('"C:/CHEMCAD/CCNXT.exe"', winreg.REG_SZ)
    )
    setup.check_chemcad_registration()
    assert views == [
        winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
        winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
    ]


def test_missing_registration_fails_before_touching_configs(
    monkeypatch, tmp_path, capsys
):
    import winreg

    def missing_key(*_):
        raise FileNotFoundError

    monkeypatch.setattr(winreg, "OpenKey", missing_key)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "configure",
            "--config-root",
            str(tmp_path / "user"),
            "--output-dir",
            str(tmp_path / "snippets"),
        ],
    )
    assert setup.main() == 1
    assert "not registered" in capsys.readouterr().err
    assert not (tmp_path / "user").exists()
    assert not (tmp_path / "snippets").exists()


def test_non_windows_setup_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        sys, "argv", ["configure", "--generate-only", "--output-dir", str(tmp_path)]
    )
    with pytest.raises(SystemExit) as error:
        setup.main()
    assert error.value.code == 2
    assert not list(tmp_path.iterdir())


def test_configuration_errors_do_not_print_private_values(
    monkeypatch, tmp_path, capsys
):
    user = tmp_path / "user"
    path = user / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text("token = PRIVATE_SECRET_DO_NOT_PRINT", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "configure",
            "--clients",
            "codex",
            "--skip-chemcad-check",
            "--config-root",
            str(user),
        ],
    )
    assert setup.main() == 1
    captured = capsys.readouterr()
    assert "PRIVATE_SECRET_DO_NOT_PRINT" not in captured.out + captured.err


def test_powershell_generate_only_leaves_isolated_home_untouched(tmp_path):
    powershell = shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Windows PowerShell is not installed")
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT / "setup.ps1"),
            "-SkipInstall",
            "-SkipChemcadCheck",
            "-GenerateOnly",
            "-ConfigRoot",
            str(tmp_path / "client home"),
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no client configs were changed" in result.stdout
    assert not (tmp_path / "client home").exists()
