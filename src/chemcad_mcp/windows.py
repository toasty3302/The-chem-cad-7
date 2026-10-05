"""Restore Windows variables required by CHEMCAD's ODBC driver registration."""

import os
import sys


def ensure_windows_environment():
    if sys.platform != "win32" or os.environ.get("WINDIR"):
        return
    root = os.environ.get("SYSTEMROOT")
    if not root:
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetWindowsDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        kernel.GetWindowsDirectoryW.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetWindowsDirectoryW(buffer, len(buffer))
        if not 0 < length < len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        root = buffer.value
    os.environ["WINDIR"] = root
