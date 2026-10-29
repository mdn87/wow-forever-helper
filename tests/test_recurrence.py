"""Synthetic recurring goals and clocks; no game data or live providers."""

from copy import deepcopy
from datetime import datetime

import pytest

from wow_helper.chat import ChatError
from wow_helper.journal import JournalService
from wow_helper.recurrence import completed, period, validate_rule
from test_goals import JOURNAL, NOTE, goal


def rule(**changes):
    return dict(frequency='Daily', zone='America/New_York', time='04:00', weekday=0) | changes


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


@pytest.mark.parametrize('reset,now,want', [
    (rule(), '2026-10-28T07:59:59Z', '2026-10-27'),
    (rule(), '2026-10-28T08:00:00Z', '2026-10-28'),
    (rule(frequency='Weekly', weekday=1), '2026-10-27T07:59:59Z', '2026-10-20'),
    (rule(frequency='Weekly', weekday=1), '2026-10-27T08:00:00Z', '2026-10-27'),
    (rule(frequency='Weekly', weekday=1), '2026-11-03T08:59:59Z', '2026-10-27'),
    (rule(frequency='Weekly', weekday=1), '2026-11-03T09:00:00Z', '2026-11-03'),
    (rule(time='02:30'), '2026-03-08T07:29:59Z', '2026-03-07'),
    (rule(time='02:30'), '2026-03-08T07:30:00Z', '2026-03-08'),
    (rule(time='01:30'), '2026-11-01T05:29:59Z', '2026-10-31'),
    (rule(time='01:30'), '2026-11-01T05:30:00Z', '2026-11-01'),
    (rule(time='01:30'), '2026-11-01T06:00:00Z', '2026-11-01'),
    (rule(zone='UTC', time='00:00'), '2027-01-01T00:00:00Z', '2027-01-01'),
])
def test_reset_boundaries(reset, now, want):
    assert period(reset, instant(now)) == want


@pytest.mark.parametrize('changes', [dict(zone='Unknown/Zone'), dict(time='24:00'), dict(time='4:00'),
                                    dict(weekday=True), dict(frequency='Hourly'), dict(extra=True)])
def test_invalid_rules(changes):
    with pytest.raises(ChatError):
        validate_rule(rule(**changes))


def test_manual_history_restart_undo_clock_changes_and_rule_edits(tmp_path):
    service = JournalService(tmp_path)
    reset = rule()
    now = instant('2026-10-28T12:00:00Z')
    entry = service.add(JOURNAL, 'Example activities', 'Original evidence', NOTE,
                        goal=goal() | dict(recurrence=reset), evidence={'text': 'Synthetic source'})['entries'][0]
    original_goal = deepcopy(entry['goal'])
    saved = service.complete_period(JOURNAL, NOTE, True, expected=entry, current_period=period(reset, now), now=now)['entries'][0]
    assert completed(saved, reset, '2026-10-28')
    assert saved['goal'] == original_goal and saved['evidence'] == entry['evidence']
    assert JournalService(tmp_path).load(JOURNAL)['entries'][0] == saved
    before = service.path(JOURNAL).read_bytes()
    for value in ('2026-10-27T12:00:00Z', '2026-12-28T12:00:00Z'):
        assert not completed(saved, reset, period(reset, instant(value)))
    assert service.path(JOURNAL).read_bytes() == before
    assert completed(saved, reset, period(reset, now))  # Return to the recorded period.
    undo = service.complete_period(JOURNAL, NOTE, False, expected=saved, current_period='2026-10-28', now=now)['entries'][0]
    assert not completed(undo, reset, '2026-10-28') and len(undo['completions']) == 2
    changed = service.update_goal(JOURNAL, NOTE, original_goal | dict(recurrence=rule(time='05:00')), None, expected=undo)['entries'][0]
    assert changed['completions'] == undo['completions']
    assert not completed(changed, rule(time='05:00'), '2026-10-28')
    no_repeat = service.update_goal(JOURNAL, NOTE, goal(), None, expected=changed)['entries'][0]
    assert no_repeat['completions'] == undo['completions']


