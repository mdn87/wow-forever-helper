"""Exercise the library on the shared isolated Tk desktop."""

import pytest

from test_workspace import manager_factory  # noqa: F401
from wow_helper import search


@pytest.mark.parametrize("theme", ["classic", "modern"])
def test_library_search_copy_and_empty_state(manager_factory, monkeypatch, theme):
    manager = manager_factory()
    manager.preview_interface({"theme": theme})
    window = manager.windows[0]
    manager.show_command_library(window)
    dialog = manager._command_library_dialog
    copied = []
    monkeypatch.setattr(dialog.root, "clipboard_clear", lambda: None)
    monkeypatch.setattr(dialog.root, "clipboard_append", copied.append)
    assert not copied
    dialog.query.set("moving brighter")
    manager.root.update()
    assert len(dialog.results.get_children()) == 1
    assert "ResampleSharpness -1" in dialog.preview.get("1.0", "end-1c")
    dialog.copy_command.invoke()
    assert copied == ["/console ResampleSharpness -1"]
    dialog.query.set("farclip")
    dialog.copy_inspect.invoke()
    dialog.copy_restore.invoke()
    assert copied[-2:] == ['/dump GetCVar("farclip")',
                          '/run SetCVar("farclip", GetCVarDefault("farclip"))']
    dialog.query.set("junk confirmation")
    assert str(dialog.copy_restore["state"]) == "disabled"
    assert "Addon required" in dialog.preview.get("1.0", "end-1c")
    dialog.query.set("no synthetic match")
    assert str(dialog.copy_command["state"]) == "disabled"
    assert "No matching commands" in dialog.preview.get("1.0", "end-1c")
    dialog.category.set("Draw distance")
    dialog.query.set("")
    assert all(c.category == "Draw distance" for c in dialog.matches)
    dialog.root.geometry("520x620")
    manager.root.update()
    for button in (dialog.copy_command, dialog.copy_inspect, dialog.copy_restore):
        assert button.winfo_rootx() >= dialog.root.winfo_rootx()
        assert button.winfo_rootx() + button.winfo_width() <= dialog.root.winfo_rootx() + dialog.root.winfo_width()
    manager.show_command_library(window)
    assert manager._command_library_dialog is dialog
    assert not window.view.service.sent
    dialog.close()
    assert manager._command_library_dialog is None


def test_library_is_reachable_from_tools_and_search_and_closes_with_owner(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    window.tools_menu.invoke("Command library…")
    assert manager._command_library_dialog is not None
    manager._command_library_dialog.close()
    rows, _ = search.search_index(manager)
    row = next(r for r in rows if r["target"] == "command_library")
    manager.show_search(window)
    manager._search_dialog.open_result(row)
    dialog = manager._command_library_dialog
    assert dialog is not None
    manager.close()
    assert manager._command_library_dialog is None


def test_clipboard_failure_is_reported_without_claiming_success(manager_factory, monkeypatch):
    manager = manager_factory()
    manager.show_command_library(manager.windows[0])
    dialog = manager._command_library_dialog
    def unavailable():
        raise manager.tk.TclError("synthetic clipboard unavailable")
    monkeypatch.setattr(dialog.root, "clipboard_clear", unavailable)
    dialog.copy_command.invoke()
    assert "Could not copy" in dialog.notice.get()
