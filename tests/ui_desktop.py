"""Put test-owned Windows UI on a desktop that is never made visible."""

import os
import uuid


class WindowsDesktopAPI:
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                             ctypes.c_void_p, wintypes.DWORD,
                                             wintypes.DWORD, ctypes.c_void_p]
        self.user.CreateDesktopW.restype = wintypes.HANDLE
        self.user.SetThreadDesktop.argtypes = [wintypes.HANDLE]
        self.user.SetThreadDesktop.restype = wintypes.BOOL
        self.user.CloseDesktop.argtypes = [wintypes.HANDLE]
        self.user.CloseDesktop.restype = wintypes.BOOL

    def create(self, name):
        # READOBJECTS | CREATEWINDOW | CREATEMENU | ENUMERATE | WRITEOBJECTS.
        # No desktop-switch permission; tests never switch the user's desktop.
        return self.user.CreateDesktopW(name, None, None, 0, 0x00C7, None)

    def attach(self, handle):
        return self.user.SetThreadDesktop(handle)

    def close(self, handle):
        return self.user.CloseDesktop(handle)


def isolate_windows_desktop(api=None):
    """Fail closed before creating Tk windows if desktop isolation is unavailable.

    Keep the desktop handle until process exit: Tk retains native thread windows
    even after root.destroy(), so detaching/closing at fixture teardown is unsafe.
    Windows releases the desktop when this test process exits.
    """
    api = api if api is not None else WindowsDesktopAPI()
    handle = api.create(f"WoWHelperTests-{os.getpid()}-{uuid.uuid4().hex}")
    if not handle:
        raise RuntimeError("Could not create an isolated UI test desktop; no UI tests were opened.")
    if not api.attach(handle):
        api.close(handle)
        raise RuntimeError("Could not attach the isolated UI test desktop; no UI tests were opened.")
    return handle
