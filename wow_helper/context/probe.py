"""Read one context packet from a chosen source and report what happened, safe to paste.

This is a measuring tool, not a feature. It answers: did a packet arrive, through which transport,
how well was the strip read, and was the packet new? The default report names fields, counts and
measurements and never the text that came from the game. ``show`` adds the cleaned content for the
person at the keyboard.

Sources, each read once per run and never watched:

* ``clipboard``: the text the player copied from the probe addon's edit box;
* ``window``: one fresh capture of the selected game window, which is read and then dropped, never
  saved or logged;
* ``image``: a picture file the person names.

Exit codes follow the other commands: 0 when a packet was read and judged (the verdict says whether
it was new), 2 when no packet could be read from what was there, 3 when the source itself could not
be used. Paths, account folders and game text never appear in the output.
"""
import json
import os
import tempfile
import time
from pathlib import Path

from . import clipboard, envelope, strip
from .tracker import Tracker

SOURCES = ("clipboard", "window", "image")
CORNERS = ("topleft", "topright", "bottomleft", "bottomright", "full")
SEARCH_WIDTH, SEARCH_HEIGHT = 1280, 720
MAX_PIXELS = 40_000_000
DEFAULT_STATE = Path(__file__).resolve().parents[2] / ".runtime" / "context-probe.json"


class CaptureFailed(Exception):
    """The game window could not be captured. The message is already safe to print."""


class ImageUnreadable(Exception):
    pass


class PillowMissing(Exception):
    pass


def _now():
    return time.time()


def _ms(started):
    return round((time.perf_counter() - started) * 1000)


def _corner_window(width, height, corner):
    if corner == "full":
        return None
    span_w, span_h = min(width, SEARCH_WIDTH), min(height, SEARCH_HEIGHT)
    left = 0 if corner.endswith("left") else width - span_w
    top = 0 if corner.startswith("top") else height - span_h
    return left, top, left + span_w, top + span_h


def _read_image(path):
    try:
        from PIL import Image
    except ImportError:
        raise PillowMissing from None
    try:
        with Image.open(path) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ImageUnreadable
            return strip.frame_from_image(image)
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ImageUnreadable from None


def _grab_window(flavor):
    """One capture of the selected game window as a frame. The picture lives in a temporary folder only."""
    from ..chat import ChatError
    from ..screen_capture import capture_game
    with tempfile.TemporaryDirectory(prefix="wfh-probe-") as folder:
        try:
            name = capture_game(folder, flavor)
        except ChatError as error:
            raise CaptureFailed(str(error)) from None
        return _read_image(Path(folder) / "captures" / name)


