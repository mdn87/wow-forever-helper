"""Synthetic local search, without provider discovery or filesystem crawling."""

from types import SimpleNamespace
import uuid

from wow_helper import search
from wow_helper.activities import ActivityService
from wow_helper.activity_layouts import SavedLayouts


def test_search_limits_leave_registered_commands_accessible(tmp_path, monkeypatch):
    activity = ActivityService(tmp_path)
    for index in range(12):
        activity.add_note(str(uuid.UUID(int=index)), 'Example journal', f'Synthetic note {index}')
    manager = SimpleNamespace(windows=[], activity_factory=lambda: activity, saved_layouts=SavedLayouts(None))
    monkeypatch.setattr(search, 'MAX_RESULTS', 12)
    rows, notices = search.search_index(manager)
    assert len(rows) <= 12 and notices
    assert any(r['kind'] == 'command' and r['target'] == 'interface' for r in rows)
    assert all(r['kind'] in {'command', 'note'} for r in rows)


def test_unicode_search_matches_all_terms_without_interpreting_commands():
    rows = [{'search': search.folded('Straße Café northern camp')}]
    assert search.matching(rows, 'STRASSE CAFE\u0301') == rows
    assert not search.matching(rows, 'café southern')
    assert not search.matching(rows, '$(execute)')
