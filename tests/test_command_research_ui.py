"""Synthetic attached sessions on the isolated desktop; no paid agent calls."""
from test_workspace import manager_factory, settle  # noqa: F401
from wow_helper.chat import ChatService
from wow_helper.model_settings import Preferences


def setup(manager_factory, tmp_path):
    manager = manager_factory()
    window = manager.windows[0]
    view = window.view
    view.service.state = tmp_path
    view.service.research = ChatService.research.__get__(view.service)
    original_send = view.service.send
    view.service.send = lambda *args, **kwargs: original_send(*args)
    view._select_session(view.sessions[0])
    settle(view)
    manager.show_command_library(window)
    library = manager._command_library_dialog
    library.query.set('ground brightness')
    library.research_button.invoke()
    return manager, view, library.research_dialog


def test_review_then_send_once_preserves_draft_and_decrements_allowance(manager_factory, tmp_path):
    manager, view, dialog = setup(manager_factory, tmp_path)
    view.editor.insert('1.0', 'Keep this draft')
    assert not view.service.sent
    dialog.send()
    assert not view.service.sent
    dialog.prepare()
    assert 'ground brightness' in dialog.preview.get('1.0', 'end')
    dialog.send(); dialog.send()
    settle(view)
    assert len(view.service.sent) == 1
    assert view.editor.get('1.0', 'end-1c') == 'Keep this draft'
    assert Preferences(tmp_path).remaining() == 2
    dialog.prepare()
    dialog.query.set('changed query')
    dialog.send()
    assert len(view.service.sent) == 1
    manager._command_library_dialog.close()
    assert dialog.closed


def test_changed_model_or_session_invalidates_review(manager_factory, tmp_path):
    manager, view, dialog = setup(manager_factory, tmp_path)
    dialog.prepare()
    Preferences(tmp_path).save(view.selected, model='example-small', effort='low', timeout=90)
    dialog.send()
    assert not view.service.sent and 'changed' in dialog.notice.get()
    dialog.prepare()
    view._select_session(view.sessions[1])
    settle(view)
    dialog.send()
    assert not view.service.sent


def test_research_chooser_preserves_question_and_rejects_old_review_after_renewal(manager_factory, tmp_path):
    manager = manager_factory()
    view = manager.windows[0].view
    view.service.state = tmp_path
    manager.show_command_library(manager.windows[0])
    library = manager._command_library_dialog
    library.query.set('ground brightens when walking')
    library.research_button.invoke()
    dialog = library.research_dialog
    dialog.prepare()
    picker = view._picker
    assert picker and not view.service.sent
    picker.rows.selection_set(0)
    picker.choose()
    settle(view)
    assert dialog.query.get() == 'ground brightens when walking'
    dialog.prepare()
    Preferences(tmp_path).renew()
    dialog.send()
    assert not view.service.sent and Preferences(tmp_path).remaining() == 3
    assert dialog.query.get() == 'ground brightens when walking'
    dialog.prepare()
    target = view.selected
    view._select_session(view.sessions[1])
    view._select_session(target)
    dialog.send()
    assert not view.service.sent and dialog.review is None


def test_three_searches_pause_until_explicit_renewal(manager_factory, tmp_path):
    _, view, dialog = setup(manager_factory, tmp_path)
    for _ in range(3):
        dialog.prepare(); dialog.send(); settle(view)
    dialog.prepare(); dialog.send()
    assert len(view.service.sent) == 3
    assert str(dialog.send_button['state']) == 'disabled'
    dialog.renew_button.invoke()
    assert len(view.service.sent) == 3
    dialog.prepare(); dialog.send(); settle(view)
    assert len(view.service.sent) == 4


def test_model_controls_save_next_send_and_disable_attached_claude(manager_factory, tmp_path):
    manager, view, research = setup(manager_factory, tmp_path)
    view.service.model_options = lambda session: ([{'model': 'example-small', 'description': 'Synthetic small model',
                                                  'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]}], 'Quota unavailable')
    view.show_model_settings()
    dialog = view._model_dialog
    settle(view)
    dialog.override.set(True)
    dialog.toggle_override()
    dialog.model.set('example-small'); dialog.effort.set('low'); dialog.save()
    assert Preferences(tmp_path).get(view.selected)['model'] == 'example-small'
    assert not view.service.sent
    assert 'example-small' in view.model_summary.get()
    dialog.root.geometry('520x610'); manager.root.update()
    assert dialog.save_button.winfo_ismapped()
    dialog.close()
    view._select_session(view.sessions[1]); settle(view)
    view.show_model_settings(); settle(view)
    dialog = view._model_dialog
    assert dialog.save_button.instate(['disabled'])
    assert str(dialog.model_choice['state']) == 'disabled'
    assert not view.service.sent
