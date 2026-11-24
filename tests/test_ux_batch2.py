"""Synthetic isolated-desktop regression tests for UX Batch 2 (U06-U09)."""

import pytest

from test_workspace import SESSIONS, manager_factory, settle  # noqa: F401
from wow_helper.chat import Message
from wow_helper.markdown_text import extract_commands, parse_markdown, valid_http_url


def test_u06_markdown_parser_links_commands_and_unsafe_scheme_rejection():
    assert valid_http_url("https://example.com/guide?a=1).") == "https://example.com/guide?a=1"
    assert valid_http_url("https://example.com/guide_(classic).") == "https://example.com/guide_(classic)"
    assert valid_http_url("https://example.com/guide.") == "https://example.com/guide"
    assert valid_http_url("javascript:alert(1)") == ""
    assert valid_http_url("file:///etc/passwd") == ""
    assert valid_http_url("https://user:pass@example.com/x") == ""

    sample = (
        "## Graphics fix\n"
        "- Try **FSR off**: `/console ResampleSharpness -1`\n"
        "- Bad link: [bad](javascript:alert(1)) and good link: [Docs](https://example.com/docs)\n"
        "```\n/console farclip 24000\n```"
    )
    blocks = parse_markdown(sample)
    assert blocks[0].kind == "heading" and blocks[0].level == 2
    assert any(b.kind == "code_block" and "/console farclip 24000" in b.text for b in blocks)
    assert extract_commands(sample) == ["/console ResampleSharpness -1", "/console farclip 24000"]


def test_u06_u07_transcript_renders_markdown_links_copy_and_reply_selection(manager_factory, monkeypatch):
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)

    manager = manager_factory()
    view = manager.windows[0].view
    settle(view)
    view._select_session(SESSIONS[0])
    settle(view)
    copied = []
    monkeypatch.setattr(view.root, "clipboard_clear", lambda: None)
    monkeypatch.setattr(view.root, "clipboard_append", copied.append)

    reply_text = (
        "### Quick fix\n"
        "Run `/console ResampleSharpness -1` and check [Guide](https://example.com/wow-guide).\n"
        "Ignored scheme: [bad](javascript:alert(1))"
    )
    view._show([
        Message("u1", "user", "My ground flickers"),
        Message("a1", "assistant", reply_text),
    ])
    manager.root.update()

    # Links: valid https URL is registered, javascript: is rejected.
    urls = list(view.transcript._md_links.values())
    assert urls == ["https://example.com/wow-guide"]
    view._open_transcript_link(urls[0])
    view._open_transcript_link("javascript:alert(1)")
    assert opened == ["https://example.com/wow-guide"]

    # Inline command copy button appears in reply_bar and preserves canonical message text in selected_advice().
    assert view.reply_bar.winfo_manager()
    assert view._cmd_buttons and "/console ResampleSharpness" in str(view._cmd_buttons[0].cget("text"))
    view._cmd_buttons[0].invoke()
    assert copied == ["/console ResampleSharpness -1"]

    # Selecting a reply visually highlights it and direct actions target that exact reply.
    view._select_reply("a1")
    assert view.transcript.tag_ranges("reply_selected")
    selection = view.selected_advice()
    assert selection is not None and selection["text"] == reply_text
    view._reply_action(view.reply_ranges[0][2], "copy")
    assert copied[-1] == reply_text


def test_u08_composer_autogrows_wait_bar_and_find_bar_work(manager_factory):
    manager = manager_factory()
    view = manager.windows[0].view
    settle(view)
    view._select_session(SESSIONS[0])
    settle(view)

    # Composer auto-grows from 2 up to 6 lines and mounts scrollbar past 6 lines.
    assert int(view.editor.cget("height")) == 2
    view.replace_draft("line1\nline2\nline3\nline4")
    manager.root.update()
    assert int(view.editor.cget("height")) == 4
    assert not view._editor_scroll.winfo_manager()
    view.replace_draft("\n".join(f"line {i}" for i in range(10)))
    manager.root.update()
    assert int(view.editor.cget("height")) == 6
    assert view._editor_scroll.winfo_manager()

    # Waiting bar activates during response wait and clears when reply finishes.
    view.send_message("Synthetic wait test")
    settle(view)
    view._update_response_timer()
    assert view.wait_bar.shown
    view.service.history = lambda _: [
        Message("q1", "user", "Synthetic wait test"),
        Message("r1", "assistant", "Found the flight master in ExampleTown."),
    ]
    view._history()
    settle(view)
    view._update_response_timer()
    assert not view.wait_bar.shown

    # Ctrl+F find bar highlights matches without altering message history.
    view.show_find()
    assert view._find_bar.winfo_manager()
    view.find_query.set("ExampleTown")
    manager.root.update()
    assert view.find_count.get() == "1 / 1"
    assert view.transcript.tag_ranges("find_current")
    view.hide_find()
    assert not view._find_bar.winfo_manager()
    assert not view.transcript.tag_ranges("find_match")


def test_u09_command_library_focus_enter_copies_and_research_answer_actions(manager_factory, tmp_path, monkeypatch):
    manager = manager_factory()
    window = manager.windows[0]
    view = window.view
    view.service.state = tmp_path
    view._select_session(SESSIONS[0])
    settle(view)

    manager.show_command_library(window)
    library = manager._command_library_dialog
    manager.root.update()
    assert library.root.focus_lastfor() == library.entry

    copied = []
    monkeypatch.setattr(library.root, "clipboard_clear", lambda: None)
    monkeypatch.setattr(library.root, "clipboard_append", copied.append)

    # Enter copies when local matches exist instead of popping online search.
    library.query.set("flicker")
    manager.root.update()
    library.entry.focus_force()
    manager.root.update()
    library.entry.event_generate("<Return>")
    manager.root.update()
    assert copied == ["/console ResampleSharpness -1"]
    assert library.research_dialog is None

    # Ctrl+Enter opens online search even when local matches exist.
    library.entry.event_generate("<Control-Return>")
    manager.root.update()
    dialog = library.research_dialog
    assert dialog is not None
    dialog.send_button.invoke()
    settle(view)
    assert dialog.busy_bar.shown

    prompt = view.service.sent[0][1]
    answer_text = "Use `/console ResampleSharpness -1` to disable sharpening. https://example.org/fix"
    view.service.history = lambda _: [
        Message("u-res", "user", prompt, turn_id="t-1"),
        Message("a-res", "assistant", answer_text, turn_id="t-1", phase="final_answer"),
    ]
    view._history()
    settle(view)
    assert not dialog.busy_bar.shown
    assert str(dialog.copy_answer_button["state"]) == "normal"
    assert str(dialog.copy_command_button["state"]) == "normal"
    assert str(dialog.save_journal_button["state"]) == "normal"

    res_copied = []
    monkeypatch.setattr(dialog.root, "clipboard_clear", lambda: None)
    monkeypatch.setattr(dialog.root, "clipboard_append", res_copied.append)
    dialog.copy_command_button.invoke()
    dialog.copy_answer_button.invoke()
    assert res_copied == ["/console ResampleSharpness -1", answer_text]

    dialog.save_journal_button.invoke()
    assert view._journal_dialog is not None
    assert view._journal_dialog.selection["text"] == answer_text
    view._journal_dialog.close()
    library.close()
