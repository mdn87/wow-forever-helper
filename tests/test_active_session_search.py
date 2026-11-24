"""Synthetic active sessions and online command searches on the isolated desktop."""
from dataclasses import replace

import pytest

from test_workspace import CreatingService, SESSIONS, manager_factory, settle  # noqa: F401
from wow_helper.chat import Message
from wow_helper.model_settings import Preferences


def test_advanced_detects_new_sessions_on_open_and_attaches_by_identity(manager_factory):
    manager = manager_factory(service=CreatingService)
    view = manager.windows[0].view
    view.replace_draft('Keep my fresh question')
    old, new = SESSIONS[0], replace(SESSIONS[1], title=SESSIONS[0].title)
    view.service.sessions = [old, new]
    view.model_button.invoke()
    settle(view)
    dialog = view._model_dialog
    assert dialog and dialog.tabs.select() == str(dialog.advanced)
    panel = dialog.session_panel
    assert panel.keys == [old.key, new.key]
    assert len(set(panel.choice['values'])) == 2
    assert view.selected is None
    panel.choice.current(1)
    panel.choice.event_generate('<<ComboboxSelected>>')
    panel.use.invoke()
    settle(view)
    assert view.selection_key == new.key and dialog.external_claude
    assert dialog.tabs.select() == str(dialog.advanced)
    assert view.editor.get('1.0', 'end-1c') == 'Keep my fresh question'
    assert not view.service.created and not view.service.sent


def test_disappearing_active_session_is_never_replaced_by_the_next_row(manager_factory):
    manager = manager_factory(service=CreatingService)
    view = manager.windows[0].view
    view._select_session(SESSIONS[0])
    settle(view)
    view.show_model_settings()
    settle(view)
    dialog = view._model_dialog
    dialog.tabs.select(dialog.advanced)
    settle(view)
    panel = dialog.session_panel
    panel.choice.current(1)
    panel.choice.event_generate('<<ComboboxSelected>>')
    view.service.sessions = [SESSIONS[0]]
    panel.use.invoke()
    settle(view)
    assert view.selection_key == SESSIONS[0].key and panel.keys == [SESSIONS[0].key]
    assert 'closed' in panel.notice.get().lower() and not view.service.sent


@pytest.mark.parametrize('question,key', [
    ('farclip', '<Control-Return>'),
    ('a question missing from the local library', '<Return>'),
])
def test_enter_opens_web_review_and_answer_returns_to_the_search(manager_factory, tmp_path, question, key):
    manager = manager_factory()
    view = manager.windows[0].view
    view.service.state = tmp_path
    view._select_session(SESSIONS[0])
    settle(view)
    view.replace_draft('Unsent chat draft')
    manager.show_command_library(manager.windows[0])
    library = manager._command_library_dialog
    library.query.set(question)
    library.entry.focus_force()
    manager.root.update()
    library.entry.event_generate(key)
    manager.root.update()
    dialog = library.research_dialog
    assert dialog and question in dialog.preview.get('1.0', 'end')
    assert 'Search the web' in dialog.preview.get('1.0', 'end')
    assert not view.service.sent and Preferences(tmp_path).remaining() == 3
    dialog.send_button.invoke()
    settle(view)
    assert len(view.service.sent) == 1 and Preferences(tmp_path).remaining() == 2
    prompt = view.service.sent[0][1]
    messages = [Message('user-new', 'user', prompt, turn_id='synthetic-turn'),
                Message('assistant-new', 'assistant', 'A synthetic answer with a source https://example.org/game-docs',
                        turn_id='synthetic-turn', phase='final_answer')]
    view.service.history = lambda _: messages
    view._history()
    settle(view)
    assert 'https://example.org/game-docs' in dialog.preview.get('1.0', 'end')
    assert view.editor.get('1.0', 'end-1c') == 'Unsent chat draft'
    dialog.view_chat.invoke()
    assert library.research_dialog is None and len(view.service.sent) == 1


def test_open_sessions_filter_includes_other_open_windows_and_omits_saved_history(manager_factory):
    manager = manager_factory(service=CreatingService)
    first = manager.windows[0].view
    other = manager.new_window(kind='chat').view
    settle(other)
    opened = replace(SESSIONS[0], managed=True, status='ready')
    other._select_session(opened)
    settle(other)
    old = replace(SESSIONS[1], managed=True, status='ready')
    running = replace(old, id='00000000-0000-0000-0000-000000000002', status='running')
    assert first.active_sessions([old, opened, running]) == [opened, running]


