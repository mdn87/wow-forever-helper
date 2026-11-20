"""Synthetic hands-free voice checks: spoken commands, chat fallback and game commands.

Turns travel through the real file bridge in a temporary folder. No microphone,
listener, network or game input is used; the assistive backend is a fake.
"""

import json

import pytest

from wow_helper.voice_bridge import VoiceBridge, write_request
from wow_helper.voice_commands import Interpreter, best, command_words, spoken_label
from test_workspace import manager_factory, SESSIONS, settle  # noqa: F401


class FakeAssistant:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def request(self, text, *, execute, request_id, issued_at):
        self.calls.append((text, execute, request_id, issued_at))
        if self.error:
            raise self.error
        return {"status": "sent", "message": "Key sent once; spell success is not verified."}


@pytest.fixture
def handsfree(manager_factory, tmp_path):
    from wow_helper.handsfree import HandsFree
    assistant = FakeAssistant()

    def factory(manager):
        controller = HandsFree(manager, bridge_factory=lambda: VoiceBridge(tmp_path / "bridge"),
                               assistant_factory=lambda: assistant)
        controller.assistant = assistant
        return controller

    manager = create_with_factory(manager_factory, factory)
    window = manager.windows[0]
    view = window.view
    view._select_session(SESSIONS[0]); settle(view)
    manager.handsfree.connect(window)
    return manager, window, view, tmp_path / "bridge"


def create_with_factory(manager_factory, factory):
    import test_workspace
    from wow_helper.workspace import WindowManager
    original = WindowManager.__init__

    def patched(self, root, **kwargs):
        kwargs.setdefault("handsfree_factory", factory)
        original(self, root, **kwargs)
    WindowManager.__init__ = patched
    try:
        return manager_factory()
    finally:
        WindowManager.__init__ = original