def _load_state(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("tracker", {}) if isinstance(data, dict) else {}


def _save_state(path, tracker):
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        partial.write_text(json.dumps({"v": 1, "tracker": tracker.state()}), encoding="utf-8")
        os.replace(partial, target)
    except OSError:
        return False
    return True


def _refused(result, code, detail, field=""):
    result.update(status="refused", reason=code, detail=detail)
    if field:
        result["field"] = field
    return 2, result


def _failed(result, code, detail):
    result.update(status="error", reason=code, detail=detail)
    return 3, result


def run(source, *, flavor=None, image_path=None, corner="topleft", max_age=120, show=False,
        state_file=None, now=None, reader=None, grab=None):
    """Read one packet and return ``(exit_code, report)``. ``reader`` and ``grab`` stand in for the real sources in tests."""
    result = {"status": "ok", "source": source}
    if source not in SOURCES:
        return _refused(result, "unknown-source", "Choose clipboard, window or image.")
    if corner not in CORNERS:
        return _refused(result, "unknown-corner", "Choose topleft, topright, bottomleft, bottomright or full.")
    timings = {}
    try:
        if source == "clipboard":
            started = time.perf_counter()
            text = (reader or clipboard.read_clipboard_text)()
            timings["read"] = _ms(started)
            started = time.perf_counter()
            packet = clipboard.parse_clipboard(text)
            timings["parse"] = _ms(started)
        else:
            started = time.perf_counter()
            if source == "window":
                from ..activities import FLAVORS
                if not flavor:
                    return _refused(result, "flavor-required", "Name the game folder to capture, for example _retail_.")
                if flavor not in FLAVORS.values():
                    return _refused(result, "flavor-unknown", "Use one of: " + ", ".join(sorted(FLAVORS.values())) + ".")
                frame = (grab or _grab_window)(flavor)
            else:
                if not image_path:
                    return _refused(result, "image-required", "Name the image file to read.")
                frame = _read_image(image_path)
            timings["read"] = _ms(started)
            started = time.perf_counter()
            try:
                found = strip.decode_strip(frame, search=_corner_window(frame.width, frame.height, corner))
            except strip.StripError as error:
                result["strip"] = error.diagnostics
                return _refused(result, error.code, strip.describe(error.code))
            result["strip"] = found.diagnostics
            timings["decode"] = _ms(started)
            started = time.perf_counter()
            packet = envelope.parse_envelope(found.payload)
            timings["parse"] = _ms(started)
    except clipboard.ClipboardUnavailable as error:
        return _failed(result, f"clipboard-{error.reason}", "The clipboard could not be read.")
    except envelope.ContextError as error:
        return _refused(result, error.code, envelope.describe(error.code), error.path)
    except CaptureFailed as error:
        return _failed(result, "capture-failed", str(error))
    except ImageUnreadable:
        return _failed(result, "image-unreadable", "The image could not be opened.")
    except PillowMissing:
        return _failed(result, "pillow-missing", "Reading pictures needs the chat extra: pip install \".[chat]\".")

    tracker = Tracker.from_state(_load_state(state_file), max_age=max_age) if state_file else Tracker(max_age=max_age)
    judged = tracker.judge(packet, _now() if now is None else now)
    state = "off"
    if state_file:
        state = "kept"
        if judged.fresh:
            state = "saved" if _save_state(state_file, tracker) else "not-saved"
    result.update(verdict=judged.verdict, age_seconds=judged.age, new_session=judged.new_session,
                  skipped=judged.skipped, state=state, packet=packet.shape(), timings_ms=timings)
    if show:
        result["content"] = packet.to_dict()
    return 0, result


def as_text(result):
    """Readable lines for the same report. Safe to paste: codes, counts and measurements only."""
    if result["status"] != "ok":
        head = f"Context probe ({result['source']}): {result['status']} {result.get('reason', '')}: {result.get('detail', '')}"
        found = result.get("strip")
        return head + (f"\n  strip: {_strip_line(found)}" if found else "")
    lines = [f"Context probe ({result['source']}): {result['verdict']}. Packet age {result['age_seconds']} s"
             + (", new session." if result["new_session"] else f", {result['skipped']} skipped." if result["skipped"] else ".")]
    lines.append("  fields: " + ", ".join(result["packet"]["present"] or ["none"])
                 + (f"; unreadable: {', '.join(result['packet']['missing'])}" if result["packet"]["missing"] else "")
                 + (f"; cleaned: {', '.join(result['packet']['cleaned'])}" if result["packet"]["cleaned"] else ""))
    if "strip" in result:
        lines.append(f"  strip: {_strip_line(result['strip'])}")
    lines.append("  timings: " + ", ".join(f"{name} {ms} ms" for name, ms in result["timings_ms"].items()))
    if "content" in result:
        lines.append("  content: " + json.dumps(result["content"]))
    return "\n".join(lines)


def _strip_line(found):
    parts = []
    if "columns" in found:
        parts.append(f"{found['columns']} columns")
    if "pitch_x" in found:
        parts.append(f"cell {found['pitch_x']} x {found.get('pitch_y', '?')} px")
    if "contrast" in found:
        parts.append(f"contrast {found['contrast']}")
    if "weakest_margin" in found:
        parts.append(f"weakest margin {found['weakest_margin']}")
    parts.append(f"{found.get('candidates', 0)} candidate(s)")
    return ", ".join(parts)
