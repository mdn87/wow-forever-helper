"""Synthetic offline tests for Slice 25: Forever AH and commodity price CLI."""

from __future__ import annotations

import json
import pytest

from wow_helper.bnet_api import ATTRIBUTION, ENV_CLIENT_ID, ENV_CLIENT_SECRET, TOKEN_URL, BnetClient, BnetConfigError, BnetNotFoundError
from wow_helper.bnet_market import as_text, list_houses, list_rulesets, price_summary

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


def test_list_rulesets_and_houses(tmp_path):
    routes = {
        "/data/wow/ruleset/index": (200, {"rulesets": [{"id": 1, "name": "PvP"}, {"id": 2, "name": "Normal"}]}),
        "/data/wow/ruleset/1/auctions/?": (
            200,
            {"auctions": [{"id": 110, "name": "Alliance Auction House"}, {"id": 113, "name": "Horde Auction House"}]},
        ),
    }
    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)
    rs = list_rulesets(client)
    assert rs["status"] == "ok"
    assert len(rs["rulesets"]) == 2
    assert ATTRIBUTION in as_text(rs)

    hs = list_houses(client, 1)
    assert hs["house_count"] == 2
    assert hs["houses"][0]["id"] == 110
    assert "Alliance Auction House" in as_text(hs)


def test_price_summary_commodities_auctions_and_zero_player_names(tmp_path):
    routes = {
        "/data/wow/item/2589": (200, {"id": 2589, "name": "Synthetic Cloth"}),
        "/data/wow/ruleset/1/auctions/110/commodities": (
            200,
            {
                "auctions": [
                    {"id": 1, "item": {"id": 2589}, "quantity": 10, "unit_price": 100, "time_left": "LONG"},
                    {"id": 2, "item": {"id": 2589}, "quantity": 20, "unit_price": 150, "time_left": "SHORT"},
                    {"id": 3, "item": {"id": 9999}, "quantity": 5, "unit_price": 99999, "time_left": "LONG"},
                ]
            },
        ),
        "/data/wow/ruleset/1/auctions/110?": (
            200,
            {
                "id": 110,
                "name": "Alliance Auction House",
                "auctions": [
                    {"id": 10, "item": {"id": 2589}, "quantity": 2, "buyout": 400, "time_left": "MEDIUM"},
                ],
            },
        ),
    }
    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)
    res = price_summary(client, ruleset_id=1, house_id=110, item_id=2589)

    assert res["status"] == "ok"
    assert res["item_name"] == "Synthetic Cloth"
    assert res["house_name"] == "Alliance Auction House"
    # 10 @ 100, 20 @ 150, 2 @ 200 -> 32 units total, min 100c (1s), weighted median 150c (1s 50c)
    assert res["summary"]["total_quantity"] == 32
    assert res["summary"]["listing_count"] == 3
    assert res["summary"]["min_unit_copper"] == 100
    assert res["summary"]["median_unit_copper"] == 150
    assert res["summary"]["min_unit_gold"] == "1s"
    assert res["summary"]["median_unit_gold"] == "1s 50c"
    assert res["commodities"]["total_quantity"] == 30
    assert res["auctions"]["total_quantity"] == 2
    text = as_text(res)
    assert "Synthetic Cloth (#2589)" in text
    assert ATTRIBUTION in text


def test_price_summary_by_query_and_404_item_name_fallback(tmp_path):
    routes = {
        "/data/wow/search/item": (
            200,
            {
                "results": [
                    {"data": {"id": 7026, "name": {"en_US": "Synthetic Belt"}}},
                    {"data": {"id": 2589, "name": {"en_US": "Synthetic Cloth"}}},
                ]
            },
        ),
        "/data/wow/ruleset/1/auctions/110/commodities": (
            200,
            {"auctions": [{"id": 1, "item": {"id": 2589}, "quantity": 4, "unit_price": 250, "time_left": "LONG"}]},
        ),
        "/data/wow/ruleset/1/auctions/110?": (200, {"id": 110, "name": "Alliance Auction House", "auctions": []}),
    }
    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)
    by_name = price_summary(client, ruleset_id=1, house_id=110, query="Synthetic Cloth")
    assert by_name["item_id"] == 2589
    assert by_name["item_name"] == "Synthetic Cloth"
    assert by_name["summary"]["min_unit_copper"] == 250

    # Unknown item ID (404 on /item/{id}) still summarizes listings cleanly
    routes_404 = {
        "/data/wow/ruleset/1/auctions/110/commodities": (
            200,
            {"auctions": [{"id": 9, "item": {"id": 17719}, "quantity": 1, "unit_price": 50000, "time_left": "LONG"}]},
        ),
        "/data/wow/ruleset/1/auctions/110?": (200, {"id": 110, "name": "Alliance Auction House", "auctions": []}),
    }
    client2 = BnetClient(cache_dir=tmp_path / "c2", env=FAKE_ENV, transport=_make_transport(routes_404), min_interval=0.0)
    fallback = price_summary(client2, ruleset_id=1, house_id=110, item_id=17719)
    assert fallback["item_name"] is None
    assert fallback["item_lookup_status"] == "not_found"
    assert fallback["summary"]["min_unit_gold"] == "5g"
    assert "Item 17719" in as_text(fallback)


def test_price_summary_validation_and_empty_search(tmp_path):
    routes = {"/data/wow/search/item": (200, {"results": []})}
    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)
    with pytest.raises(BnetConfigError):
        price_summary(client, ruleset_id=1, house_id=110)
    with pytest.raises(BnetConfigError):
        price_summary(client, ruleset_id=1, house_id=110, item_id=1, query="x")
    with pytest.raises(BnetNotFoundError):
        price_summary(client, ruleset_id=1, house_id=110, query="Missing Item")


def test_market_cli_cache_only_and_missing_house_refusal(tmp_path, monkeypatch, capsys):
    from wow_helper import __main__ as cli
    from wow_helper import bnet_api

    routes = {
        "/data/wow/item/2589": (200, {"id": 2589, "name": "Synthetic Cloth"}),
        "/data/wow/ruleset/1/auctions/110/commodities": (
            200,
            {"auctions": [{"id": 1, "item": {"id": 2589}, "quantity": 5, "unit_price": 300, "time_left": "LONG"}]},
        ),
        "/data/wow/ruleset/1/auctions/110?": (200, {"id": 110, "name": "Alliance Auction House", "auctions": []}),
    }
    seeded = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)
    price_summary(seeded, ruleset_id=1, house_id=110, item_id=2589)

    monkeypatch.setattr(bnet_api, "DEFAULT_CACHE_DIR", tmp_path)
    monkeypatch.delenv(ENV_CLIENT_ID, raising=False)
    monkeypatch.delenv(ENV_CLIENT_SECRET, raising=False)

    assert cli.main(["market", "--ruleset", "1", "--house", "110", "--item", "2589", "--cache-only", "--text"]) == 0
    out = capsys.readouterr().out
    assert "Synthetic Cloth (#2589)" in out
    assert "min 3s" in out
    assert ATTRIBUTION in out

    assert cli.main(["market", "--ruleset", "1", "--item", "2589"]) == 2
    err_json = json.loads(capsys.readouterr().out)
    assert err_json["status"] == "error"
    assert "--house" in err_json["message"]
