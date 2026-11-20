"""Synthetic model preferences and bounded research; no provider requests."""
import uuid

import pytest

from wow_helper.chat import ChatError, Session
from wow_helper.model_settings import Preferences, research_prompt, usage_summary
from wow_helper.codex_chat import CodexClient


def session(provider='codex', managed=False):
    return Session(provider, str(uuid.UUID(int=17)), 'Synthetic chat', '', 'idle', managed=managed)


def test_preferences_survive_restart_and_separate_sessions(tmp_path):
    store = Preferences(tmp_path)
    assert store.get(session())['model'] == ''
    assert store.get(session(managed=True))['effort'] == 'low'
    store.save(session(), model='example-small', effort='low', timeout=90)
    assert Preferences(tmp_path).get(session())['model'] == 'example-small'
    assert store.get(session('claude'))['model'] == ''
    with pytest.raises(ChatError):
        store.save(session('claude'), model='sonnet', effort='low', timeout=90)


def test_research_allowance_is_durable_global_and_never_replays(tmp_path):
    store = Preferences(tmp_path)
    for n in range(3):
        store.reserve_research(str(uuid.UUID(int=n)))
    assert Preferences(tmp_path).remaining() == 0
    with pytest.raises(ChatError, match='allowance'):
        store.reserve_research(str(uuid.UUID(int=4)))
    store.renew()
    with pytest.raises(ChatError, match='already'):
        store.reserve_research(str(uuid.UUID(int=1)))
    assert store.remaining() == 3


def test_research_prompt_has_scope_and_no_hard_budget_claim():
    text = research_prompt('ground gets brighter', 'WoW Forever')
    assert 'ground gets brighter' in text and 'at most 3' in text
    assert 'Do not execute' in text and 'source URLs' in text
    with pytest.raises(ChatError):
        research_prompt('x' * 1500, '')


def test_usage_distinguishes_unknown_from_available():
    assert 'unavailable' in usage_summary({})
    assert '80%' in usage_summary({'rateLimits': {'primary': {'usedPercent': 80, 'windowDurationMins': 300}}})
    assert 'not allowed' in usage_summary({'ordinaryUsageAllowed': False})


@pytest.mark.parametrize('busy,fail', [(False, False), (True, False), (False, True)])
def test_attached_codex_model_send_is_explicit_and_never_falls_back(monkeypatch, busy, fail):
    client = CodexClient()
    calls = []
    monkeypatch.setattr(client, 'models', lambda: [{'model': 'example-small', 'defaultReasoningEffort': 'low',
                                                 'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]}])
    monkeypatch.setattr(client, 'rpc', lambda *_: {'thread': {'status': {'type': 'active' if busy else 'idle'}}})
    def request(method, params):
        calls.append((method, params))
        if fail:
            raise TimeoutError('Synthetic timeout after potential delivery')
        return {'turn': {'id': 'synthetic-turn'}}
    monkeypatch.setattr(client, '_rpc', request)
    monkeypatch.setattr(client, 'send', lambda *_: pytest.fail('must never fall back'))
    if busy or fail:
        with pytest.raises(ChatError):
            client.send_with_model(session().id, 'Synthetic search', 'example-small', 'low')
    else:
        client.send_with_model(session().id, 'Synthetic search', 'example-small', 'low')
    assert len(calls) == (0 if busy else 1)
    if calls:
        assert calls[0][0] == 'turn/start'
        assert calls[0][1]['model'] == 'example-small'
        assert calls[0][1]['serviceTier'] == 'default'
        assert 'sandboxPolicy' not in calls[0][1]
    with pytest.raises(ChatError):
        client.send_with_model(session().id, 'Synthetic search', 'missing-model', 'low')


def test_corrupt_preferences_and_allowance_fail_closed(tmp_path):
    store = Preferences(tmp_path)
    store.folder.mkdir()
    (store.folder / 'research.json').write_text('{broken', encoding='utf-8')
    with pytest.raises(ChatError):
        store.reserve_research(str(uuid.uuid4()))
    path = store.path(session())
    path.parent.mkdir()
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(ChatError):
        store.get(session())
