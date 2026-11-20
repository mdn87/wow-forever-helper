"""Exercise the native picker with synthetic conversations on the isolated test desktop."""
import threading
from dataclasses import replace

import pytest

from test_workspace import CreatingService, manager_factory, settle  # noqa: F401
from wow_helper.model_settings import Preferences


def test_duplicate_titles_keyboard_and_saved_draft_collision(manager_factory, tmp_path):
    manager = manager_factory(service=CreatingService)
    view = manager.windows[0].view
    first, other = view.sessions
    second = replace(other, provider=first.provider, title=first.title)
    view.sessions = [first, second]
    view._session_labels()
    view.drafts[second.key] = 'Earlier unsent question'
    view.replace_draft('Why does the ground brighten?')
    view.send()
    picker = view._picker
    assert picker.rows.get(0) != picker.rows.get(1) and 'External' in picker.rows.get(0)
    picker.close()
    assert view.selected is None and not view.service.sent
    view.send()
    picker = view._picker
    picker.rows.selection_set(1)
    picker.rows.focus_force()
    picker.root.update()
    picker.rows.event_generate('<Return>')
    settle(view)
    assert view.selection_key == second.key and not view.service.sent
    view.editor.event_generate('<Return>')  # Still-held choose key.
    view.editor.event_generate('<KeyRelease-Return>')
    assert not view.service.sent
    assert view.editor.get('1.0', 'end-1c') == 'Why does the ground brighten?'
    view.saved_button.invoke()
    assert view._draft_dialog.preview.get('1.0', 'end-1c') == 'Earlier unsent question'
    view._draft_dialog.apply(False)
    assert view.editor.get('1.0', 'end-1c') == 'Earlier unsent question'
    view.show_saved_draft()
    view._draft_dialog.apply(False)
    snapshot = view.snapshot()
    assert snapshot['draft'] == 'Why does the ground brighten?'
    assert any(row['saved'] == 'Earlier unsent question' for row in snapshot['conversation_drafts'])
    assert 'conversation_drafts' not in view.snapshot(False) and 'draft' not in view.snapshot(False)
    # The same two stable identities will be rediscovered when this window reopens.
    class Reopened(CreatingService):
        def __init__(self):
            super().__init__()
            self.sessions = [first, second]
    path = manager.layout_path
    manager.close()
    manager = manager_factory(path, service=Reopened)
    restored = manager.windows[0].view
    assert restored.saved_drafts[second.key] == 'Earlier unsent question'
    assert restored.editor.get('1.0', 'end-1c') == 'Why does the ground brighten?'
    restored.send()
    settle(restored)
    assert restored.service.sent == [(second.key, 'Why does the ground brighten?')]
    assert restored.saved_drafts[second.key] == 'Earlier unsent question'


def test_cancel_while_creating_has_no_late_selection_or_send(manager_factory):
    gate = threading.Event()
    class Slow(CreatingService):
        def create(self, *args, **kwargs):
            assert gate.wait(4)
            return super().create(*args, **kwargs)
    manager = manager_factory(service=Slow)
    view = manager.windows[0].view
    view.replace_draft('Held question')
    view.send()
    try:
        view._picker.create('claude')
        view._picker.close()
        assert view.pending_creation is None
    finally:
        gate.set()
    settle(view)
    assert view.selected is None and not view.service.sent
    assert len(view.service.created) == 1 and view.editor.get('1.0', 'end-1c') == 'Held question'


def test_retyped_identical_draft_survives_completed_delivery(manager_factory):
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(view.sessions[0])
    settle(view)
    started, release = threading.Event(), threading.Event()
    def send(*_):
        started.set()
        assert release.wait(3)
        return 'queued'
    view.service.send = send
    view.replace_draft('First question')
    try:
        view.send()
        assert started.wait(1)
        view.replace_draft('Different question')
        view.replace_draft('First question')
    finally:
        release.set()
    settle(view)
    assert view.editor.get('1.0', 'end-1c') == 'First question'


