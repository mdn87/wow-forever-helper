"""Opt-in, one-shot capture evidence for F07; no comparison or automatic send.

Run with pythonw on Windows. Ctrl+Alt+F9 captures once, only with the selected
game in front. The temporary shortcut expires after five minutes. Private
results live under .runtime/live-gear-proof; no desktop image fallback exists.
"""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import time
import uuid

from .activities import FLAVORS
from .chat import write_json
from .screen_capture import capture_game, game_window
from .window_access import WindowsAPI


def foreground_window():
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.argtypes = []
    user.GetForegroundWindow.restype = wintypes.HWND
    return user.GetForegroundWindow()


def probe(storage, flavor, *, api, publish, identify=game_window,
          foreground=foreground_window, capture=capture_game,
          clock=time.monotonic, sleep=time.sleep, timeout=300):
    """Bound one explicit request; return evidence, never retry or alter focus."""
    request_id = str(uuid.uuid4())

    def report(state, **fields):
        record = {"request_id": request_id, "state": state, "flavor": flavor,
                  "recorded_at": datetime.now(timezone.utc).isoformat(), **fields}
        publish(record)
        return record

    registered = False
    try:
        if flavor not in FLAVORS.values() or not 0 < timeout <= 300:
            return report("invalid-settings")
        try:
            window = identify(flavor)
        except Exception:
            return report("unavailable")
        registered = api.register(0x78)  # F9 with CONTROL | ALT | NOREPEAT
        if not registered:
            return report("shortcut-unavailable")
        deadline = clock() + timeout
        report("ready", shortcut="Ctrl+Alt+F9", expires_in_seconds=timeout)
        while clock() < deadline:
            if api.poll_hotkey():
                if identify(flavor) != window:
                    return report("game-changed")
                if foreground() != window:
                    return report("wrong-foreground")
                requested_at = datetime.now(timezone.utc).isoformat()
                report("capturing", requested_at=requested_at)
                start = clock()
                name = capture(storage, flavor)
                seconds = clock() - start
                same_focus = foreground() == window
                return report("captured", requested_at=requested_at, image=name,
                              capture_seconds=round(seconds, 3), focus_unchanged=same_focus,
                              extraction_verified=False)
            sleep(0.025)
        return report("expired")
    except Exception:
        # Exceptions may contain machine paths or image content. Never emit them.
        return report("capture-failed")
    finally:
        if registered:
            api.unregister()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flavor", choices=FLAVORS.values(), default="_classic_beta_")
    args = parser.parse_args(argv)
    if os.name != "nt":
        return 2
    root = Path(__file__).resolve().parents[1] / ".runtime" / "live-gear-proof"
    folder = root / str(uuid.uuid4())
    folder.mkdir(parents=True)

    def publish(record):
        write_json(folder / "result.json", record)
        write_json(root / "latest.json", {"run": folder.name, **record})

    result = probe(folder, args.flavor, api=WindowsAPI(), publish=publish)
    return 0 if result["state"] == "captured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
