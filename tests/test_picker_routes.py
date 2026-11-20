"""Exercise the real dispatch boundaries with local provider doubles."""
import time
import uuid

import pytest

from wow_helper import chat
from wow_helper.chat import ChatError, ChatService, read_json
from wow_helper.codex_chat import CodexClient
from wow_helper.model_settings import Preferences
from wow_helper.provider_usage import AccountUsage, FRESH_SECONDS, UsageDecision


def uid(n):
    return str(uuid.UUID(int=n))


class LocalCodex(CodexClient):
    def __init__(self):
        self.sent = []
        self.status = 'idle'
        self.data = {'accountId': 'example-account', 'ordinaryUsageAllowed': True, 'rateLimits': {}}
        self.available = ['small', 'large']
        self.failed = False

    def sessions(self):
        return [{'id': uid(1), 'name': 'Graphics', 'status': {'type': self.status}}]

    def models(self):
        return [{'model': name, 'defaultReasoningEffort': 'low',
                 'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]} for name in self.available]

    def rpc(self, method, _):
        if method == 'thread/read':
            return {'thread': {'status': {'type': self.status}}}
        assert method == 'account/rateLimits/read'
        if self.failed:
            raise ChatError('Synthetic account read failed')
        return self.data

    def _rpc(self, method, params):
        assert method == 'turn/start'
        self.sent.append(params)
        return {'turn': {'id': 'test-turn'}}

    def send(self, session_id, body):
        self.sent.append((session_id, body))

    def close(self):
        pass


@pytest.fixture
def route(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, 'claude_sessions', lambda _: [])
    client = LocalCodex()
    service = ChatService(tmp_path, client)
    session = service.discover()[0][0]
    return service, client, session, Preferences(tmp_path)


def test_preflight_then_charged_attempt_on_uncertain_delivery(route, monkeypatch):
    service, client, session, prefs = route
    prefs.save(session, model='small', effort='low', timeout=180)
    seen, epoch = prefs.snapshot(session), prefs.allowance()[1]
    client.status = 'active'
    with pytest.raises(ChatError, match='idle'):
        service.send_reviewed(session, 'question', uid(2), seen, research_epoch=epoch)
    client.status = 'idle'
    client.available = ['large']
    with pytest.raises(ChatError, match='unavailable'):
        service.send_reviewed(session, 'question', uid(2), seen, research_epoch=epoch)
    assert prefs.remaining() == 3 and not client.sent
    client.available = ['large', 'small']
    def interrupted(*args):
        client.sent.append(args)
        raise OSError('Synthetic loss after dispatch')
    monkeypatch.setattr(client, '_rpc', interrupted)
    with pytest.raises(ChatError, match='unconfirmed'):
        service.send_reviewed(session, 'question', uid(2), seen, research_epoch=epoch)
    with pytest.raises(ChatError, match='already attempted'):
        service.send_reviewed(session, 'question', uid(2), seen, research_epoch=epoch)
    assert prefs.remaining() == 2 and len(client.sent) == 1


def test_quota_pause_account_change_and_replay(route):
    service, client, session, prefs = route
    seen, epoch = prefs.snapshot(session), prefs.allowance()[1]
    client.data.update(ordinaryUsageAllowed=False,
                       rateLimits={'spendControlReached': False, 'credits': {'hasCredits': True}})
    with pytest.raises(UsageDecision) as first:
        service.send_reviewed(session, 'question', uid(2), seen, research_epoch=epoch)
    consent = first.value.consent
    assert consent and first.value.usage.extras
    assert prefs.remaining() == 3 and not client.sent
    client.data['accountId'] = 'different-account'
    with pytest.raises(ChatError, match='account'):
        service.send_reviewed(session, 'question', uid(2), seen, research_epoch=epoch, billing_consent=consent)
    client.data['accountId'] = 'example-account'
    assert service.send_reviewed(session, 'question', uid(2), seen, research_epoch=epoch,
                                 billing_consent=consent) == 'queued'
    with pytest.raises(UsageDecision):
        service.send_reviewed(session, 'another question', uid(3), seen)
    with pytest.raises(ChatError, match='already'):
        service.send_reviewed(session, 'question', uid(2), seen, research_epoch=epoch, billing_consent=consent)
    with pytest.raises(ChatError, match='request changed'):
        service.send_reviewed(session, 'another question', uid(3), seen, billing_consent=consent)
    assert prefs.remaining() == 2 and len(client.sent) == 1


def test_hard_limit_and_stale_or_missing_readings(route):
    service, client, session, prefs = route
    client.data['rateLimits'] = {'primary': {'usedPercent': 100, 'windowDurationMins': 300},
                                 'spendControlReached': True, 'credits': {'hasCredits': True}}
    current = service.read_usage(session)
    assert current.hard_stop and not current.extras and current.paused()
    assert '5 hours' in current.describe() and '100%' in current.describe()
    with pytest.raises(UsageDecision):
        service.send_reviewed(session, 'question', uid(2), prefs.snapshot(session))
    client.failed = True
    old = service.read_usage(session)
    assert not old.paused() and 'Stale' in old.describe() and '100%' in old.describe()
    age = AccountUsage.from_codex(client.data, now=time.time() - FRESH_SECONDS - 1)
    assert 'Stale' in age.describe() and not age.paused()
    assert not AccountUsage.from_codex({'rateLimits': {'primary': {'usedPercent': 100}}}).paused()
    assert not AccountUsage.from_codex({}).paused()


@pytest.mark.parametrize('provider', ('codex', 'claude'))
def test_managed_transport_pins_choice_and_preflights_busy_before_reserving(route, monkeypatch, provider):
    from wow_helper import agent_sessions
    service, client, _, prefs = route
    monkeypatch.setattr(agent_sessions, 'command', lambda _: ['synthetic'])
    monkeypatch.setattr(agent_sessions.subprocess, 'Popen', lambda *a, **kw: object())
    session = service.create(provider, creation_id=uid(7))
    model = 'small' if provider == 'codex' else 'haiku'
    prefs.save(session, model=model, effort='low', timeout=90, catalog_bound=provider == 'codex')
    choice, epoch = prefs.snapshot(session), prefs.allowance()[1]
    assert service.send_reviewed(session, 'test', uid(3), choice, research_epoch=epoch) == 'started'
    packet = service.agents.result(session.id, uid(3))
    assert (packet['model'], packet['effort'], packet['timeout']) == (model, 'low', 90)
    with pytest.raises(ChatError, match='unfinished'):
        service.send_reviewed(session, 'test', uid(4), choice, research_epoch=epoch)
    assert prefs.remaining() == 2 and not client.sent


def test_late_read_for_previous_account_cannot_replace_new_account(route, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    service, client, session, _ = route
    newer = ChatService(service.state, LocalCodex())
    newer.codex.data['accountId'] = 'new-account'
    started, release = threading.Event(), threading.Event()
    def delayed(*_):
        started.set()
        assert release.wait(3)
        return client.data
    monkeypatch.setattr(client, 'rpc', delayed)
    with ThreadPoolExecutor() as worker:
        late = worker.submit(service.read_usage, session)
        try:
            assert started.wait(1)
            current = newer.read_usage(session)
        finally:
            release.set()
        with pytest.raises(ChatError, match='account changed'):
            late.result()
    assert newer.usage_scope.current(current)


def test_attached_claude_preserves_external_settings_and_delivers_once(route, monkeypatch):
    service, _, _, prefs = route
    session = chat.Session('claude', uid(8), 'Graphics', 'Game', 'idle')
    monkeypatch.setattr(chat, 'claude_sessions', lambda _: [session])
    choice = prefs.snapshot(session)
    assert service.send_reviewed(session, 'question', uid(2), choice) == 'waiting for Claude to poll'
    path = service.state / 'claude' / session.id / 'inbox' / (uid(2) + '.json')
    assert read_json(path)['text'] == 'question'
    with pytest.raises(ChatError, match='already attempted'):
        service.send_reviewed(session, 'question', uid(2), choice)
