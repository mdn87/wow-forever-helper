"""Local picker decisions and durable research reservations use no provider turns."""
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from wow_helper.chat import ChatError, Session
from wow_helper.model_settings import Preferences


def conversation():
    return Session('codex', str(uuid.UUID(int=42)), 'Graphics', 'Game', 'idle', managed=True)


def test_changed_back_settings_and_renewal_invalidate_review_without_spending(tmp_path):
    store, chat = Preferences(tmp_path), conversation()
    seen = store.snapshot(chat)
    epoch = store.allowance()[1]
    store.save(chat, model='example', effort='high', timeout=180)
    store.save(chat, **seen.settings)
    with pytest.raises(ChatError, match='changed'):
        store.authorize(chat, seen, str(uuid.uuid4()), epoch)
    seen = store.snapshot(chat)
    store.renew()
    with pytest.raises(ChatError, match='allowance'):
        store.authorize(chat, seen, str(uuid.uuid4()), epoch)
    assert store.remaining() == 3


def test_two_windows_compete_for_final_research_attempt(tmp_path):
    store, chat = Preferences(tmp_path), conversation()
    for _ in range(2):
        store.reserve_research(str(uuid.uuid4()))
    choice = store.snapshot(chat)
    epoch = store.allowance()[1]

    def reserve(_):
        try:
            Preferences(tmp_path).authorize(chat, choice, str(uuid.uuid4()), epoch)
        except ChatError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(reserve, range(2))) == [False, True]
    assert store.remaining() == 0
