"""One fresh Windows Graphics Capture frame from an identified game window.

The caller runs this native boundary in the existing ten-second capture worker.
It never targets a monitor or falls back to desktop/PrintWindow capture.
"""

from .chat import ChatError

MAX_PIXELS = 40_000_000


def qpc_timestamp():
    """Return QPC in WinRT TimeSpan's 100 ns units, matching frame timestamps."""
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.QueryPerformanceCounter.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
    kernel.QueryPerformanceFrequency.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
    counter, frequency = ctypes.c_longlong(), ctypes.c_longlong()
    if not kernel.QueryPerformanceCounter(ctypes.byref(counter)) or not kernel.QueryPerformanceFrequency(ctypes.byref(frequency)):
        raise OSError
    return counter.value * 10_000_000 // frequency.value


def grab_window(window, *, factory=None, timestamp=qpc_timestamp):
    """Ignore cached pre-request frames and copy one fresh frame before closing."""
    from PIL import Image
    result = []
    try:
        if type(window) is not int or window <= 0:
            raise ValueError
        if factory is None:
            from windows_capture import WindowsCapture
            factory = WindowsCapture
        started = timestamp()
        capture = factory(window_hwnd=window, monitor_index=None, cursor_capture=False)

        @capture.event
        def on_frame_arrived(frame, control):
            if frame.timespan < started:
                return
            try:
                width, height = frame.width, frame.height
                if (min(width, height) < 2 or width * height > MAX_PIXELS):
                    raise ValueError
                # Copy while the native frame is checked out. Never retain a
                # borrowed GPU buffer or use image text as an instruction.
                data = frame.frame_buffer.tobytes()
                if len(data) != width * height * 4:
                    raise ValueError
                result.append(Image.frombytes("RGB", (width, height), data, "raw", "BGRX"))
            except Exception:
                pass  # Reject malformed frames; do not retry the capture.
            finally:
                control.stop()

        @capture.event
        def on_closed():
            pass

        capture.start()
        if not result:
            raise ValueError
        return result[0]
    except Exception:
        raise ChatError("A fresh game frame was unavailable. Keep WoW visible and request another capture.") from None
