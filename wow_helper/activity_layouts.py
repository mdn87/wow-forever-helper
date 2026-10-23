"""Private named window arrangements, without copied drafts or executable requests."""

from copy import deepcopy
import json
from pathlib import Path
import uuid

from .activities import TYPES, profile_settings
from .appearance import appearance_settings
from .chat import ChatError, write_json
from .journal import bounded_text
from .pinned_advice import validate_pin
from .window_state import LayoutLock, MAX_WINDOWS, saved_selection

MAX_BYTES = 8_000_000
MAX_LAYOUTS = 20


def valid_id(value):
    return str(uuid.UUID(value))


def bounds(value):
    if (not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}
            or any(type(v) is not int for v in value.values())
            or any(abs(value[k]) > 32_000 for k in ("x", "y"))
            or not 1 <= value["width"] <= 4000 or not 1 <= value["height"] <= 3000):
        raise ValueError
    return dict(value)


def layout_record(window):
    """Read presentation settings only; snapshot() can persist live quest state."""
    record = {"id": window.id, "kind": window.kind, "bounds": window.capture_bounds(),
              "topmost": window.topmost.get(), "remember": window.remember.get()}
    if window.card:
        record.update(pin=window.pin, mode=window.mode, mode_bounds=window.mode_bounds)
    elif window.view:
        view = window.view
        activity = {}
        if view.book:
            activity["tab"] = min(view.book.index("current"), 1) if not view.active_quest_chat() else 0
        if window.kind == "journal":
            activity["journal_id"] = view.journal_id
        if window.kind == "screen" and view.image_name:
            activity["image"] = view.image_name
        if window.kind == "character":
            activity.update(gear_goal=view.gear_goal.get(), gear_slot=view.gear_slot.get())
        chat = {"appearance": view.appearance, "provider": view.default_provider,
                "profile": view.profile, "activity": activity}
        key = view.selection_key
        if key:
            chat.update(session={"provider": key[0], "id": key[1]}, title=view.session_title[:100])
        record["chat"] = chat
    return normalize_record(record)


def normalize_record(raw):
    try:
        if not isinstance(raw, dict) or raw.get("kind") not in (*TYPES, "chooser", "play"):
            raise ValueError
        kind = raw["kind"]
        record = {"id": valid_id(raw["id"]), "kind": kind, "bounds": bounds(raw["bounds"])}
        if type(raw.get("topmost")) is not bool:
            raise ValueError
        record["topmost"] = raw["topmost"]
        if type(raw.get("remember", True)) is not bool:
            raise ValueError
        record["remember"] = raw.get("remember", True)
        if kind == "play":
            if raw.get("mode") not in {"play", "desk"}:
                raise ValueError
            modes = raw.get("mode_bounds", {})
            if not isinstance(modes, dict) or set(modes) - {"play", "desk"}:
                raise ValueError
            record.update(pin=validate_pin(raw.get("pin")), mode=raw["mode"],
                          mode_bounds={k: bounds(v) for k, v in modes.items()})
        elif kind in TYPES:
            chat = raw.get("chat", {})
            if not isinstance(chat, dict):
                raise ValueError
            # Deliberately exclude launch, pending, response waits, drafts, histories,
            # and quest-tab files. Restoring an arrangement cannot replay work.
            state = {"appearance": appearance_settings(chat.get("appearance")),
                     "profile": profile_settings(kind, chat.get("profile")), "activity": {}}
            state["provider"] = chat.get("provider") if chat.get("provider") in {"claude", "codex"} else "codex"
            if "session" in chat:
                selection = saved_selection(chat["session"])
                if selection is None:
                    raise ValueError
                state["session"] = {"provider": selection[0], "id": selection[1]}
                title = chat.get("title", "Saved conversation")
                bounded_text(title, 100, empty=True)
                state["title"] = title
            activity = chat.get("activity", {})
            if not isinstance(activity, dict):
                raise ValueError
            tab = activity.get("tab", 0)
            if type(tab) is not int or tab not in (0, 1):
                raise ValueError
            state["activity"]["tab"] = tab
            if kind == "journal" and activity.get("journal_id"):
                state["activity"]["journal_id"] = valid_id(activity["journal_id"])
            if kind == "screen" and activity.get("image"):
                name = activity["image"]
                if not isinstance(name, str) or name != valid_id(name[:-4]) + ".png":
                    raise ValueError
                state["activity"]["image"] = name
            if kind == "character":
                for key in ("gear_goal", "gear_slot"):
                    if key in activity:
                        bounded_text(activity[key], 200, empty=True)
                        state["activity"][key] = activity[key]
            record["chat"] = state
        return deepcopy(record)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise ChatError("This saved arrangement contains invalid window settings. Existing windows and saved layouts are kept.") from None


class SavedLayouts:
    def __init__(self, path):
        self.path = Path(path) if path is not None else None
        self.memory = {"version": 1, "layouts": []}

    def load(self):
        if self.path is None:
            return deepcopy(self.memory)
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return {"version": 1, "layouts": []}
        except OSError:
            raise ChatError("Saved activity layouts could not be read. The existing file is kept.") from None
        try:
            if len(raw) > MAX_BYTES:
                raise ValueError
            data = json.loads(raw)
            if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1
                    or not isinstance(data.get("layouts"), list) or len(data["layouts"]) > MAX_LAYOUTS):
                raise ValueError
            names = set()
            for layout in data["layouts"]:
                bounded_text(layout["name"], 80)
                name = layout["name"].casefold()
                if name in names:
                    raise ValueError
                names.add(name)
                windows = layout["windows"]
                if not isinstance(windows, list) or not 1 <= len(windows) <= MAX_WINDOWS:
                    raise ValueError
                layout["windows"] = [normalize_record(w) for w in windows]
                if len({w["id"] for w in layout["windows"]}) != len(windows):
                    raise ValueError
            return data
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, ChatError):
            raise ChatError("Saved activity layouts are damaged or unsupported. The existing file is kept.") from None

    def get(self, name):
        result = next((s for s in self.load()["layouts"] if s["name"].casefold() == name.casefold()), None)
        if result is None:
            raise ChatError("That activity layout is no longer available. Refresh the list.")
        return result

    def save(self, name, records, *, replace=False):
        try:
            bounded_text(name, 80)
            name = name.strip()
            if not 1 <= len(records) <= MAX_WINDOWS:
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            raise ChatError("Use a name between 1 and 80 characters for one to eight windows.") from None
        windows = [normalize_record(r) for r in records]
        lock = None
        try:
            try:
                lock = LayoutLock(self.path)
            except ChatError:
                raise ChatError("Another window is saving activity layouts. Your current arrangement is unchanged; try again shortly.") from None
            data = self.load()
            existing = next((s for s in data["layouts"] if s["name"].casefold() == name.casefold()), None)
            if existing and not replace:
                raise ChatError("That name is already saved. Choose Replace selected to update it.")
            if not existing and len(data["layouts"]) >= MAX_LAYOUTS:
                raise ChatError("Twenty activity layouts are saved. Replace a selected layout instead.")
            item = {"name": name, "windows": windows}
            if existing:
                data["layouts"][data["layouts"].index(existing)] = item
            else:
                data["layouts"].append(item)
            if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_BYTES:
                raise ChatError("Saved activity layouts are full. Save a smaller arrangement; existing layouts are kept.")
            if self.path is None:
                self.memory = deepcopy(data)
            else:
                write_json(self.path, data)
            return item
        except OSError:
            raise ChatError("The activity layout could not be saved. Your current arrangement and previous save are kept.") from None
        finally:
            if lock:
                lock.close()
