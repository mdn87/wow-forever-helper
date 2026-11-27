"""Synthetic offline tests for Slice 29: hands-free voice item and market lookups."""

from __future__ import annotations

import json
import time

from wow_helper.bnet_api import ATTRIBUTION, ENV_CLIENT_ID, ENV_CLIENT_SECRET, TOKEN_URL, BnetClient
from wow_helper.bnet_voice import BnetVoiceLookup, BnetVoiceResult
from wow_helper.handsfree import HandsFree
from wow_helper.voice_commands import Interpreter

FAKE_ENV = {ENV_CLIENT_ID: "synthetic-id", ENV_CLIENT_SECRET: "synthetic-secret"}


def _make_transport(routes: dict[str, tuple[int, dict]]):
    def transport(method, url, headers, body, timeout, max_bytes):
        if url == TOKEN_URL:
            return 200, json.dumps({"access_token": "tok", "expires_in": 3600}).encode("utf-8")
        for prefix, (status, payload) in routes.items():
            if prefix in url:
                return status, json.dumps(payload).encode("utf-8")
        return 404, b'{"code":404}'
    return transport


def test_voice_grammar_routes_item_market_and_keeps_spell_browser():
    interp = Interpreter(manager=None, window=None)
    m1 = interp.handle("price check Linen Cloth")
    assert (m1.kind, m1.detail, m1.text) == ("bnet", "market", "linen cloth")

    m2 = interp.handle("how much is Linen Cloth on the auction house")
    assert (m2.kind, m2.detail, m2.text) == ("bnet", "market", "linen cloth")

    i1 = interp.handle("item stats for Synthetic Stormblade")
    assert (i1.kind, i1.detail, i1.text) == ("bnet", "item", "synthetic stormblade")

    i2 = interp.handle("what are the stats on Thunderfury")
    assert (i2.kind, i2.detail, i2.text) == ("bnet", "item", "thunderfury")

    # Spell lookup still goes to voice browser directly (Forever /spell/ API is 404)
    sp = interp.handle("look up frostbolt")
    assert (sp.kind, sp.detail, sp.text) == ("browser", "search", "frostbolt")


def test_bnet_voice_lookup_item_hit_404_fallback_and_market(tmp_path):
    routes = {
        "/data/wow/search/item?locale=en_US&name.en_US=Synthetic+Stormblade": (
            200,
            {"results": [{"data": {"id": 19019, "name": {"en_US": "Synthetic Stormblade"}}}]},
        ),
        "/data/wow/search/item?locale=en_US&name.en_US=Linen+Cloth": (
            200,
            {"results": [{"data": {"id": 2589, "name": {"en_US": "Linen Cloth"}}}]},
        ),
        "/data/wow/search/item?locale=en_US&name.en_US=Missing+Spell": (200, {"results": []}),
        "/data/wow/item/19019": (
            200,
            {
                "id": 19019,
                "name": "Synthetic Stormblade",
                "quality": {"name": "Legendary"},
                "level": 80,
                "required_level": 60,
                "inventory_type": {"name": "One-Hand"},
                "preview_item": {
                    "stats": [{"type": {"type": "STAMINA"}, "value": 8, "display": {"display_string": "+8 Stamina"}}]
                },
            },
        ),
        "/data/wow/ruleset/1/auctions/110/commodities": (
            200,
            {"auctions": [{"id": 1, "item": {"id": 2589}, "quantity": 12, "unit_price": 200, "time_left": "LONG"}]},
        ),
        "/data/wow/ruleset/1/auctions/110?": (200, {"id": 110, "name": "Alliance Auction House", "auctions": []}),
    }
    def flexible_transport(method, url, headers, body, timeout, max_bytes):
        if url == TOKEN_URL:
            return 200, json.dumps({"access_token": "tok", "expires_in": 3600}).encode("utf-8")
        if "/data/wow/search/item" in url:
            if "Stormblade" in url:
                return 200, json.dumps({"results": [{"data": {"id": 19019, "name": {"en_US": "Synthetic Stormblade"}}}]}).encode("utf-8")
            if "Linen" in url:
                return 200, json.dumps({"results": [{"data": {"id": 2589, "name": {"en_US": "Linen Cloth"}}}]}).encode("utf-8")
            return 200, json.dumps({"results": []}).encode("utf-8")
        return _make_transport(routes)(method, url, headers, body, timeout, max_bytes)

    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=flexible_transport, min_interval=0.0)
    lookup = BnetVoiceLookup(client_factory=lambda: client, ruleset_id=1, house_id=110)

    hit = lookup.run("item", "Synthetic Stormblade")
    assert hit.status == "done"
    assert "Synthetic Stormblade" in hit.detail
    assert "+8 Stamina" in hit.detail
    assert ATTRIBUTION in hit.detail

    miss = lookup.run("item", "Missing Item")
    assert miss.status == "fallback"
    assert miss.fallback_query == "Missing Item"

    mkt = lookup.run("market", "Linen Cloth")
    assert mkt.status == "done"
    assert "Linen Cloth (#2589)" in mkt.detail
    assert "min 2s" in mkt.detail
    assert ATTRIBUTION in mkt.detail


def test_handsfree_bnet_worker_and_browser_fallback():
    reports = []

    class FakeBridge:
        connected = True
        def report(self, request_id, status, detail):
            reports.append((request_id, status, detail))

    class FakeBrowser:
        def __init__(self):
            self.calls = []
        def run(self, action, argument):
            self.calls.append((action, argument))
            return f"Opened Classic Wowhead for {argument}."

    class FakeBnet:
        def run(self, action, argument):
            if argument == "missing gear":
                return BnetVoiceResult("fallback", "Not found in Forever API.", fallback_query=argument)
            return BnetVoiceResult("done", f"{action} answer for {argument}. {ATTRIBUTION}")

    class FakeWindow:
        id = "win-1"
        caption = "Test"
        closed = False
        view = None
        notices = []
        def set_notice(self, text):
            self.notices.append(text)

    class FakeManager:
        windows = []
        root = None

    browser = FakeBrowser()
    hf = HandsFree(FakeManager(), bridge_factory=FakeBridge, browser_factory=lambda: browser, bnet_factory=FakeBnet)
    hf.window = FakeWindow()

    hf.handle({"id": "req-1", "text": "price check Linen Cloth"})
    hf.handle({"id": "req-2", "text": "item stats for Missing Gear"})

    deadline = time.monotonic() + 3.0
    while len(reports) < 2 and time.monotonic() < deadline:
        hf.answer_finished()
        time.sleep(0.02)

    by_id = {rid: (status, detail) for rid, status, detail in reports}
    assert by_id["req-1"][0] == "done"
    assert "market answer for linen cloth" in by_id["req-1"][1]
    assert ATTRIBUTION in by_id["req-1"][1]
    assert by_id["req-2"][0] == "done"
    assert "checked Classic Wowhead instead" in by_id["req-2"][1]
    assert browser.calls == [("classic", "missing gear")]
