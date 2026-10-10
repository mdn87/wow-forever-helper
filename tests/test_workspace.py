"""Synthetic UI checks; no real agent connection or game input is used."""

import json
import threading
import time
import uuid

import pytest

from wow_helper.chat import Message, Session
from wow_helper.workspace import ChatWorkspace, MIN_HEIGHT, MIN_WIDTH


SESSIONS = [Session("codex", str(uuid.UUID(int=0)), "Synthetic planning", "ExampleProject", "idle"),
            Session("claude", str(uuid.UUID(int=1)), "Synthetic review", "ExampleProject", "idle")]


class Service:
    def __init__(self):
        self.sessions = list(SESSIONS)
        self.sent = []
        self.closed = False
        self.gate = None

    def discover(self):
        return self.sessions, []

    def history(self, session):
        return [Message("synthetic-reply", "assistant", session.title)]

    def send(self, session, body, request_id):
        if self.gate is not None and not self.gate.wait(3):
            raise RuntimeError("Synthetic send timed out")
        self.sent.append((session.key, body))
        return "queued"

    def close(self):
        self.closed = True


@pytest.fixture
def workspace_factory(tmp_path, desktop):
    tk, parent = desktop
    views = []

    def create(path=tmp_path / "layout.json"):
        root = tk.Toplevel(parent)
        root.withdraw()
        view = ChatWorkspace(root, service_factory=Service, layout_path=path)
        views.append(view)
        root.deiconify()
        root.update()
        for panel in view.panels:
            settle(panel.view)
        return view

    yield create
    for view in views:
        view.close()
        for panel in view.panels:
            panel.view.worker.shutdown(wait=True)


def settle(view):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        view.root.update()
        if not view.busy:
            return
        time.sleep(0.01)
    pytest.fail("Synthetic chat did not finish")


def choose(panel, index):
    panel.view.session_picker.current(index)
    panel.view.session_picker.event_generate("<<ComboboxSelected>>")
    settle(panel.view)


def drag(widget, dx, dy):
    widget.event_generate("<ButtonPress-1>", x=5, y=5, rootx=100, rooty=100)
    widget.event_generate("<B1-Motion>", x=5 + dx, y=5 + dy, rootx=100 + dx, rooty=100 + dy)
    widget.event_generate("<ButtonRelease-1>", x=5 + dx, y=5 + dy, rootx=100 + dx, rooty=100 + dy)
    widget.update()


def test_two_panels_route_independently_while_one_send_is_waiting(workspace_factory):
    workspace = workspace_factory()
    first, second = workspace.panels
    choose(first, 0)
    choose(second, 1)
    gate = threading.Event()
    first.view.service.gate = gate
    try:
        first.view.editor.insert("1.0", "Plan the next step")
        second.view.editor.insert("1.0", "Review the plan")
        first.view.send()
        second.view.send()
        settle(second.view)
        assert first.view.busy
        assert second.view.service.sent == [(SESSIONS[1].key, "Review the plan")]
        assert "Review the plan" not in first.view.transcript.get("1.0", "end")
    finally:
        gate.set()
        settle(first.view)
    assert first.view.service.sent == [(SESSIONS[0].key, "Plan the next step")]
    assert "Plan the next step" not in second.view.transcript.get("1.0", "end")
    assert first.view.service is not second.view.service


def test_switching_and_closing_one_panel_leaves_the_other_usable(workspace_factory):
    workspace = workspace_factory()
    first, second = workspace.panels
    choose(first, 0)
    choose(second, 1)
    first.view.editor.insert("1.0", "First panel draft")
    second.view.editor.insert("1.0", "Second panel draft")
    choose(first, 1)
    assert first.view.editor.get("1.0", "end-1c") == ""
    choose(first, 0)
    assert first.view.editor.get("1.0", "end-1c") == "First panel draft"
    assert second.view.editor.get("1.0", "end-1c") == "Second panel draft"
    callback = first.view._after_id
    workspace.close_panel(first)
    assert first.view.closed
    assert callback not in workspace.root.tk.call("after", "info")
    assert not second.view.closed
    assert not second.view.service.closed
    second.view.send()
    settle(second.view)
    assert second.view.service.sent == [(SESSIONS[1].key, "Second panel draft")]


