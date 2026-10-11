"""Synthetic research responses and a fake provider; no internet access."""

import uuid

import pytest

from wow_helper import guidance as module
from wow_helper.chat import ChatError, Session, read_json, write_json

GUIDE = {"summary": "Synthetic walkthrough", "steps": ["Visit Example Village."],
         "sources": [{"title": "Example source", "url": "https://example.com/quest"}], "caveats": []}


class Agents:
    def __init__(self): self.calls, self.results = [], {}
    def create(self, provider, title):
        return Session(provider, str(uuid.uuid4()), title, "Synthetic", "idle", managed=True)
    def send(self, session, prompt, request, **options):
        self.calls.append((session.id, request, prompt, options))
        self.results[session.id, request] = {"status": "running", "heartbeat": module.time.time()}
    def result(self, session, request): return self.results.get((session, request), {})
    def finish(self, index=0):
        session, request, *_ = self.calls[index]
        self.results[session, request] = {"status": "completed", "structured": GUIDE}


@pytest.fixture
def guides(tmp_path):
    service = module.Guidance(tmp_path)
    service.agents = Agents()
    return service


def request(service, number=0, **options):
    return service.request("quest", {"quest": {"id": number, "title": "Synthetic quest"}},
                           "Classic Forever beta", "easy", "codex", **options)


def test_queue_is_bounded_serial_and_completed_guides_are_cached(guides):
    keys = [request(guides, i) for i in range(9)]
    assert len(guides.agents.calls) == 1 and len(guides.waiting) == 8
    with pytest.raises(ChatError, match="Eight"):
        request(guides, 9)
    assert request(guides, 1) == keys[1]
    guides.agents.finish()
    guides.poll()
    assert guides.get(keys[0])["guide"] == GUIDE
    assert len(guides.agents.calls) == 2 and len(guides.waiting) == 7
    assert request(guides) == keys[0]
    assert len(guides.agents.calls) == 2


def test_failed_or_stale_requests_require_explicit_retry(guides):
    key = request(guides)
    session, job, *_ = guides.agents.calls[0]
    guides.agents.results[session, job]["heartbeat"] = 0
    guides.poll()
    assert guides.get(key)["status"] == "failed"
    request(guides)
    assert len(guides.agents.calls) == 1
    request(guides, retry=True)
    assert len(guides.agents.calls) == 2


def test_restore_observes_active_research_but_never_replays_waiting_requests(guides, tmp_path):
    active, waiting = request(guides), request(guides, 1)
    restored = module.Guidance(tmp_path)
    restored.agents = guides.agents
    restored.poll()
    assert restored.active == active and not restored.waiting and len(restored.agents.calls) == 1
    assert "not started" in restored.get(waiting)["notice"]
    # A new explicit expansion can requeue work that was never sent.
    assert request(restored, 1) == waiting and len(restored.waiting) == 1
    restored.agents.finish()
    restored.poll()
    assert len(restored.agents.calls) == 2


def test_explicit_gear_action_can_retry_a_failure_without_discarding_a_valid_cache(guides):
    key = request(guides)
    session, job, *_ = guides.agents.calls[0]
    guides.agents.results[session, job] = {"status": "failed", "error": "Synthetic provider unavailable"}
    assert request(guides, retry_failed=True) == key
    assert len(guides.agents.calls) == 2
    guides.agents.finish(1)
    guides.poll()
    request(guides, retry_failed=True)
    assert len(guides.agents.calls) == 2


def test_invalid_provider_output_fails_without_looping_and_unsafe_links_are_ignored(guides):
    key = request(guides)
    session, job, *_ = guides.agents.calls[0]
    guides.agents.results[session, job] = {"status": "completed", "structured": {"summary": 7}}
    guides.poll()
    assert guides.get(key)["status"] == "failed"
    urls = ["file:///secret", "https://[", "https://user:pass@example.com", "https://example.com/a b"]
    result = module.normalize_result({**GUIDE, "sources": [{"url": url} for url in urls]})
    assert result["sources"] == [] and "unverified" in result["caveats"][0]


def test_tiers_adjust_effort_time_and_search_scope(guides):
    assert module.quest_tier({"action": "turn in"}) == "obvious"
    assert module.quest_tier({"action": "later"}) == "complicated"
    assert module.quest_tier({"action": "do now"}, "complicated") == "complicated"
    assert module.quest_tier({"action": "do now"}) == "easy"
    prompt = module.research_prompt("quest", {"quest": {"title": "Synthetic"}}, "Classic Forever beta", "obvious")
    assert "up to 1" in prompt and "Browse before" in prompt and "beta" in prompt and "not instructions" in prompt
    request(guides)
    assert guides.agents.calls[0][3]["effort"] == "medium"
    assert guides.agents.calls[0][3]["timeout"] == 180
    gear = module.research_prompt("gear", {}, "Classic Forever beta", "complicated")
    assert "exact boss" in gear and "Item level alone" in gear