def test_foreground_usage_dialog_defaults_to_keep_and_bills_once(manager_factory):
    from wow_helper.provider_usage import AccountUsage, BillingConsent, UsageDecision
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(view.sessions[0])
    settle(view)
    calls = []
    def guarded(session, body, request, choice, *, billing_consent=None, **_):
        usage = AccountUsage.from_codex({'accountId': 'test', 'ordinaryUsageAllowed': False,
                                          'rateLimits': {'spendControlReached': False, 'credits': {'hasCredits': True}}})
        token = BillingConsent.for_request(usage.account, request, choice, None, body)
        if billing_consent != token:
            raise UsageDecision(usage, token)
        calls.append((request, body))
        return 'queued'
    view.service.send_reviewed = guarded
    view.replace_draft('Question on a limited plan')
    view.send()
    settle(view)
    dialog = view._usage_dialog
    assert dialog and dialog.once and not calls
    assert dialog.root.focus_lastfor() == dialog.keep
    dialog.keep.invoke()
    assert view.editor.get('1.0', 'end-1c') == 'Question on a limited plan'
    view.send()
    settle(view)
    dialog = view._usage_dialog
    dialog.proceed()
    dialog.proceed()
    settle(view)
    assert len(calls) == 1 and view.editor.get('1.0', 'end-1c') == ''


def test_two_window_summary_catches_a_change_before_send(manager_factory, tmp_path):
    manager = manager_factory()
    a = manager.windows[0].view
    b = manager.new_window(kind='chat').view
    settle(b)
    for view in (a, b):
        view.service.state = tmp_path
        view._select_session(view.sessions[0])
        settle(view)
    a.replace_draft('A limited-plan question')
    Preferences(tmp_path).save(b.selected, model='small', effort='low', timeout=180)
    b.refresh_model_summary()
    a.send()
    assert not a.service.sent and 'small' in a.model_summary.get()
    assert a.editor.get('1.0', 'end-1c') == 'A limited-plan question'
    a.send()
    settle(a)
    assert a.service.sent == [(a.selected.key, 'A limited-plan question')]


def test_failed_managed_reply_restores_sent_draft_without_overwriting_new_text(manager_factory):
    manager = manager_factory(service=CreatingService)
    view = manager.windows[0].view
    view.start_session('claude')
    settle(view)
    view.replace_draft('Original question')
    view.send()
    settle(view)
    wait = view.response_waits[view.selected.key][0]
    view.replace_draft('Different question')
    view._observe_responses(view.selected.key, [], {wait.request_id: 'failed'})
    assert view.editor.get('1.0', 'end-1c') == 'Different question'
    assert view.saved_drafts[view.selected.key] == 'Original question'
    assert len(view.service.sent) == 1


@pytest.mark.parametrize('theme,scaling', [('classic', 1.33), ('modern', 1.67)])
def test_managed_presets_and_model_controls_fit_at_minimum(manager_factory, theme, scaling):
    manager = manager_factory(service=CreatingService)
    manager.preview_interface({'theme': theme})
    view = manager.windows[0].view
    original = view.root.tk.call('tk', 'scaling')
    view.root.tk.call('tk', 'scaling', scaling)
    try:
        view.new_chat_button.invoke()
        view._picker.providers['claude'].invoke()
        settle(view)
        view.service.model_options = lambda _: ([], 'Check /usage in Claude.')
        view.model_button.invoke()
        settle(view)
        dialog = view._model_dialog
        dialog.chrome.place('430x475+40+40')
        dialog.choose_model_button.invoke()
        dialog.model_choice.set('haiku')
        dialog.tabs.select(0)
        for effort in ('low', 'high', 'medium'):
            dialog.presets[effort].invoke()
            assert dialog.model.get() == 'haiku' and dialog.effort.get() == effort
        dialog.save_button.invoke()
        assert 'haiku (alias)' in view.model_summary.get() and 'Medium' in view.model_summary.get()
        dialog.root.update()
        for widget in (dialog.choose_model_button, dialog.save_button, *dialog.presets.values()):
            assert widget.winfo_ismapped()
            assert widget.winfo_rooty() + widget.winfo_height() <= dialog.root.winfo_rooty() + dialog.root.winfo_height()
        assert view.service.sent == []
        dialog.close()
    finally:
        view.root.tk.call('tk', 'scaling', original)
