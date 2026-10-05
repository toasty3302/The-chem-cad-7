"""Print CHEMCAD window titles without interacting with the application."""

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
pid_filter = int(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 0
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def child_callback(hwnd, _):
    title = ctypes.create_unicode_buffer(2048)
    name = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, len(title))
    user32.GetClassNameW(hwnd, name, len(name))
    if title.value:
        print("  child", hwnd, repr(name.value), repr(title.value), flush=True)
    return True


child_handler = callback_type(child_callback)


def callback(hwnd, _):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid_filter or pid.value == pid_filter:
        title = ctypes.create_unicode_buffer(1024)
        name = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, len(title))
        user32.GetClassNameW(hwnd, name, len(name))
        if pid_filter or title.value:
            print(
                pid.value,
                hwnd,
                bool(user32.IsWindowVisible(hwnd)),
                repr(name.value),
                repr(title.value),
                flush=True,
            )
            if name.value == "#32770":
                user32.EnumChildWindows(hwnd, child_handler, 0)
    return True


user32.EnumWindows(callback_type(callback), 0)
