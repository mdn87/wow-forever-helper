"""Synthetic Tk interaction tests; skipped when a graphical desktop is unavailable."""

import time
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
    assert callback in window.root.tk.call("after", "info")
    window.close()
    assert callback not in window.root.tk.call("after", "info")


def test_claude_connection_dialog_keeps_copy_button_visible(window):
    choose(window, 1)
    window.claude_setup()
    window.root.update()
    dialog = next(child for child in window.root.winfo_children() if isinstance(child, window.tk.Toplevel))
    button = next(child for child in dialog.winfo_children() if child.winfo_class() == "TButton")
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