def test_browser_search_encodes_question_and_uses_no_agent_attempt(manager_factory, tmp_path, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    from wow_helper import command_library_ui
    manager = manager_factory()
    window = manager.windows[0]
    window.view.service.state = tmp_path
    manager.show_command_library(window)
    library = manager._command_library_dialog
    urls = []
    monkeypatch.setattr(command_library_ui.webbrowser, 'open', lambda url: urls.append(url) or True)
    assert library.browser_button.instate(['disabled'])
    query = 'test setting & what about #2?'
    library.query.set(query)
    assert not urls
    library.browser_button.invoke()
    assert len(urls) == 1
    url = urlsplit(urls[0])
    assert url.scheme == 'https' and parse_qs(url.query)['q'] == ['World of Warcraft ' + query]
    assert not window.view.service.sent and Preferences(tmp_path).remaining() == 3


@pytest.mark.parametrize('theme,scaling', [('classic', 1.33), ('modern', 1.67)])
def test_session_selector_and_existing_advanced_settings_fit(manager_factory, theme, scaling):
    manager = manager_factory(service=CreatingService)
    manager.preview_interface({'theme': theme})
    view = manager.windows[0].view
    view.start_session('claude')
    settle(view)
    original = view.root.tk.call('tk', 'scaling')
    view.root.tk.call('tk', 'scaling', scaling)
    try:
        view.show_model_settings()
        settle(view)
        dialog = view._model_dialog
        dialog.tabs.select(dialog.advanced)
        dialog.chrome.place('430x475+40+40')
        settle(view)
        dialog.root.update()
        fields = (dialog.manual_model, dialog.effort_choice, dialog.timeout_choice)
        for control in (dialog.session_panel.use, dialog.session_panel.choice, dialog.save_button, *fields):
            assert control.winfo_ismapped() and control.winfo_height() >= control.winfo_reqheight()
            assert control.winfo_rootx() + control.winfo_width() <= dialog.root.winfo_rootx() + dialog.root.winfo_width()
            assert control.winfo_rooty() + control.winfo_height() <= dialog.root.winfo_rooty() + dialog.root.winfo_height()
    finally:
        view.root.tk.call('tk', 'scaling', original)


def test_close_during_attach_validation_keeps_original_destination(manager_factory):
    import threading
    manager = manager_factory(service=CreatingService)
    view = manager.windows[0].view
    view._select_session(SESSIONS[0])
    settle(view)
    view.show_model_settings()
    settle(view)
    dialog = view._model_dialog
    dialog.tabs.select(dialog.advanced)
    settle(view)
    entered, release = threading.Event(), threading.Event()
    def discover():
        entered.set()
        assert release.wait(3)
        return SESSIONS, []
    view.service.discover = discover
    panel = dialog.session_panel
    panel.choice.current(1)
    panel.choice.event_generate('<<ComboboxSelected>>')
    panel.use.invoke()
    try:
        assert entered.wait(1)
        dialog.close()
    finally:
        release.set()
    settle(view)
    assert view.selected.key == SESSIONS[0].key and not view.service.sent


def test_only_answers_for_this_research_request_are_displayed():
    from wow_helper.command_research_ui import research_answer
    codex, claude = SESSIONS
    request = '00000000-0000-0000-0000-000000000007'
    marker = f'[WoW search {request}]'
    messages = [Message('user', 'user', 'question', turn_id='turn-a'),
                Message('other', 'assistant', 'Other answer', turn_id='turn-b', phase='final_answer'),
                Message('progress', 'assistant', 'Working', turn_id='turn-a', phase='commentary')]
    assert research_answer(codex, request, 'question', messages, None) == ''
    assert research_answer(claude, request, 'question', messages, 'acknowledged') == ''
    messages.append(Message('answer', 'assistant', 'Cited answer\n' + marker))
    assert research_answer(claude, request, 'question', messages, 'acknowledged') == 'Cited answer'
    managed = replace(codex, managed=True)
    messages.append(Message(request + ':assistant', 'assistant', 'Managed answer'))
    assert research_answer(managed, request, 'question', messages, 'running') == ''
    assert research_answer(managed, request, 'question', messages, 'completed') == 'Managed answer'