def test_stale_period_conflicts_and_failed_writes_preserve_history(tmp_path, monkeypatch):
    service = JournalService(tmp_path)
    entry = service.add(JOURNAL, 'Example activities', 'Example', NOTE, goal=goal() | dict(recurrence=rule()))['entries'][0]
    now = instant('2026-10-28T12:00:00Z')
    before = service.path(JOURNAL).read_bytes()
    with pytest.raises(ChatError, match='period changed'):
        service.complete_period(JOURNAL, NOTE, True, expected=entry, current_period='2026-10-27', now=now)
    assert service.path(JOURNAL).read_bytes() == before
    saved = service.complete_period(JOURNAL, NOTE, True, expected=entry, current_period='2026-10-28', now=now)['entries'][0]
    with pytest.raises(ChatError, match='another window'):
        service.complete_period(JOURNAL, NOTE, True, expected=entry, current_period='2026-10-28', now=now)
    before = service.path(JOURNAL).read_bytes()
    def fail(*_):
        raise OSError('Synthetic disk failure')
    monkeypatch.setattr('wow_helper.journal.write_json', fail)
    with pytest.raises(ChatError):
        service.complete_period(JOURNAL, NOTE, False, expected=saved, current_period='2026-10-28', now=now)
    assert service.path(JOURNAL).read_bytes() == before


def test_full_or_corrupt_history_is_not_silently_discarded(tmp_path, monkeypatch):
    service = JournalService(tmp_path)
    entry = service.add(JOURNAL, 'Activities', 'Example', NOTE, goal=goal() | dict(recurrence=rule()))['entries'][0]
    monkeypatch.setattr('wow_helper.recurrence.MAX_EVENTS', 0)
    with pytest.raises(ChatError, match='full'):
        service.complete_period(JOURNAL, NOTE, True, expected=entry, current_period='2026-10-28', now=instant('2026-10-28T12:00:00Z'))
    import json
    path = service.path(JOURNAL)
    data = json.loads(path.read_text())
    data['entries'][0]['completions'] = [{'done': 'invented'}]
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    with pytest.raises(ChatError, match='kept'):
        service.load(JOURNAL)
    assert path.read_bytes() == before


from test_workspace import SESSIONS, Service, manager_factory, settle  # noqa: E402,F401


@pytest.mark.parametrize('theme,provider', [('classic', 'codex'), ('modern', 'claude')])
def test_checklist_edit_complete_undo_plan_and_restart(manager_factory, theme, provider):
    from wow_helper.theme import apply_theme
    manager = manager_factory()
    apply_theme(manager.root, theme)
    view = manager.windows[0].view
    view._select_session(next(s for s in SESSIONS if s.provider == provider)); settle(view)
    view.editor.insert('1.0', 'Keep my conversation draft')
    view.show_goals(); owner = view._resume_dialog
    owner.edit_goal(new=True); editor = owner.goal_dialog
    editor.fields['title'].set('Synthetic daily supplies')
    editor.fields['frequency'].set('Daily'); editor.fields['zone'].set('UTC'); editor.fields['reset_time'].set('04:00')
    editor.save(); editor.close()
    owner.show_checklist(); checklist = owner.checklist
    checklist.root.geometry('480x560'); manager.root.update()
    assert len(checklist.rows) == 1 and not view.service.sent
    checklist.toggle()
    assert next(iter(checklist.rows.values()))[3]
    checklist.toggle()
    assert not next(iter(checklist.rows.values()))[3]
    checklist.mode.set('This week'); checklist.reload(); assert not checklist.rows
    checklist.mode.set('Today'); checklist.reload()
    checklist.minutes.set('45'); checklist.priorities.set('Solo supplies first')
    checklist.plan(); followup = checklist.followup
    assert '45 available minutes' in followup.packet['task']
    assert 'Synthetic daily supplies' in followup.packet['context_files'][0]['text']
    assert not view.service.sent
    followup.task.set('Revised priorities'); followup.send(); assert not view.service.sent
    followup.prepare(); followup.send(); followup.send(); settle(view)
    assert len(view.service.sent) == 1
    assert view.editor.get('1.0', 'end-1c') == 'Keep my conversation draft'
    assert manager.save_layout()
    manager.close()
    restored = manager_factory(); view = restored.windows[0].view
    view.show_goals(); view._resume_dialog.show_checklist()
    rows = view._resume_dialog.checklist.rows
    assert len(next(iter(rows.values()))[0]['completions']) == 2
    assert not view.service.sent