def say(manager, folder, text):
    request_id = write_request(text, storage=folder)
    assert request_id, "the binding must be live"
    manager.handsfree.poll()
    for view in (w.view for w in manager.windows if w.view):
        settle(view)
    manager.root.update()
    path = folder / "results" / (request_id + ".json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def test_spoken_labels_and_matching():
    assert spoken_label("Voice input…  Keypad -") == "voice input"
    assert spoken_label("Hands-free voice (Lugos Voice)…") == "hands free voice lugos voice"
    assert command_words("Please, open the Journal.") == "open the journal"
    rows = [("Keep above other windows", 1), ("Remember draft and recent chat", 2)]
    assert best("keep above", rows) == (1, [])
    assert best("the remember draft", rows) == (2, [])
    assert best("teleport", rows) == (None, [])


def test_menu_toggle_reports_state_and_is_idempotent(handsfree):
    manager, window, view, folder = handsfree
    assert window.topmost.get() is True  # New windows stay above the game by default.
    assert say(manager, folder, "Turn off keep above other windows.")["status"] == "done"
    assert window.topmost.get() is False
    assert "already off" in say(manager, folder, "turn off keep above")["detail"]
    assert say(manager, folder, "turn on keep above other windows")["status"] == "done"
    assert window.topmost.get() is True and window.root.attributes("-topmost")
    assert not view.service.sent  # Commands are never chat messages.


def test_open_commands_reach_menus_and_companion_windows(handsfree):
    manager, window, view, folder = handsfree
    before = len(manager.windows)
    assert say(manager, folder, "open journal")["status"] == "done"
    assert len(manager.windows) == before + 1 and manager.windows[-1].kind == "journal"
    assert say(manager, folder, "open activity history")["status"] == "done"
    assert manager._activity_dialog is not None
    assert not view.service.sent


def test_dialog_buttons_close_and_read(handsfree):
    manager, window, view, folder = handsfree
    assert say(manager, folder, "open chat appearance")["status"] == "done"
    assert view._appearance_dialog is not None and view._appearance_dialog.root.winfo_ismapped()
    assert say(manager, folder, "read it")["status"] == "done"
    closed = say(manager, folder, "close")
    assert closed["status"] == "done"
    manager.root.update()
    dialog = view._appearance_dialog
    assert dialog is None or not dialog.root.winfo_exists() or not dialog.root.winfo_ismapped()


def test_draft_type_then_send_and_read_the_reply(handsfree):
    manager, window, view, folder = handsfree
    view.editor.insert("1.0", "Keep this")
    assert say(manager, folder, "type and the next quest")["status"] == "done"
    assert view.editor.get("1.0", "end-1c") == "Keep this and the next quest"
    assert say(manager, folder, "send it")["detail"] == "Draft sent."
    settle(view)
    assert view.service.sent == [(SESSIONS[0].key, "Keep this and the next quest")]
    view._history(); settle(view)
    assert say(manager, folder, "read the reply")["detail"] == SESSIONS[0].title


def test_unmatched_speech_is_sent_to_the_selected_chat_and_switch_is_announced(handsfree):
    manager, window, view, folder = handsfree
    assert say(manager, folder, "Where is the flight master?")["status"] == "sent"
    assert view.service.sent == [(SESSIONS[0].key, "Where is the flight master?")]
    assert say(manager, folder, "switch to synthetic review")["detail"] == "Now talking to Synthetic review."
    assert view.selected.key == SESSIONS[1].key
    result = say(manager, folder, "What should I buy?")
    assert result["status"] == "sent" and "Synthetic review" in result["detail"]
    assert view.service.sent[-1] == (SESSIONS[1].key, "What should I buy?")
    # An explicit chat prefix keeps command words as a message.
    say(manager, folder, "tell the agent open journal")
    assert view.service.sent[-1] == (SESSIONS[1].key, "open journal")


def test_game_command_uses_the_turn_id_and_spoken_time(handsfree):
    manager, window, view, folder = handsfree
    result = say(manager, folder, "Cast teleport to Orgrimmar.")
    assert result["status"] == "done" and "not verified" in result["detail"]
    [(text, execute, request_id, issued_at)] = manager.handsfree.assistant.calls
    assert execute is True and request_id == result["id"] and isinstance(issued_at, float)
    assert not view.service.sent


def test_game_refusal_is_spoken_and_nothing_else_happens(handsfree):
    from wow_helper.assist import AssistError
    manager, window, view, folder = handsfree
    manager.handsfree.assistant.error = AssistError("Assistive input is stopped. Enable it before issuing a new command.")
    result = say(manager, folder, "cast teleport to orgrimmar")
    assert result["status"] == "rejected" and "stopped" in result["detail"]
    assert not view.service.sent


def test_ambiguous_and_unavailable_commands_are_refused_plainly(handsfree):
    manager, window, view, folder = handsfree
    assert say(manager, folder, "send")["status"] == "rejected"  # Empty draft.
    assert say(manager, folder, "compare")["detail"].startswith("Open Live gear comparison")
    assert not view.service.sent


def test_no_session_refuses_chat_and_disconnect_phrase_ends_binding(handsfree):
    manager, window, view, folder = handsfree
    view.selected = None
    assert say(manager, folder, "how do I get to the bank")["status"] == "rejected"
    assert say(manager, folder, "stop hands free")["status"] == "done"
    assert not manager.handsfree.connected
    assert not (folder / "binding.json").exists()
    assert write_request("hello", storage=folder) is None


def test_closing_the_window_disconnects_and_auto_connect_is_saved(handsfree, tmp_path):
    manager, window, view, folder = handsfree
    manager.handsfree.set_auto(True)
    assert manager.handsfree.settings() == {"auto": True, "window": window.id}
    manager.new_window()
    manager.close_window(window)
    assert not manager.handsfree.connected and not (folder / "binding.json").exists()


def test_panel_shows_binding_and_recent_turns(handsfree):
    from wow_helper.voice_ui import HandsFreeDialog
    manager, window, view, folder = handsfree
    panel = manager._handsfree_dialog = HandsFreeDialog(manager, window)
    say(manager, folder, "turn on keep above")
    assert "Connected to" in panel.bound.get()
    assert "keep above" in panel.transcript.get("1.0", "end-1c").lower()
    # Voice never treats its own panel as the dialog to operate.
    assert Interpreter(manager, window, exclude=manager.handsfree.exclude).dialog() is None
    panel.close()
    assert manager.handsfree.connected  # Closing the panel keeps the connection.


def test_fight_question_review_flow_is_fully_voice_driven(handsfree, monkeypatch, tmp_path):
    from test_fight_question import fake_reader, wait_read, sent, DIGEST
    calls = fake_reader(monkeypatch, tmp_path)
    manager, window, view, folder = handsfree
    assert say(manager, folder, "ask about the last fight")["status"] == "done"
    dialog = view._notebooks["fight"]
    assert say(manager, folder, "type why did we wipe so fast")["status"] == "done"
    assert dialog.editors["question"].get("1.0", "end-1c") == "why did we wipe so fast"
    assert say(manager, folder, "check include player names")["status"] == "done"
    assert dialog.fields["names"].get() == "1"
    assert say(manager, folder, "send")["status"] == "rejected"  # Nothing reviewed yet.
    assert say(manager, folder, "press read combat log")["status"] == "done"
    wait_read(dialog)
    assert [c[0] for c in calls] == ["find", "digest"]
    assert dialog.editors["digest"].get("1.0", "end-1c") == DIGEST
    assert say(manager, folder, "press prepare review")["status"] == "done"
    manager.root.update()
    assert dialog.packet is not None, dialog.notice.get()
    assert "Example Cleave" in say(manager, folder, "read it")["detail"]
    assert not sent(manager)
    assert say(manager, folder, "send")["detail"] == "Pressed send."
    settle(view)
    assert len(sent(manager)) == 1 and sent(manager)[0][0] == SESSIONS[0].key
    assert say(manager, folder, "send")["status"] == "rejected"  # One explicit send only.
    assert len(sent(manager)) == 1


def test_compare_requires_an_enabled_comparison_and_starts_one_capture(handsfree):
    from wow_helper.gear_ui import GearDialog

    class Engine:
        def __init__(self, *args, **kwargs):
            self.begun = 0
        def begin(self):
            self.begun += 1
        def snapshot(self):
            return None
        def approve(self, *args):
            pass
        def disable(self):
            pass
        def close(self):
            pass

    class Key:
        available = True
        def requested(self):
            return False
        def close(self):
            pass

    manager, window, view, folder = handsfree
    view.service.agents = None
    dialog = view._gear_dialog = GearDialog(view, engine_factory=Engine, key_factory=Key)
    result = say(manager, folder, "compare")
    assert result["status"] == "rejected" and "Enable the comparison shortcut" in result["detail"]
    assert dialog.engine.begun == 0
    dialog.key = Key()  # The player enabled the reviewed comparison.
    assert say(manager, folder, "compare gear")["detail"].startswith("Comparing")
    assert dialog.engine.begun == 1
    assert not view.service.sent
    dialog.close()


def test_dialog_choices_tabs_named_fields_and_new_chat(handsfree, monkeypatch, tmp_path):
    from wow_helper.activities import FLAVORS
    manager, window, view, folder = handsfree
    say(manager, folder, "ask about the last fight")
    dialog = view._notebooks["fight"]
    other = next(name for name in FLAVORS if name != dialog.fields["edition"].get())
    assert say(manager, folder, f"choose {other}")["detail"] == f"Chose {other}."
    assert dialog.fields["edition"].get() == other
    assert say(manager, folder, "set question to what killed the tank")["status"] == "done"
    assert dialog.editors["question"].get("1.0", "end-1c") == "what killed the tank"
    shown = say(manager, folder, "show the digest tab")
    assert shown["status"] == "done", shown
    say(manager, folder, "close")
    started = []
    monkeypatch.setattr(view, "start_session", lambda provider=None, **_: started.append(provider))
    assert say(manager, folder, "new codex chat")["detail"] == "Starting a new Codex chat."
    assert started == ["codex"]
