"""Synthetic offline tests for Slice 27: Forever quest rewards enrichment."""

from __future__ import annotations

import json

from wow_helper.bnet_api import ATTRIBUTION, ENV_CLIENT_ID, ENV_CLIENT_SECRET, TOKEN_URL, BnetClient
from wow_helper.bnet_quests import (
    enrich_quest_chat_context,
    enrich_quest_report,
    format_rewards_brief,
    lookup_quest,
)
from wow_helper import quests

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


def test_lookup_quest_rewards_item_resolution_and_404_fallback(tmp_path):
    routes = {
        "/data/wow/quest/11": (
            200,
            {
                "_links": {"self": {"href": "https://us.api.blizzard.com/data/wow/quest/11?namespace=static-1.60.1_70399-forever-us"}},
                "id": 11,
                "title": "Synthetic Bounty",
                "area": {"id": 12, "name": "Example Forest"},
                "description": "Collect synthetic tokens.",
                "requirements": {},
                "rewards": {
                    "experience": 850,
                    "items": {
                        "choice_of": [
                            {"item": {"id": 2249, "name": "Synthetic Buckler"}},
                            {"item": {"id": 2238, "name": "Synthetic Pants"}},
                        ]
                    },
                    "reputations": [{"reward": {"id": 72, "name": "Example City"}, "value": 100}],
                },
            },
        ),
        "/data/wow/quest/16": (
            200,
            {
                "id": 16,
                "title": "Synthetic Delivery",
                "area": {"id": 12, "name": "Example Forest"},
                "description": "Bring a drink.",
                "is_repeatable": True,
                "requirements": {},
                "rewards": {"items": {"items": [{"item": {"id": 4536, "name": "Synthetic Apple"}}]}},
            },
        ),
        "/data/wow/item/2249": (
            200,
            {
                "id": 2249,
                "name": "Synthetic Buckler",
                "quality": {"type": "UNCOMMON", "name": "Uncommon"},
                "level": 10,
                "required_level": 5,
                "inventory_type": {"name": "Off Hand"},
                "preview_item": {"armor": {"value": 120, "display": {"display_string": "120 Armor"}}},
            },
        ),
    }
    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)

    q11 = lookup_quest(client, 11, resolve_reward_items=True)
    assert q11["status"] == "ok"
    assert q11["quest"]["prerequisites_available"] is False
    assert q11["quest"]["rewards"]["experience"] == 850
    choice = q11["quest"]["rewards"]["choice_items"]
    assert choice[0]["bnet_status"] == "ok"
    assert "120 Armor" in choice[0]["summary"]
    assert choice[1]["bnet_status"] == "not_found"  # item 2238 404s cleanly

    brief = format_rewards_brief(q11["quest"])
    assert "850 XP" in brief
    assert "choose 1 of 2" in brief
    assert "+100 Example City" in brief

    q16 = lookup_quest(client, 16, resolve_reward_items=False)
    assert q16["quest"]["is_repeatable"] is True
    assert "repeatable" in format_rewards_brief(q16["quest"])

    q404 = lookup_quest(client, 999999)
    assert q404["status"] == "not_found"


def test_enrich_quest_report_text_and_chat_context(tmp_path):
    routes = {
        "/data/wow/quest/11": (
            200,
            {
                "id": 11,
                "title": "Synthetic Bounty",
                "area": {"id": 12, "name": "Example Forest"},
                "description": "Collect tokens.",
                "rewards": {"experience": 850, "reputations": [{"reward": {"id": 72, "name": "Example City"}, "value": 100}]},
            },
        ),
    }
    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)

    base = {
        "status": "ok",
        "age_seconds": 10,
        "player": {"level": 8, "class": "MAGE", "zone": "Example Forest", "subzone": None},
        "quest_count": 2,
        "plan": [
            {"step": 1, "action": "finish", "id": 11, "title": "Synthetic Bounty", "zone": "Example Forest", "remaining": ["0/8"], "notes": []},
            {"step": 2, "action": "finish", "id": 999, "title": "Unknown Quest", "zone": "Example Forest", "remaining": [], "notes": []},
        ],
        "warnings": [],
    }
    enriched = enrich_quest_report(base, client)
    assert enriched["bnet_summary"] == {"resolved": 1, "not_found": 1, "unavailable": 0}
    assert enriched["plan"][0]["bnet_rewards"]["experience"] == 850
    text = quests.as_text(enriched)
    assert "850 XP" in text
    assert ATTRIBUTION in text

    chat_ctx = enrich_quest_chat_context({"quest": {"id": 11, "title": "Synthetic Bounty"}}, client, resolve_reward_items=False)
    assert chat_ctx["bnet_quest"]["status"] == "ok"
    assert "prerequisites" in chat_ctx["bnet_quest"]["caveat"]
