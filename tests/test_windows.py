import ctypes
import os
import sys

import pytest

from chemcad_mcp.windows import ensure_windows_environment


@pytest.mark.skipif(sys.platform != "win32", reason="Windows environment expansion")
def test_sanitized_environment_resolves_odbc_driver_path(monkeypatch):
    monkeypatch.delenv("WINDIR", raising=False)
    ensure_windows_environment()
    output = ctypes.create_unicode_buffer(32768)
    ctypes.windll.kernel32.ExpandEnvironmentStringsW(
        "%WINDIR%\\system32\\odbcjt32.dll", output, len(output)
    )
    assert "%WINDIR%" not in output.value
    assert os.path.isabs(output.value)
    assert output.value.lower().endswith("\\system32\\odbcjt32.dll")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows directory fallback")
def test_missing_systemroot_uses_windows_directory_api(monkeypatch):
    expected = os.environ["WINDIR"]
    monkeypatch.delenv("WINDIR")
    monkeypatch.delenv("SYSTEMROOT", raising=False)
    ensure_windows_environment()
    assert os.environ["WINDIR"].lower() == expected.lower()
