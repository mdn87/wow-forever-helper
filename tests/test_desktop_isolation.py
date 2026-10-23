"""Native regression checks for synthetic UI tests staying off the input desktop."""

import os

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows desktop isolation")
def test_ui_desktop_is_private(desktop, request):
    if request.config.getoption("--visible-ui"):
        pytest.skip("Visible UI testing was explicitly requested")
    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentThreadId.restype = wintypes.DWORD
    user.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user.GetThreadDesktop.restype = wintypes.HANDLE
    user.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD)]
    user.GetUserObjectInformationW.restype = wintypes.BOOL
    name = ctypes.create_unicode_buffer(256)
    needed = wintypes.DWORD()
    handle = user.GetThreadDesktop(kernel.GetCurrentThreadId())
    assert user.GetUserObjectInformationW(handle, 2, name, ctypes.sizeof(name), ctypes.byref(needed))
    assert name.value.startswith("WoWHelperTests-"), "UI tests are using the interactive desktop"

    # Exercise an actual mapped, topmost window, then prove it is absent from
    # the desktop receiving the user's input. Do not depend on visual observation.
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumDesktopWindows.argtypes = [wintypes.HANDLE, callback_type, wintypes.LPARAM]
    user.EnumDesktopWindows.restype = wintypes.BOOL
    user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user.OpenInputDesktop.restype = wintypes.HANDLE
    user.CloseDesktop.argtypes = [wintypes.HANDLE]
    user.CloseDesktop.restype = wintypes.BOOL

    def windows_on(desktop_handle):
        windows = []
        callback = callback_type(lambda window, _: windows.append(window) or True)
        assert user.EnumDesktopWindows(desktop_handle, callback, 0)
        return windows

    tk, root = desktop
    window = tk.Toplevel(root)
    input_desktop = None
    try:
        window.attributes("-topmost", True)
        window.update()
        native_window = int(window.frame(), 0)
        assert window.winfo_ismapped()
        assert native_window in windows_on(handle)
        input_desktop = user.OpenInputDesktop(0, False, 0x0041)
        assert input_desktop
        assert native_window not in windows_on(input_desktop)
    finally:
        window.destroy()
        if input_desktop:
            user.CloseDesktop(input_desktop)


@pytest.mark.parametrize("create_ok,attach_ok", [(False, True), (True, False), (True, True)])
def test_isolation_failure_never_falls_back_to_visible_ui(create_ok, attach_ok):
    from ui_desktop import isolate_windows_desktop

    class API:
        def __init__(self):
            self.closed = []
            self.attached = []

        def create(self, name):
            assert name.startswith("WoWHelperTests-")
            return 123 if create_ok else None

        def attach(self, handle):
            self.attached.append(handle)
            return attach_ok

        def close(self, handle):
            self.closed.append(handle)

    api = API()
    if create_ok and attach_ok:
        assert isolate_windows_desktop(api) == 123
    else:
        with pytest.raises(RuntimeError, match="no UI tests were opened"):
            isolate_windows_desktop(api)
    assert api.attached == ([123] if create_ok else [])
    assert api.closed == ([123] if create_ok and not attach_ok else [])
