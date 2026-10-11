"""Synthetic Tk interaction tests; skipped when a graphical desktop is unavailable."""

import time
import threading
import uuid

import pytest

from wow_helper.chat import Message, Session


@pytest.fixture
def window(desktop):
    tk, parent = desktop
    root = tk.Toplevel(parent)
    root.withdraw()
    from wow_helper.chat_window import ChatWindow
    class Service:
        sessions = [Session("codex", str(uuid.UUID(int=0)), "Synthetic Codex", "ExampleProject", "idle"),
                    Session("claude", str(uuid.UUID(int=1)), "Synthetic Claude", "ExampleProject", "idle")]
        def discover(self): return self.sessions, []
        def history(self, session): return [Message("synthetic-reply", "assistant", session.title)]
        def send(self, *_): return "queued"
        def close(self): pass
    view = ChatWindow(root, Service())
    settle(view)
    yield view
    view.close()
    view.worker.shutdown(wait=True)


def settle(window):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        window.root.update()
        if not window.busy:
            return
        time.sleep(0.01)
    pytest.fail("Synthetic UI work did not finish")


def choose(window, index):
    window.session_picker.current(index)
    window.session_picker.event_generate("<<ComboboxSelected>>")
    window.root.update()
    settle(window)


def test_drafts_and_replies_stay_with_the_selected_session(window):
    choose(window, 0)
    window.editor.insert("1.0", "First draft")
    choose(window, 1)
    assert window.editor.get("1.0", "end-1c") == ""
    assert "Synthetic Claude" in window.transcript.get("1.0", "end")
    window.editor.insert("1.0", "Second draft")
    choose(window, 0)
    assert window.editor.get("1.0", "end-1c") == "First draft"
    assert "Synthetic Claude" not in window.transcript.get("1.0", "end")


def test_send_does_not_erase_text_typed_during_delivery(window):
    choose(window, 0)
    window.editor.insert("1.0", "First message")
    window.send()
    window.editor.insert("end", " and a new thought")
    settle(window)
    assert window.editor.get("1.0", "end-1c") == "First message and a new thought"


def test_history_poll_keeps_controls_available_and_accepts_one_send(window):
    choose(window, 0)
    gate, started = threading.Event(), threading.Event()
    calls = []

    def history(_):
        started.set()
        assert gate.wait(3)
        return [Message("synthetic-existing", "user", "Hello")]

    window.service.history = history
    window.service.send = lambda session, body, request: calls.append((session.key, body)) or "queued"
    try:
        window.auto_refresh = 29
        window._tick()
        assert started.wait(1)
        assert str(window.send_button["state"]) == "normal"
        assert str(window.refresh_button["state"]) == "normal"
        window.editor.insert("1.0", "Hello")
        window.send()
        window.send()  # A second click must not queue the same draft again.
        window.editor.insert("end", " and keep typing")
        window.root.update()
        assert window.editor.get("1.0", "end-1c") == "Hello and keep typing"
        assert str(window.send_button["state"]) == "disabled"
        assert calls == []  # The provider connection remains single-worker.
    finally:
        gate.set()
        settle(window)
    assert calls == [(window.selected.key, "Hello")]
    assert window.editor.get("1.0", "end-1c") == "Hello and keep typing"
    assert "QUEUED" in window.transcript.get("1.0", "end")
    window._show([Message("synthetic-existing", "user", "Hello"),
                  Message("synthetic-delivered", "user", "Hello")])
    assert "QUEUED" not in window.transcript.get("1.0", "end")


def test_unchanged_poll_does_not_schedule_another_layout_save(window):
    choose(window, 0)
    changes = []
    window.on_change = lambda: changes.append(True)
    window._history()
    settle(window)
    assert changes == []


def long_history():
    return [Message(f"synthetic-{i}", "assistant", f"Reply {i}: " + "Wrapped conversation text. " * 25)
            for i in range(30)]


def assert_latest_visible(window):
    window.root.update()
    text = window.transcript
    assert text.bbox("end-2c") is not None
    # Tk updates yview's line-height estimates asynchronously. Check the
    # actual final line against the viewport edge instead of those estimates.
    last_line = text.bbox("end-1c")
    padding = sum(int(text.cget(option)) for option in ("pady", "borderwidth", "highlightthickness"))
    assert last_line is not None
    assert last_line[1] + last_line[3] == text.winfo_height() - padding


@pytest.mark.parametrize("update", ["reply", "growing_reply", "queued_message"])
def test_new_text_scrolls_to_bottom_after_reading_older_messages(window, update):
    window.root.deiconify()
    choose(window, 0)
    messages = long_history()
    window._show(messages)
    window.root.update()
    window.transcript.yview_moveto(0.2)
    window.root.update()
    assert window.transcript.yview()[1] < 0.9
    if update == "reply":
        messages = messages + [Message("synthetic-latest", "assistant", "Newest reply at the bottom")]
    elif update == "growing_reply":
        last = messages[-1]
        messages = messages[:-1] + [Message(last.id, last.role, last.text + " More reply text. " * 100)]
    else:
        window.sent[window.selection_key] = [("Newest outgoing message", "queued", frozenset())]
    window._show(messages)
    assert_latest_visible(window)