def test_drag_resize_and_restart_preserve_layout_and_selected_sessions(workspace_factory):
    workspace = workspace_factory()
    first, second = workspace.panels
    choose(first, 0)
    choose(second, 1)
    original = dict(first.bounds)
    drag(first.label, 80, 60)
    assert first.bounds["x"] == original["x"] + 80
    assert first.bounds["y"] == original["y"] + 60
    drag(first.grip, 50, 40)
    assert first.bounds["width"] == original["width"] + 50
    assert first.bounds["height"] == original["height"] + 40
    first.view.editor.insert("1.0", "Synthetic private draft")
    expected = [dict(panel.bounds) for panel in workspace.panels]
    path = workspace.layout_path
    workspace.close()
    saved = path.read_text(encoding="utf-8")
    assert "Synthetic private draft" not in saved
    assert "Synthetic planning" not in saved
    restored = workspace_factory(path)
    assert [panel.bounds for panel in restored.panels] == expected
    assert [panel.view.selected.key for panel in restored.panels] == [s.key for s in SESSIONS]
    assert all(panel.view.service.sent == [] for panel in restored.panels)


def test_resize_limits_keep_controls_inside_panel_and_tiles_do_not_overlap(workspace_factory):
    workspace = workspace_factory()
    first = workspace.panels[0]
    choose(first, 0)
    drag(first.grip, -2000, -2000)
    assert first.bounds["width"] == MIN_WIDTH
    assert first.bounds["height"] == MIN_HEIGHT
    view = first.view
    bottom = first.frame.winfo_rooty() + first.frame.winfo_height()
    right = first.frame.winfo_rootx() + first.frame.winfo_width()
    assert view.transcript.winfo_height() > 20
    assert view.editor.winfo_height() > 20
    assert view.send_button.winfo_rooty() + view.send_button.winfo_height() <= bottom
    assert view.send_button.winfo_rootx() + view.send_button.winfo_width() <= right
    workspace.add_chat()
    workspace.add_chat()
    workspace.root.geometry("900x640")
    workspace.root.update()
    workspace.tile()
    workspace.root.update()
    for index, panel in enumerate(workspace.panels):
        a = panel.bounds
        assert a["width"] >= MIN_WIDTH and a["height"] >= MIN_HEIGHT
        for other in workspace.panels[index + 1:]:
            b = other.bounds
            assert (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                    or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])
    last = workspace.panels[-1]
    workspace.activate(last, reveal=True)
    workspace.root.update()
    assert 0 <= last.bounds["y"] - workspace.canvas.canvasy(0) < workspace.canvas.winfo_height()


def test_missing_saved_session_never_falls_back_and_can_reconnect(workspace_factory, tmp_path):
    path = tmp_path / "missing.json"
    missing = Session("codex", str(uuid.UUID(int=5)), "Synthetic returning session", "ExampleProject", "idle")
    path.write_text(json.dumps({"version": 1, "panels": [{"session": {"provider": "codex", "id": missing.id}}]}), encoding="utf-8")
    workspace = workspace_factory(path)
    view = workspace.panels[0].view
    assert view.selected is None
    assert str(view.send_button["state"]) == "disabled"
    view.editor.insert("1.0", "Do not send elsewhere")
    view.send()
    assert view.service.sent == []
    workspace.save_layout()
    assert json.loads(path.read_text())["panels"][0]["session"]["id"] == missing.id
    view.service.sessions.append(missing)
    view.refresh()
    settle(view)
    assert view.selected.key == missing.key
    assert view.service.sent == []


def test_activating_a_covered_panel_raises_its_widgets(workspace_factory):
    workspace = workspace_factory()
    first, second = workspace.panels
    first.place(second.bounds)
    workspace.activate(first)
    workspace.root.update()
    assert workspace.canvas.winfo_children()[-1] is first.frame
    workspace.activate(second)
    workspace.root.update()
    assert workspace.canvas.winfo_children()[-1] is second.frame


def test_malformed_layout_recovers_and_empty_layout_stays_empty(workspace_factory, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    workspace = workspace_factory(path)
    assert len(workspace.panels) == 2
    for panel in list(workspace.panels):
        workspace.close_panel(panel)
    workspace.close()
    restored = workspace_factory(path)
    assert restored.panels == []
    assert restored.add_chat() is not None
    restored.close()
    path.write_text(json.dumps({"version": 1, "panels": [{"width": "bad", "height": -1,
                    "x": -100, "session": {"provider": [], "id": "bad"}}]}), encoding="utf-8")
    repaired = workspace_factory(path)
    panel = repaired.panels[0]
    assert panel.bounds["width"] >= MIN_WIDTH
    assert panel.bounds["height"] >= MIN_HEIGHT
    assert panel.bounds["x"] == 0
    assert panel.view.selected is None


def test_layout_write_failure_keeps_panels_usable_without_private_error(workspace_factory, monkeypatch):
    workspace = workspace_factory()
    def fail(*_):
        raise OSError("Synthetic private filesystem detail")
    monkeypatch.setattr("wow_helper.workspace.write_json", fail)
    workspace.save_layout()
    assert "Could not save" in workspace.status.get()
    assert "private" not in workspace.status.get()
    choose(workspace.panels[0], 0)
    assert workspace.panels[0].view.selected.key == SESSIONS[0].key
