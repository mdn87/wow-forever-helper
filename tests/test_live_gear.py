"""Explicit comparison lifecycle with synthetic pixels and fake agent results."""

from copy import deepcopy
from pathlib import Path
import uuid
import pytest
from PIL import Image

from wow_helper.chat import ChatError, Session
from wow_helper.live_gear import LiveGear
from test_gear_compare import sample

SESSION = Session('codex', str(uuid.UUID(int=10)), 'Example', 'Example', 'ready', managed=True)


class Agents:
    def __init__(self):
        self.calls = []
        self.data = sample()
    def send(self, session, body, request_id, **options):
        self.calls.append((body, request_id, options))
    def result(self, *_):
        data = self.data if len(self.calls) == 1 else dict(summary='Example tradeoff.', steps=[], sources=[], caveats=[])
        return {'status': 'completed', 'structured': deepcopy(data)}
    def idle(self, _):
        return True
    def present(self, *_):
        pass


def service(tmp_path, *, capture=None, target=None):
    folder = tmp_path / 'captures'; folder.mkdir(exist_ok=True)
    preview = str(uuid.uuid4()) + '.png'
    Image.new('RGB', (400, 300), 'blue').save(folder / preview)
    calls = []
    def snap(storage, flavor, **options):
        calls.append(options)
        name = str(uuid.uuid4()) + '.png'
        Image.new('RGB', (400, 300), 'blue').save(Path(storage) / 'captures' / name)
        return name
    agents = Agents()
    engine = LiveGear(tmp_path, agents, target=target or (lambda: (SESSION.key, 1)),
                      capture=capture or snap, identify=lambda _: 42, foreground=lambda: 42)
    engine.approve(SESSION, 1, '_retail_', preview, [0, 0, 400, 300], 'Example build', 'Example goal')
    return engine, agents, calls


def test_one_request_crops_sends_validates_and_records_result(tmp_path):
    engine, agents, calls = service(tmp_path)
    request = str(uuid.uuid4())
    engine.begin(request, background=False)
    result = engine.snapshot()
    assert result['state'] == 'completed' and not engine.busy
    assert len(calls) == 1 and calls[0]['region'] == [0, 0, 400, 300]
    assert len(agents.calls) == 2
    assert result['comparisons'][0]['deltas'][0]['delta'] == -30
    assert result['timings'].keys() == {'capture', 'extraction', 'explanation'}
    assert result['source']['session_id'] == SESSION.id
    with pytest.raises(ChatError, match='already'):
        engine.begin(request, background=False)


def test_changed_destination_prevents_capture(tmp_path):
    current = [(SESSION.key, 1)]
    engine, agents, calls = service(tmp_path, target=lambda: current[0])
    current[0] = (SESSION.key, 2)
    with pytest.raises(ChatError, match='[Rr]eview'):
        engine.begin(background=False)
    assert not calls and not agents.calls


def test_destination_change_during_capture_prevents_send(tmp_path):
    current = [(SESSION.key, 1)]
    def capture(*_, **__):
        current[0] = (SESSION.key, 2)
        return 'unused.png'
    engine, agents, _ = service(tmp_path, target=lambda: current[0], capture=capture)
    engine.begin(background=False)
    assert engine.snapshot()['state'] == 'failed' and not agents.calls


def test_missing_tooltip_fails_without_explanation_or_retry(tmp_path):
    engine, agents, calls = service(tmp_path)
    agents.data['candidate'] = None
    engine.begin(background=False)
    assert engine.snapshot()['state'] == 'failed'
    assert len(calls) == len(agents.calls) == 1


def test_restart_and_disable_never_replay_or_capture(tmp_path):
    engine, agents, calls = service(tmp_path)
    engine.begin(background=False)
    restored = LiveGear(tmp_path, agents, target=lambda: (SESSION.key, 1))
    assert not restored.approval and not restored.busy
    engine.disable()
    with pytest.raises(ChatError, match='[Rr]eview'):
        engine.begin(background=False)
    assert len(calls) == 1


def test_foreground_mismatch_prevents_capture(tmp_path):
    engine, agents, calls = service(tmp_path)
    engine.foreground = lambda: 99
    engine.begin(background=False)
    assert engine.snapshot()['state'] == 'failed' and not calls and not agents.calls


def test_unmanaged_destination_cannot_be_approved(tmp_path):
    engine, _, _ = service(tmp_path)
    with pytest.raises(ChatError, match='companion'):
        engine.approve(Session('codex', SESSION.id, 'Example', '', 'ready'), 1, '_retail_',
                       'unused.png', [0, 0, 400, 300], 'Example', 'Example')


def test_send_failure_is_not_retried(tmp_path):
    engine, agents, captures = service(tmp_path)
    calls = []
    def failed(*args, **kwargs):
        calls.append(True)
        raise ChatError('Synthetic delivery failure')
    agents.send = failed
    engine.begin(background=False)
    assert len(calls) == len(captures) == 1 and engine.snapshot()['state'] == 'failed'


def test_busy_press_is_not_queued(tmp_path):
    import threading
    entered, release = threading.Event(), threading.Event()
    def capturing(*_, **__):
        entered.set(); release.wait(2)
        raise ChatError('Synthetic stopped capture')
    engine, agents, _ = service(tmp_path, capture=capturing)
    engine.begin()
    try:
        assert entered.wait(2)
        with pytest.raises(ChatError, match='not queued'):
            engine.begin()
    finally:
        release.set()


def test_reviewed_result_saves_source_image_and_full_facts_to_journal(tmp_path):
    from wow_helper.journal import JournalService
    from wow_helper.live_gear import journal_selection
    engine, _, _ = service(tmp_path)
    engine.begin(background=False)
    selection = journal_selection(engine.snapshot())
    journal_id = str(uuid.uuid4())
    journal = JournalService(tmp_path)
    journal.add(journal_id, 'Example journal', selection['text'],
                source=selection['source'], evidence=selection['evidence'])
    saved = journal.load(journal_id)['entries'][0]
    assert saved['source']['session_id'] == SESSION.id
    assert saved['evidence']['image'] == engine.snapshot()['image']
    assert 'Example candidate' in saved['evidence']['text']
