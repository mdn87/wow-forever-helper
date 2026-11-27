"""Synthetic offline tests for Slice 26: Forever item metadata enrichment."""

from __future__ import annotations

import json

from wow_helper.bnet_api import ATTRIBUTION, ENV_CLIENT_ID, ENV_CLIENT_SECRET, TOKEN_URL, BnetClient
from wow_helper.bnet_items import (
    enrich_character_report,
    enrich_gear_context,
    format_item_summary,
    lookup_item,
    search_items,
)
from wow_helper.task_window import TaskWindow

FAKE_ENV = {ENV_CLIENT_ID: "synthetic-id", ENV_CLIENT_SECRET: "synthetic-secret"}


def _synthetic_weapon_payload(item_id: int = 19019) -> dict:
    return {
        "_links": {"self": {"href": f"https://us.api.blizzard.com/data/wow/item/{item_id}?namespace=static-1.60.1_70399-forever-us"}},
        "id": item_id,
        "name": "Synthetic Stormblade",
        "quality": {"type": "LEGENDARY", "name": "Legendary"},
        "level": 80,
        "required_level": 60,
        "item_class": {"name": "Weapon"},
        "item_subclass": {"name": "Sword"},
        "inventory_type": {"name": "One-Hand"},
        "is_equippable": True,
        "sell_price": 255355,
        "purchase_price": 1276777,
        "preview_item": {
            "binding": {"name": "Binds when picked up"},
            "weapon": {
                "damage": {"min_value": 44, "max_value": 115, "display_string": "44 - 115 Damage"},
                "attack_speed": {"display_string": "Speed 1.90"},
                "dps": {"value": 41.84, "display_string": "(41.8 damage per second)"},
            },
            "stats": [
                {"type": {"type": "AGILITY", "name": "Agility"}, "value": 5, "display": {"display_string": "+5 Agility"}},
                {"type": {"type": "STAMINA", "name": "Stamina"}, "value": 8, "display": {"display_string": "+8 Stamina"}},
            ],
            "spells": [
                {"spell": {"id": 21992, "name": "Synthetic Proc"}, "description": "Chance on hit: Deals 300 Nature damage."}
            ],
        },
    }


def _make_transport(routes: dict[str, tuple[int, dict]]):
    def transport(method, url, headers, body, timeout, max_bytes):
        if url == TOKEN_URL:
            return 200, json.dumps({"access_token": "tok", "expires_in": 3600}).encode("utf-8")
        for prefix, (status, payload) in routes.items():
            if prefix in url:
                return status, json.dumps(payload).encode("utf-8")
        return 404, b'{"code":404}'
    return transport


def test_lookup_item_parses_weapon_stats_spells_and_handles_404(tmp_path):
    routes = {"/data/wow/item/19019": (200, _synthetic_weapon_payload(19019))}
    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)

    found = lookup_item(client, 19019)
    assert found["status"] == "ok"
    assert found["served_namespace"] == "static-1.60.1_70399-forever-us"
    item = found["item"]
    assert item["name"] == "Synthetic Stormblade"
    assert item["weapon"]["dps"] == 41.84
    assert len(item["stats"]) == 2
    assert item["spells"][0]["id"] == 21992
    summary = format_item_summary(item)
    assert "Synthetic Stormblade (Legendary, ilvl 80, req 60, One-Hand)" in summary
    assert "+5 Agility" in summary
    assert "300 Nature damage" in summary

    missing = lookup_item(client, 17719)
    assert missing["status"] == "not_found"
    assert missing["id"] == 17719
    assert missing["from_cache"] is False

    # Second call uses negative cache cleanly
    missing_again = lookup_item(client, 17719)
    assert missing_again["status"] == "not_found"
    assert missing_again["from_cache"] is True


def test_enrich_character_report_and_guidance_context_with_mixed_404(tmp_path):
    routes = {"/data/wow/item/19019": (200, _synthetic_weapon_payload(19019))}
    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)

    base_report = {
        "status": "ok",
        "gear": [
            {"slot": "main hand", "slot_id": 16, "id": 19019, "ilvl": 80, "durability_percent": 90},
            {"slot": "head", "slot_id": 1, "id": 17719, "ilvl": 45, "durability_percent": 20},
        ],
    }
    enriched = enrich_character_report(base_report, client)
    assert base_report["gear"][0].get("name") is None  # non-mutating
    assert enriched["gear"][0]["name"] == "Synthetic Stormblade"
    assert enriched["gear"][0]["bnet_status"] == "ok"
    assert enriched["gear"][1]["bnet_status"] == "not_found"
    assert enriched["bnet_summary"] == {"resolved": 1, "not_found": 1, "unavailable": 0}
    assert enriched["bnet_attribution"] == ATTRIBUTION

    ctx = enrich_gear_context({"gear": base_report["gear"]}, client)
    assert ctx["bnet_summary"]["not_found"] == 1
    assert any("HTTP 404" in note for note in ctx["bnet_notes"])

    # Missing credentials degrades to unavailable instead of raising
    no_cred_client = BnetClient(cache_dir=tmp_path / "empty", env={}, min_interval=0.0)
    degraded = enrich_character_report(base_report, no_cred_client)
    assert degraded["bnet_summary"] == {"resolved": 0, "not_found": 0, "unavailable": 2}


def test_equipment_table_displays_enriched_names_and_preserves_plain_layout():
    plain_gear = [{"slot": "main hand", "id": 19019, "ilvl": 80, "durability_percent": 90}]
    plain_table = TaskWindow._format_equipment_table(plain_gear)
    assert "Item ID" in plain_table
    assert "19019" in plain_table

    named_gear = [
        {"slot": "main hand", "id": 19019, "name": "Synthetic Stormblade", "ilvl": 80, "durability_percent": 90},
        {"slot": "head", "id": 17719, "ilvl": 45, "durability_percent": 20},
    ]
    named_table = TaskWindow._format_equipment_table(named_gear)
    assert "Synthetic Stormblade" in named_table
    assert "17719" in named_table
    assert "[LOW]" in named_table


def test_search_items_returns_matches(tmp_path):
    routes = {
        "/data/wow/search/item": (
            200,
            {"results": [{"data": {"id": 2589, "name": {"en_US": "Synthetic Cloth"}, "level": 5, "required_level": 0}}]},
        )
    }
    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)
    res = search_items(client, "Synthetic")
    assert res["status"] == "ok"
    assert res["results"][0]["id"] == 2589
    assert res["results"][0]["name"] == "Synthetic Cloth"
