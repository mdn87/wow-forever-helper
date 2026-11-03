"""Synthetic hands-free bridge checks. No microphone, listener, or game input."""

import json

from wow_helper.voice_bridge import VoiceBridge, write_request


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now
    def __call__(self):
        return self.now


def result(storage, request_id):
    return json.loads((storage / "results" / (request_id + ".json")).read_text(encoding="utf-8"))


def test_unbound_bridge_accepts_nothing(tmp_path):
    assert write_request("hello", storage=tmp_path) is None  # No binding file: the sender stays out.
    assert VoiceBridge(tmp_path).pending() == []


def test_fresh_request_for_current_binding_is_claimed_once(tmp_path):
    clock = Clock()
    bridge = VoiceBridge(tmp_path, clock=clock)
    bridge.connect("Synthetic planning", "codex")
    request_id = write_request("  What should I do next?  ", storage=tmp_path, clock=clock)
    assert bridge.pending() == [{"id": request_id, "text": "What should I do next?"}]
    assert not list((tmp_path / "inbox").iterdir())
    # The same id dropped again is never delivered twice.
    write_request("again", storage=tmp_path, clock=clock, request_id=request_id)
    assert bridge.pending() == []


def test_stale_foreign_and_malformed_requests_are_answered_as_rejected(tmp_path):
    clock = Clock()
    bridge = VoiceBridge(tmp_path, clock=clock)
    bridge.connect("Synthetic planning", "codex")
    stale = write_request("old turn", storage=tmp_path, clock=clock, spoken_at=clock.now - 61)
    future = write_request("future turn", storage=tmp_path, clock=clock, spoken_at=clock.now + 30)
    empty = write_request("   ", storage=tmp_path, clock=clock)
    oversized = write_request("x" * 6001, storage=tmp_path, clock=clock)
    foreign = "00000000-0000-0000-0000-00000000000f"
    (tmp_path / "inbox" / (foreign + ".json")).write_text(json.dumps(
        {"id": foreign, "binding_id": "someone-else", "text": "hi", "spoken_at": clock.now}), encoding="utf-8")
    assert bridge.pending() == []
    for request_id in (stale, future, empty, oversized, foreign):
        assert result(tmp_path, request_id)["status"] == "rejected"
    assert "No WoW Helper chat is bound" in result(tmp_path, foreign)["detail"]


def test_reconnect_invalidates_turns_for_the_previous_binding(tmp_path):
    clock = Clock()
    bridge = VoiceBridge(tmp_path, clock=clock)
    bridge.connect("Synthetic planning", "codex")
    request_id = write_request("for the old chat", storage=tmp_path, clock=clock)
    bridge.disconnect()
    assert not (tmp_path / "binding.json").exists()
    bridge.connect("Synthetic review", "claude")
    assert bridge.pending() == []
    assert result(tmp_path, request_id)["status"] == "rejected"


def test_disconnect_leaves_a_newer_binding_alone(tmp_path):
    first, second = VoiceBridge(tmp_path), VoiceBridge(tmp_path)
    first.connect("Synthetic planning", "codex")
    second.connect("Synthetic review", "claude")
    first.disconnect()
    assert json.loads((tmp_path / "binding.json").read_text())["label"] == "Synthetic review"


def test_sender_ignores_a_binding_whose_heartbeat_stopped(tmp_path):
    clock = Clock()
    bridge = VoiceBridge(tmp_path, clock=clock)
    bridge.connect("Synthetic planning", "codex")
    clock.now += 16
    assert write_request("hello", storage=tmp_path, clock=clock) is None
    bridge.heartbeat()
    assert write_request("hello", storage=tmp_path, clock=clock)


from test_workspace import manager_factory, SESSIONS, settle  # noqa: E402,F401


def open_panel(manager, tmp_path, clock):
    from wow_helper.voice_ui import HandsFreeDialog
    window = manager.windows[0]
    panel = manager._handsfree_dialog = HandsFreeDialog(
        manager, window, bridge_factory=lambda: VoiceBridge(tmp_path / "bridge", clock=clock))
    return window, window.view, panel


def deliver(view, panel):
    panel.poll()
    settle(view)


def test_panel_sends_a_spoken_turn_to_the_bound_chat_without_touching_the_draft(manager_factory, tmp_path):
    clock = Clock()
    manager = manager_factory()
    window, view, panel = open_panel(manager, tmp_path, clock)
    panel.connect()
    assert not panel.bridge.connected  # Needs a chosen session first.
    view._select_session(SESSIONS[0]); settle(view)
    view.editor.insert("1.0", "Unsent draft")
    panel.connect()
    assert "Synthetic planning" in panel.bound.get()
    request_id = write_request("Where is the flight master?", storage=tmp_path / "bridge", clock=clock)
    deliver(view, panel)
    assert view.service.sent == [(SESSIONS[0].key, "Where is the flight master?")]
    assert view.editor.get("1.0", "end-1c") == "Unsent draft"
    assert result(tmp_path / "bridge", request_id)["status"] == "sent"
    panel.close()
    assert not (tmp_path / "bridge" / "binding.json").exists()
    assert manager._handsfree_dialog is None


def test_switching_chats_disconnects_before_any_turn_is_sent(manager_factory, tmp_path):
    clock = Clock()
    manager = manager_factory()
    window, view, panel = open_panel(manager, tmp_path, clock)
    view._select_session(SESSIONS[0]); settle(view)
    panel.connect()
    request_id = write_request("For the first chat", storage=tmp_path / "bridge", clock=clock)
    view._select_session(SESSIONS[1]); settle(view)
    deliver(view, panel)
    assert not panel.bridge.connected
    assert view.service.sent == []
    assert "chat changed" in panel.notice.get()
    # The orphaned request stays unanswered; the sender reports no answer rather than a send.
    assert not (tmp_path / "bridge" / "results" / (request_id + ".json")).exists()


def test_busy_chat_refuses_the_turn_instead_of_queueing_it(manager_factory, tmp_path):
    import threading
    clock = Clock()
    manager = manager_factory()
    window, view, panel = open_panel(manager, tmp_path, clock)
    view._select_session(SESSIONS[0]); settle(view)
    panel.connect()
    view.service.gate = threading.Event()
    first = write_request("first", storage=tmp_path / "bridge", clock=clock)
    panel.poll()
    second = write_request("second", storage=tmp_path / "bridge", clock=clock)
    panel.poll()
    assert result(tmp_path / "bridge", second)["status"] == "rejected"
    view.service.gate.set(); settle(view)
    assert result(tmp_path / "bridge", first)["status"] == "sent"
    assert view.service.sent == [(SESSIONS[0].key, "first")]


def test_closing_the_window_closes_the_panel_and_binding(manager_factory, tmp_path):
    clock = Clock()
    manager = manager_factory()
    window, view, panel = open_panel(manager, tmp_path, clock)
    view._select_session(SESSIONS[0]); settle(view)
    panel.connect()
    manager.new_window()
    manager.close_window(window)
    assert manager._handsfree_dialog is None
    assert not (tmp_path / "bridge" / "binding.json").exists()