def test_unchanged_history_keeps_manual_scroll_position(window):
    window.root.deiconify()
    choose(window, 0)
    messages = long_history()
    window._show(messages)
    window.root.update()
    window.transcript.yview_moveto(0.2)
    window.root.update()
    before = window.transcript.index("@0,0")
    position = window.transcript.bbox(before)
    window._show(messages)
    window.root.update()
    assert window.transcript.index("@0,0") == before
    assert window.transcript.bbox(before) == position


def test_switching_sessions_opens_each_conversation_at_bottom(window):
    window.root.deiconify()
    window.service.history = lambda _: long_history()
    choose(window, 0)
    assert_latest_visible(window)
    window.transcript.yview_moveto(0.0)
    choose(window, 1)
    assert_latest_visible(window)
    window.transcript.yview_moveto(0.0)
    choose(window, 0)
    assert_latest_visible(window)


def test_resize_and_reopen_keep_the_latest_text_visible(window):
    window.root.deiconify()
    choose(window, 0)
    window._show(long_history())
    window.root.update()
    window.transcript.yview_moveto(1.0)
    for geometry in ("440x580", "1000x760", "520x620"):
        window.root.geometry(geometry)
        assert_latest_visible(window)
    window.root.withdraw()
    window.transcript.yview_moveto(0.0)
    window.root.update()
    window.root.deiconify()
    assert_latest_visible(window)


def test_refresh_clicked_during_history_still_detects_a_disconnected_session(window):
    choose(window, 0)
    gate = threading.Event()
    def history(_):
        assert gate.wait(3)
        return []
    window.service.history = history
    try:
        window._history()
        window.service.sessions = []
        window.editor.insert("1.0", "Keep this draft")
        window.refresh_button.invoke()
    finally:
        gate.set()
        settle(window)
    assert window.selected is None
    assert str(window.send_button["state"]) == "disabled"
    assert window.editor.get("1.0", "end-1c") == "Keep this draft"


def test_identical_old_text_cannot_hide_a_new_queued_message(window):
    choose(window, 0)
    old = Message("synthetic-old", "user", "Hello")
    window._show([old])
    window.editor.insert("1.0", "Hello")
    window.send()
    settle(window)
    assert "QUEUED" in window.transcript.get("1.0", "end")
    window._show([old, Message("synthetic-new", "user", "Hello")])
    assert "QUEUED" not in window.transcript.get("1.0", "end")
    window._show([Message("synthetic-later", "assistant", "A later reply")])
    assert "Hello" not in window.transcript.get("1.0", "end")


def test_stale_reply_cannot_appear_in_a_different_session(window):
    choose(window, 1)
    window.results.put(("history", window.sessions[0].key,
                        [Message("synthetic-stale", "assistant", "Wrong session text")], None))
    window._tick()
    assert "Wrong session text" not in window.transcript.get("1.0", "end")


def test_disconnected_session_disables_send_and_preserves_draft(window):
    choose(window, 0)
    key = window.selected.key
    window.editor.insert("1.0", "Unsent draft")
    window.service.sessions = []
    window.refresh()
    settle(window)
    assert window.selected is None
    assert str(window.send_button["state"]) == "disabled"
    assert window.drafts[key] == "Unsent draft"


def test_close_cancels_the_refresh_callback(window):
    callback = window._after_id
    window._show(long_history())
    scroll_callback = window._scroll_after_id
    assert callback in window.root.tk.call("after", "info")
    assert scroll_callback in window.root.tk.call("after", "info")
    window.close()
    assert callback not in window.root.tk.call("after", "info")
    assert scroll_callback not in window.root.tk.call("after", "info")


@pytest.mark.parametrize("geometry", ["700x460", "500x400"])
def test_claude_connection_dialog_keeps_copy_button_visible(window, geometry):
    choose(window, 1)
    window.claude_setup()
    window.root.update()
    dialog = next(child for child in window.root.winfo_children() if isinstance(child, window.tk.Toplevel))
    dialog.geometry(geometry)
    dialog.update()
    button = next(child for child in dialog._companion_frame.content.winfo_children() if child.winfo_class() == "TButton")
    assert button.winfo_rooty() + button.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()


@pytest.mark.parametrize("geometry", ["1080x760", "760x540"])
def test_composer_and_send_button_fit_inside_window(window, geometry):
    window.root.geometry(geometry)
    window.root.deiconify()
    window.root.update()
    bottom = window.root.winfo_rooty() + window.root.winfo_height()
    assert window.editor.winfo_height() > 20
    assert window.send_button.winfo_rooty() + window.send_button.winfo_height() <= bottom
    assert window.refresh_button.winfo_rooty() + window.refresh_button.winfo_height() <= bottom
