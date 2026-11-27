"""Synthetic offline tests for Slice 28: Forever ruleset status and reference catalogs."""

from __future__ import annotations

import json
import pytest

from wow_helper.bnet_api import ATTRIBUTION, ENV_CLIENT_ID, ENV_CLIENT_SECRET, TOKEN_URL, BnetClient, BnetConfigError
from wow_helper.bnet_catalogs import CATALOGS, as_text, fetch_catalog, ruleset_status, search_catalog

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


def test_ruleset_status_single_and_all(tmp_path):
    routes = {
        "/data/wow/ruleset/index": (200, {"rulesets": [{"id": 1, "name": "PvP"}, {"id": 2, "name": "Normal"}]}),
        "/data/wow/ruleset/1?": (200, {"id": 1, "name": "PvP", "status": {"type": "UP", "name": "Up"}}),
        "/data/wow/ruleset/2?": (200, {"id": 2, "name": "Normal", "status": {"type": "UP", "name": "Up"}}),
    }
    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)

    one = ruleset_status(client, 1)
    assert one["status"] == "ok"
    assert one["rulesets"][0]["status_type"] == "UP"
    assert "Ruleset 1 (PvP): Up" in as_text(one)
    assert ATTRIBUTION in as_text(one)

    all_rs = ruleset_status(client)
    assert len(all_rs["rulesets"]) == 2
    assert {r["id"] for r in all_rs["rulesets"]} == {1, 2}


def test_catalog_fetch_search_and_rejects_empty_journal_instance(tmp_path):
    routes = {
        "/data/wow/playable-race/index": (
            200,
            {
                "_links": {"self": {"href": "https://us.api.blizzard.com/data/wow/playable-race/?namespace=static-1.60.1_70399-forever-us"}},
                "races": [
                    {"id": 1, "name": "Human"},
                    {"id": 95, "name": "High Order Skyborne"},
                    {"id": 96, "name": "Windshaper Skyborne"},
                ],
            },
        ),
        "/data/wow/profession/index": (
            200,
            {"professions": [{"id": 197, "name": "Tailoring"}, {"id": 185, "name": "Cooking"}]},
        ),
    }
    client = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)

    assert "journal-instances" not in CATALOGS
    with pytest.raises(BnetConfigError):
        fetch_catalog(client, "journal-instances")

    races = fetch_catalog(client, "races")
    assert races["status"] == "ok"
    assert races["count"] == 3
    assert races["served_namespace"] == "static-1.60.1_70399-forever-us"

    sky = search_catalog(client, "races", "skyborne")
    assert sky["total_matches"] == 2
    assert all("Skyborne" in m["name"] for m in sky["matches"])
    assert "High Order Skyborne (95)" in as_text(sky)
    assert ATTRIBUTION in as_text(sky)

    # Second fetch is served from local runtime cache
    profs = fetch_catalog(client, "professions")
    assert profs["from_cache"] is False
    profs_cached = fetch_catalog(client, "professions", cache_only=True)
    assert profs_cached["from_cache"] is True
    assert profs_cached["count"] == 2


def test_catalog_cli_ruleset_and_search(tmp_path, monkeypatch, capsys):
    from wow_helper import __main__ as cli
    from wow_helper import bnet_api

    routes = {
        "/data/wow/ruleset/1?": (200, {"id": 1, "name": "PvP", "status": {"type": "UP", "name": "Up"}}),
        "/data/wow/playable-race/index": (
            200,
            {"races": [{"id": 95, "name": "High Order Skyborne"}, {"id": 1, "name": "Human"}]},
        ),
    }
    seeded = BnetClient(cache_dir=tmp_path, env=FAKE_ENV, transport=_make_transport(routes), min_interval=0.0)
    ruleset_status(seeded, 1)
    fetch_catalog(seeded, "races")

    monkeypatch.setattr(bnet_api, "DEFAULT_CACHE_DIR", tmp_path)
    monkeypatch.delenv(ENV_CLIENT_ID, raising=False)
    monkeypatch.delenv(ENV_CLIENT_SECRET, raising=False)

    assert cli.main(["catalog", "ruleset", "--ruleset", "1", "--cache-only", "--text"]) == 0
    assert "Ruleset 1 (PvP): Up" in capsys.readouterr().out

    assert cli.main(["catalog", "list", "races", "--query", "skyborne", "--cache-only", "--text"]) == 0
    out = capsys.readouterr().out
    assert "High Order Skyborne (95)" in out
    assert ATTRIBUTION in out
