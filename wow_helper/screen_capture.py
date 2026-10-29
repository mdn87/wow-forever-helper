"""Explicit single-window captures and locally imported images; no game input."""

import os
import json
from pathlib import Path
import subprocess
import sys
import uuid

from .chat import ChatError

MAX_PIXELS = 40_000_000


def saved_image(storage, name):
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(".png"):
        raise ChatError("Capture or open an image first.")
    folder = (Path(storage) / "captures").resolve()
    path = (folder / name).resolve()
    if path.parent != folder or not path.is_file():
        raise ChatError("The saved image is unavailable. Capture or open it again.")
    return path


def _save(image, path):
    from PIL import Image
    if image.width * image.height > MAX_PIXELS or min(image.size) < 2:
        raise ChatError("Choose an image smaller than 40 megapixels.")
    # Copy pixels into a fresh image so imports do not retain EXIF or text metadata.
    clean = Image.new("RGB", image.size)
    clean.paste(image.convert("RGB"))
    path.parent.mkdir(parents=True, exist_ok=True)
    clean.save(path, format="PNG")


def import_image(storage, source):
    from PIL import Image, ImageOps, UnidentifiedImageError
    path = Path(storage) / "captures" / (str(uuid.uuid4()) + ".png")
    try:
        if Path(source).stat().st_size > 64_000_000:
            raise ChatError("Choose an image smaller than 64 MB.")
        with Image.open(source) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ChatError("Choose an image smaller than 40 megapixels.")
            _save(ImageOps.exif_transpose(image), path)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise ChatError("That image could not be opened. Choose a PNG, JPEG, or WebP image.") from None
    return path.name


def paste_image(storage):
    """An explicit clipboard read avoids opening a file picker over the game."""
    from PIL import Image, ImageGrab
    try:
        value = ImageGrab.grabclipboard()
        if isinstance(value, Image.Image):
            path = Path(storage) / "captures" / (str(uuid.uuid4()) + ".png")
            _save(value, path)
            return path.name
        if isinstance(value, list) and len(value) == 1:
            return import_image(storage, value[0])
    except (OSError, ValueError, NotImplementedError):
        raise ChatError("The clipboard image could not be read. Copy an image or take a screen snip first.") from None
    raise ChatError("No single image is on the clipboard. Copy an image or take a screen snip first.")


def game_window(flavor):
    """Identify one visible game window by executable and edition, not its title."""
    if os.name != "nt":
        raise ChatError("Live capture requires Windows. Open an image instead.")
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows.restype = wintypes.BOOL
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsWindowVisible.restype = wintypes.BOOL
    user.IsIconic.argtypes = [wintypes.HWND]
    user.IsIconic.restype = wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    found = []

    @callback_type
    def visit(window, _):
        if not user.IsWindowVisible(window) or user.IsIconic(window):
            return True
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        process = kernel.OpenProcess(0x1000, False, pid.value)
        if process:
            try:
                size = wintypes.DWORD(32768)
                name = ctypes.create_unicode_buffer(size.value)
                if kernel.QueryFullProcessImageNameW(process, 0, name, ctypes.byref(size)):
                    path = Path(name.value)
                    if (path.name.casefold() in {"wow.exe", "wowb.exe", "wowclassic.exe", "wowclassicb.exe"}
                            and path.parent.name.casefold() == flavor.casefold()):
                        found.append(window)
            finally:
                kernel.CloseHandle(process)
        return True

    if not user.EnumWindows(visit, 0):
        raise ChatError("Game windows could not be listed. Open an image instead.")
    if len(found) != 1:
        raise ChatError("Open one visible WoW window for the selected edition, or open an image instead.")
    return found[0]


def crop_region(image, region, expected_size):
    try:
        if (not isinstance(region, (list, tuple)) or len(region) != 4
                or any(type(v) is not int for v in region)
                or not isinstance(expected_size, (list, tuple)) or len(expected_size) != 2
                or any(type(v) is not int for v in expected_size)
                or tuple(expected_size) != image.size):
            raise ValueError
        x, y, width, height = region
        if min(x, y) < 0 or min(width, height) < 2 or x + width > image.width or y + height > image.height:
            raise ValueError
        return image.crop((x, y, x + width, y + height))
    except (TypeError, ValueError):
        raise ChatError("The game size or region changed. Review a fresh preview before comparing.") from None


def capture_game(storage, flavor, *, region=None, expected_size=None):
    if os.name != "nt":
        raise ChatError("Live capture requires Windows. Open an image instead.")
    path = Path(storage) / "captures" / (str(uuid.uuid4()) + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, "-m", "wow_helper.screen_capture", str(path), flavor]
    if region is not None:
        args.append(json.dumps({'region': region, 'size': expected_size}))
    try:
        # Isolate native capture so an unresponsive game cannot hang a worker.
        result = subprocess.run(args,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        raise ChatError("Capture did not finish. Keep WoW visible or open an image instead.") from None
    if result.returncode == 3:
        raise ChatError("The game size or region changed. Review a fresh preview before comparing.")
    if result.returncode != 0 or not path.is_file():
        raise ChatError("Capture failed. Open one visible WoW window for the selected edition, or open an image.")
    return path.name


def main():
    from .graphics_capture import grab_window
    from .activities import FLAVORS
    if len(sys.argv) not in (3, 4) or sys.argv[2] not in FLAVORS.values():
        return 2
    try:
        window = game_window(sys.argv[2])
        image = grab_window(window)
        if len(sys.argv) == 4:
            if len(sys.argv[3]) > 1000:
                return 2
            options = json.loads(sys.argv[3])
            try:
                image = crop_region(image, options['region'], options['size'])
            except ChatError:
                return 3
        _save(image, Path(sys.argv[1]))
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