def test_checklist_plan_refuses_session_changes_and_keeps_failed_request(manager_factory):
    class Failing(Service):
        def send(self, *_args, **_kwargs):
            raise ChatError('Synthetic delivery failure')
    manager = manager_factory(service=Failing)
    view = manager.windows[0].view
    view._select_session(SESSIONS[0]); settle(view)
    JournalService(view.activity.storage).add(view.journal_id, 'Activities', 'Example', goal=goal() | dict(recurrence=rule()))
    view.show_goals(); owner = view._resume_dialog; owner.show_checklist(); checklist = owner.checklist
    checklist.minutes.set('30'); checklist.priorities.set('Preparation')
    checklist.plan(); followup = checklist.followup
    view._select_session(SESSIONS[1]); settle(view)
    followup.send(); assert followup.packet is None and not view.service.sent
    followup.close(); checklist.plan(); followup = checklist.followup
    followup.send(); settle(view)
    assert followup.attempted and followup.packet and not view.service.sent
    assert checklist.minutes.get() == '30' and checklist.priorities.get() == 'Preparation'


def test_checklist_keyboard_navigation_and_invalid_planning_send_nothing(manager_factory):
    manager = manager_factory(); view = manager.windows[0].view
    service = JournalService(view.activity.storage)
    for title in ('Example supplies', 'Example quests'):
        service.add(view.journal_id, 'Activities', title, goal=goal() | dict(title=title, recurrence=rule()))
    view.show_goals(); owner = view._resume_dialog; owner.show_checklist(); checklist = owner.checklist
    ids = checklist.entries.get_children()
    checklist.entries.selection_set(ids[0]); checklist.entries.focus(ids[0]); checklist.entries.focus_force()
    manager.root.update()
    checklist.entries.event_generate('<Down>'); manager.root.update()
    assert checklist.entries.selection() == (ids[1],)
    checklist.plan()
    assert checklist.followup is None and 'minutes' in checklist.notice.get()
    checklist.minutes.set('30'); checklist.priorities.set('Supplies')
    assert view.selected is None
    checklist.plan()
    assert checklist.followup is None and 'Select a chat' in checklist.notice.get()
    assert not view.service.sent


def test_checklist_editor_stays_with_its_journal_and_failed_refresh_clears_rows(manager_factory, monkeypatch):
    manager = manager_factory(); view = manager.windows[0].view
    service = JournalService(view.activity.storage)
    service.add(view.journal_id, 'Activities', 'Example', goal=goal() | dict(recurrence=rule()))
    view.show_goals(); owner = view._resume_dialog; owner.show_checklist(); checklist = owner.checklist
    original_id = checklist.journal_id
    owner.journal_id = JOURNAL  # Parent navigation must not redirect a checklist edit.
    checklist.edit_goal(); editor = checklist.goal_dialog
    assert editor.journal_id == original_id
    editor.fields['title'].set('Updated activity'); editor.save(); editor.close()
    assert next(iter(checklist.rows.values()))[0]['goal']['title'] == 'Updated activity'
    assert not service.load(JOURNAL)['entries']
    def fail(*_):
        raise ChatError('Synthetic read failure')
    monkeypatch.setattr(JournalService, 'load', fail)
    checklist.mode.set('This week'); assert not checklist.reload()
    assert not checklist.rows and not checklist.entries.get_children()
    assert 'read failure' in checklist.notice.get()
