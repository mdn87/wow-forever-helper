"""Synthetic goals and manual progress; no game data or provider access."""

from copy import deepcopy
import json
import uuid

import pytest

from wow_helper.chat import ChatError
from wow_helper.goals import TEXT_LIMITS, validate_goal
from wow_helper.journal import JournalService
from wow_helper.journal_ui import note_summary

JOURNAL, NOTE, SESSION = [str(uuid.UUID(int=i)) for i in (100, 101, 102)]


def goal():
    return dict.fromkeys(TEXT_LIMITS, '') | dict(title='Example mount', kind='Mount', edition='Classic', state='Planned')


def test_goal_restart_updates_preserve_evidence_and_separate_manual_choices(tmp_path):
    service = JournalService(tmp_path)
    value = goal() | dict(suggestions='Consider a group route.', decision='Try solo first.', progress='Ownership unknown.')
    evidence = dict(text='Synthetic historical source', edition='Classic', snapshot_at=1000, urls=['https://example.com/goal'])
    entry = service.add(JOURNAL, 'Example goals', 'Original advice', NOTE, goal=value,
                        source=dict(provider='codex', session_id=SESSION), evidence=evidence,
                        next_time=dict(text='Check requirements', state='open'))['entries'][0]
    before = service.path(JOURNAL).read_bytes()
    assert JournalService(tmp_path).load(JOURNAL)['entries'][0] == entry
    assert service.path(JOURNAL).read_bytes() == before
    updated = service.update_goal(JOURNAL, NOTE, value | dict(state='Done'),
                                  dict(text='Check requirements', state='open'), expected=entry)['entries'][0]
    assert updated['goal']['state'] == 'Done'
    assert updated['next_time']['state'] == 'open'  # Goal status does not infer step completion.
    assert updated['evidence'] == evidence and updated['source'] == entry['source']
    assert updated['text'] == entry['text'] and updated['at'] == entry['at']
    assert 'AGENT SUGGESTIONS (not player decisions)' in note_summary(updated)
    assert 'PLAYER DECISION' in note_summary(updated) and 'not independently verified' in note_summary(updated)


def test_goal_conflicts_and_write_failure_preserve_prior_record(tmp_path, monkeypatch):
    service = JournalService(tmp_path)
    entry = service.add(JOURNAL, 'Goals', 'Advice', NOTE, goal=goal())['entries'][0]
    current = service.update_goal(JOURNAL, NOTE, goal() | dict(progress='First update'), None, expected=entry)['entries'][0]
    before = service.path(JOURNAL).read_bytes()
    with pytest.raises(ChatError, match='another window'):
        service.update_goal(JOURNAL, NOTE, goal() | dict(progress='Stale update'), None, expected=entry)
    def fail(*_):
        raise OSError('Synthetic write failure')
    monkeypatch.setattr('wow_helper.journal.write_json', fail)
    with pytest.raises(ChatError, match='draft'):
        service.update_goal(JOURNAL, NOTE, goal() | dict(progress='Failed update'), None, expected=current)
    assert service.path(JOURNAL).read_bytes() == before


@pytest.mark.parametrize('changes', [dict(title=''), dict(edition='Invented'), dict(state='Automatically complete'),
    dict(kind='Executable'), dict(title='x' * 201), dict(suggestions='x' * 8001), dict(progress='\ud800'),
    dict(url='javascript:execute'), dict(review={'text': 'Suggestion', 'source': {'provider': 'invalid'}})])
def test_invalid_goal_never_overwrites_notes(tmp_path, changes):
    service = JournalService(tmp_path)
    service.add(JOURNAL, 'Goals', 'Existing')
    before = service.path(JOURNAL).read_bytes()
    with pytest.raises(ChatError):
        service.add(JOURNAL, 'Goals', 'New', goal=goal() | changes)
    assert service.path(JOURNAL).read_bytes() == before


def test_corrupt_goal_is_kept_and_review_evidence_is_bounded(tmp_path):
    service = JournalService(tmp_path)
    service.add(JOURNAL, 'Goals', 'Advice', NOTE, goal=goal())
    path = service.path(JOURNAL)
    data = json.loads(path.read_text())
    del data['entries'][0]['goal']['state']
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    with pytest.raises(ChatError, match='kept'):
        service.add(JOURNAL, 'Goals', 'Other advice')
    assert path.read_bytes() == before
    with pytest.raises(ChatError, match='64,000'):
        validate_goal(goal() | dict(review=dict(text='Suggestion', evidence=dict(text='🎮' * 16000))))


def test_goal_reply_review_does_not_change_decisions_or_original_source(tmp_path):
    service = JournalService(tmp_path)
    entry = service.add(JOURNAL, 'Goals', 'Original note', NOTE,
                        goal=goal() | dict(decision='Solo only'), evidence={'text': 'First source'})['entries'][0]
    reviewed = deepcopy(entry['goal'])
    reviewed.update(suggestions='Try with a group.', review=dict(text='Try with a group.',
                    source=dict(provider='claude', session_id=SESSION), evidence=dict(text='Reviewed plan evidence')))
    saved = service.update_goal(JOURNAL, NOTE, reviewed, None, expected=entry)['entries'][0]
    assert saved['goal']['decision'] == 'Solo only'
    assert saved['evidence']['text'] == 'First source'
    assert saved['goal']['review']['source']['provider'] == 'claude'
    assert 'Reviewed plan evidence' in note_summary(saved)


def test_review_with_unknown_source_is_readable_and_journal_request_includes_goal(tmp_path):
    from wow_helper.activities import ActivityService, packet_preview, profile_settings
    value = goal() | dict(constraints='Solo play', review=dict(text='Unverified suggestion', source=None, evidence=None))
    service = JournalService(tmp_path)
    entry = service.add(JOURNAL, 'Goals', 'Original note', goal=value)['entries'][0]
    assert 'Unknown' in note_summary(entry)
    activity = ActivityService(tmp_path)
    packet = activity.prepare('journal', profile_settings('journal'), journal_id=JOURNAL)
    assert 'Solo play' in packet_preview(packet)
    assert 'Unverified suggestion' in packet_preview(packet)
