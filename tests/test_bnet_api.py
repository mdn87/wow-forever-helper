"""Synthetic offline tests for the Battle.net Forever API client and TTL cache."""

from __future__ import annotations

import base64
import json
import pytest

from wow_helper.bnet_api import (
    ATTRIBUTION,
    ENV_CLIENT_ID,
    ENV_CLIENT_SECRET,
    MAX_NOT_FOUND_TTL_SECONDS,
    MAX_TTL_SECONDS,
    TOKEN_URL,
    BnetApiError,
    BnetAuthError,
    BnetCache,
    BnetClient,
    BnetConfigError,
    BnetNetworkError,
    BnetNotFoundError,
    BnetRateLimitError,
    BnetServerError,
    dynamic_namespace,
    static_namespace,
)

FAKE_ID = "synthetic-client-id-0000"
FAKE_SECRET = "synthetic-client-secret-9999"
FAKE_TOKEN = "synthetic-bearer-token-value"


class FakeClock:
    def __init__(self, wall: float = 1_800_000_000.0, mono: float = 1000.0):
        self.wall = wall
        self.mono = mono
        self.slept: list[float] = []

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.mono += seconds
        self.wall += seconds

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.mono += seconds


def _token_bytes(token: str = FAKE_TOKEN, expires_in: int = 86399) -> bytes:
    return json.dumps({"access_token": token, "token_type": "bearer", "expires_in": expires_in}).encode("utf-8")


def _synthetic_item_bytes(item_id: int = 2589) -> bytes:
    return json.dumps(
        {
            "_links": {
                "self": {
                    "href": f"https://us.api.blizzard.com/data/wow/item/{item_id}?namespace=static-1.60.1_70399-forever-us"
                }
            },
            "id": item_id,
            "name": "Synthetic Cloth",
            "level": 5,
        }
    ).encode("utf-8")


def test_missing_credentials_raises_without_leaking_values(tmp_path):
    client = BnetClient(cache_dir=tmp_path, env={ENV_CLIENT_ID: FAKE_ID})
    with pytest.raises(BnetConfigError) as exc_info:
        client.get_json("/data/wow/item/2589")
    assert FAKE_ID not in str(exc_info.value)
    assert ENV_CLIENT_ID in str(exc_info.value)
    assert ENV_CLIENT_SECRET in str(exc_info.value)


def test_validation_rejects_profile_paths_and_bad_regions_or_namespaces(tmp_path):
    client = BnetClient(cache_dir=tmp_path, env={})
    with pytest.raises(BnetConfigError):
        BnetClient(region="invalid", cache_dir=tmp_path, env={})
    with pytest.raises(BnetConfigError):
        BnetClient(locale="en-US", cache_dir=tmp_path, env={})
    for bad_path in (
        "/profile/wow/character/test-char",
        "/oauth/token",
        "/data/wow/item/2589?foo=bar",
        "/data/wow/../profile/wow/character/test",
        "/data/wow//item/2589",
    ):
        with pytest.raises(BnetConfigError):
            client.get_json(bad_path)
    with pytest.raises(BnetConfigError):
        client.get_json("/data/wow/item/2589", namespace="profile-forever-us")
    with pytest.raises(BnetConfigError):
        client.get_json("/data/wow/item/2589", namespace="static-forever-eu")
    with pytest.raises(BnetConfigError):
        client.get_json("/data/wow/item/2589", params={"access_token": "nope"})


def test_token_fetch_reuse_refresh_and_no_secret_leakage(tmp_path):
    clock = FakeClock()
    calls = []

    def transport(method, url, headers, body, timeout, max_bytes):
        calls.append((method, url, dict(headers), body))
        if url == TOKEN_URL:
            expected_basic = base64.b64encode(f"{FAKE_ID}:{FAKE_SECRET}".encode("utf-8")).decode("ascii")
            assert headers["Authorization"] == f"Basic {expected_basic}"
            assert body == b"grant_type=client_credentials"
            return 200, _token_bytes(token=f"{FAKE_TOKEN}-{len(calls)}", expires_in=300)
        return 200, _synthetic_item_bytes(2589)

    client = BnetClient(
        cache_dir=tmp_path,
        env={ENV_CLIENT_ID: FAKE_ID, ENV_CLIENT_SECRET: FAKE_SECRET},
        transport=transport,
        clock=clock.time,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    resp1 = client.get_json("/data/wow/item/2589", ttl_seconds=600)
    assert resp1 is not None
    assert resp1.from_cache is False
    assert resp1.served_namespace == "static-1.60.1_70399-forever-us"
    assert resp1.attribution == ATTRIBUTION
    assert resp1.payload["name"] == "Synthetic Cloth"
    assert len(calls) == 2  # 1 token + 1 API GET

    # Second item reuses in-memory token without fetching another token
    resp2 = client.get_json("/data/wow/item/25", ttl_seconds=600)
    assert resp2 is not None and resp2.from_cache is False
    assert len(calls) == 3

    # Advance past token lifetime minus 60s safety margin -> refreshes token
    clock.advance(250)
    resp3 = client.get_json("/data/wow/item/6948", ttl_seconds=600)
    assert resp3 is not None and resp3.from_cache is False
    assert len(calls) == 5  # new token + new GET

    # Confirm credentials and bearer tokens never appear in repr or any cache file
    assert FAKE_ID not in repr(client)
    assert FAKE_SECRET not in repr(client)
    assert FAKE_TOKEN not in repr(client)
    cache_files = list(tmp_path.glob("*.json"))
    assert len(cache_files) == 3
    for cf in cache_files:
        text = cf.read_text(encoding="utf-8")
        assert FAKE_ID not in text
        assert FAKE_SECRET not in text
        assert FAKE_TOKEN not in text


def test_token_401_reports_lengths_only_without_secrets(tmp_path):
    def transport(method, url, headers, body, timeout, max_bytes):
        return 401, b'{"error":"unauthorized"}'

    client = BnetClient(
        cache_dir=tmp_path,
        env={ENV_CLIENT_ID: FAKE_ID, ENV_CLIENT_SECRET: FAKE_SECRET},
        transport=transport,
    )
    with pytest.raises(BnetAuthError) as exc_info:
        client.get_json("/data/wow/item/2589")
    msg = str(exc_info.value)
    assert "401" in msg
    assert str(len(FAKE_ID)) in msg
    assert str(len(FAKE_SECRET)) in msg
    assert FAKE_ID not in msg
    assert FAKE_SECRET not in msg


def test_cache_hit_requires_no_credentials_or_network(tmp_path):
    clock = FakeClock()
    calls = 0

    def transport(method, url, headers, body, timeout, max_bytes):
        nonlocal calls
        calls += 1
        if url == TOKEN_URL:
            return 200, _token_bytes()
        return 200, _synthetic_item_bytes(2589)

    writer = BnetClient(
        cache_dir=tmp_path,
        env={ENV_CLIENT_ID: FAKE_ID, ENV_CLIENT_SECRET: FAKE_SECRET},
        transport=transport,
        clock=clock.time,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    first = writer.get_json("/data/wow/item/2589", ttl_seconds=3600)
    assert first is not None and first.from_cache is False
    assert calls == 2

    # Separate client with empty env and a failing transport still gets the cached response
    def fail_transport(*args, **kwargs):
        raise AssertionError("Transport must not be called on a fresh cache hit")

    clock.advance(45)
    reader = BnetClient(cache_dir=tmp_path, env={}, transport=fail_transport, clock=clock.time)
    second = reader.get_json("/data/wow/item/2589", ttl_seconds=3600)
    assert second is not None
    assert second.from_cache is True
    assert second.age_seconds(clock.time()) == 45
    assert second.payload["id"] == 2589
    assert second.served_namespace == "static-1.60.1_70399-forever-us"

    # cache_only returns None on miss without hitting transport
    assert reader.get_json("/data/wow/item/9999", cache_only=True) is None


def test_strict_30_day_ttl_ceiling_and_tampered_file_eviction(tmp_path):
    clock = FakeClock()
    cache = BnetCache(tmp_path, clock=clock.time)

    with pytest.raises(ValueError):
        cache.put(
            region="us",
            namespace=static_namespace("us"),
            locale="en_US",
            path="/data/wow/item/2589",
            ttl_seconds=MAX_TTL_SECONDS + 1,
            payload={"id": 2589},
        )
    with pytest.raises(ValueError):
        cache.put(
            region="us",
            namespace=static_namespace("us"),
            locale="en_US",
            path="/data/wow/item/2589",
            ttl_seconds=0,
            payload={"id": 2589},
        )

    cache.put(
        region="us",
        namespace=static_namespace("us"),
        locale="en_US",
        path="/data/wow/item/2589",
        ttl_seconds=MAX_TTL_SECONDS,
        payload={"id": 2589},
    )
    cache_files = list(tmp_path.glob("*.json"))
    assert len(cache_files) == 1

    # Hand-tamper expires_at far into the future; cache must still evict once 30 days pass
    tampered = json.loads(cache_files[0].read_text(encoding="utf-8"))
    tampered["expires_at"] = tampered["fetched_at"] + (90 * 24 * 60 * 60)
    cache_files[0].write_text(json.dumps(tampered), encoding="utf-8")

    clock.advance(MAX_TTL_SECONDS - 10)
    assert cache.get(region="us", namespace=static_namespace("us"), locale="en_US", path="/data/wow/item/2589") is not None

    clock.advance(11)
    assert cache.get(region="us", namespace=static_namespace("us"), locale="en_US", path="/data/wow/item/2589") is None
    assert not cache_files[0].exists()  # evicted on read


def test_purge_expired_and_clear(tmp_path):
    clock = FakeClock()
    cache = BnetCache(tmp_path, clock=clock.time)
    cache.put(region="us", namespace=static_namespace("us"), locale="en_US", path="/data/wow/item/1", ttl_seconds=60, payload={"id": 1})
    cache.put(region="us", namespace=static_namespace("us"), locale="en_US", path="/data/wow/item/2", ttl_seconds=600, payload={"id": 2})
    (tmp_path / "corrupt.json").write_text("{not-json", encoding="utf-8")

    clock.advance(120)
    assert cache.purge_expired() == 2  # expired item/1 + corrupt.json
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert cache.clear() == 1
    assert list(tmp_path.glob("*.json")) == []


def test_404_handling_and_optional_negative_cache(tmp_path):
    clock = FakeClock()
    get_calls = 0

    def transport(method, url, headers, body, timeout, max_bytes):
        nonlocal get_calls
        if url == TOKEN_URL:
            return 200, _token_bytes()
        get_calls += 1
        return 404, b'{"code":404,"type":"BLZWEBAPI00000404","detail":"Not Found"}'

    client = BnetClient(
        cache_dir=tmp_path,
        env={ENV_CLIENT_ID: FAKE_ID, ENV_CLIENT_SECRET: FAKE_SECRET},
        transport=transport,
        clock=clock.time,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    with pytest.raises(ValueError):
        client.get_json("/data/wow/item/17719", not_found_ttl=MAX_NOT_FOUND_TTL_SECONDS + 1)

    with pytest.raises(BnetNotFoundError) as exc1:
        client.get_json("/data/wow/item/17719", not_found_ttl=300)
    assert exc1.value.from_cache is False
    assert get_calls == 1

    # Second call within negative TTL raises cached 404 without hitting network
    with pytest.raises(BnetNotFoundError) as exc2:
        client.get_json("/data/wow/item/17719", not_found_ttl=300)
    assert exc2.value.from_cache is True
    assert get_calls == 1

    # After expiry, re-queries live API
    clock.advance(301)
    with pytest.raises(BnetNotFoundError) as exc3:
        client.get_json("/data/wow/item/17719", not_found_ttl=300)
    assert exc3.value.from_cache is False
    assert get_calls == 2


def test_429_rate_limit_and_5xx_circuit_breaker(tmp_path):
    clock = FakeClock()
    responses = [
        (429, b'{"code":429}'),
        (503, b'{"code":503}'),
        (502, b'{"code":502}'),
    ]
    api_calls = 0

    def transport(method, url, headers, body, timeout, max_bytes):
        nonlocal api_calls
        if url == TOKEN_URL:
            return 200, _token_bytes()
        api_calls += 1
        return responses.pop(0)

    client = BnetClient(
        cache_dir=tmp_path,
        env={ENV_CLIENT_ID: FAKE_ID, ENV_CLIENT_SECRET: FAKE_SECRET},
        transport=transport,
        clock=clock.time,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        min_interval=0.2,
    )

    with pytest.raises(BnetRateLimitError):
        client.get_json("/data/wow/item/1")
    assert api_calls == 1

    with pytest.raises(BnetServerError):
        client.get_json("/data/wow/item/2")
    with pytest.raises(BnetServerError):
        client.get_json("/data/wow/item/3")
    assert api_calls == 3

    # Circuit breaker now stops further outbound requests before calling transport
    with pytest.raises(BnetServerError):
        client.get_json("/data/wow/item/4")
    assert api_calls == 3


def test_rate_pacing_and_hourly_quota_cap(tmp_path):
    clock = FakeClock()

    def transport(method, url, headers, body, timeout, max_bytes):
        if url == TOKEN_URL:
            return 200, _token_bytes()
        return 200, _synthetic_item_bytes(2589)

    client = BnetClient(
        cache_dir=tmp_path,
        env={ENV_CLIENT_ID: FAKE_ID, ENV_CLIENT_SECRET: FAKE_SECRET},
        transport=transport,
        clock=clock.time,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        min_interval=0.25,
        max_requests_per_hour=2,
    )

    client.get_json("/data/wow/ruleset/1", namespace=dynamic_namespace("us"))
    client.get_json("/data/wow/ruleset/2", namespace=dynamic_namespace("us"))
    assert clock.slept == [pytest.approx(0.25)]

    with pytest.raises(BnetRateLimitError):
        client.get_json("/data/wow/ruleset/3", namespace=dynamic_namespace("us"))

    # Advancing one hour clears the sliding window
    clock.advance(3601)
    resp = client.get_json("/data/wow/ruleset/3", namespace=dynamic_namespace("us"))
    assert resp is not None and resp.from_cache is False


def test_malformed_json_and_unexpected_status(tmp_path):
    statuses = [(200, b"{not-json"), (418, b"{}")]

    def transport(method, url, headers, body, timeout, max_bytes):
        if url == TOKEN_URL:
            return 200, _token_bytes()
        return statuses.pop(0)

    client = BnetClient(
        cache_dir=tmp_path,
        env={ENV_CLIENT_ID: FAKE_ID, ENV_CLIENT_SECRET: FAKE_SECRET},
        transport=transport,
        min_interval=0.0,
    )

    with pytest.raises(BnetNetworkError):
        client.get_json("/data/wow/item/1")
    with pytest.raises(BnetApiError):
        client.get_json("/data/wow/item/2")


def test_force_refresh_api_401_clears_token_and_params_separate_cache(tmp_path):
    clock = FakeClock()
    token_calls = 0
    api_calls = 0
    fail_once_401 = True

    def transport(method, url, headers, body, timeout, max_bytes):
        nonlocal token_calls, api_calls, fail_once_401
        if url == TOKEN_URL:
            token_calls += 1
            return 200, _token_bytes(token=f"{FAKE_TOKEN}-{token_calls}")
        api_calls += 1
        if fail_once_401:
            fail_once_401 = False
            return 401, b'{"code":401}'
        if "Linen" in url:
            return 200, json.dumps({"results": [{"id": 2589, "tag": api_calls}]}).encode("utf-8")
        return 200, json.dumps({"results": [{"id": 2592, "tag": api_calls}]}).encode("utf-8")

    client = BnetClient(
        cache_dir=tmp_path,
        env={ENV_CLIENT_ID: FAKE_ID, ENV_CLIENT_SECRET: FAKE_SECRET},
        transport=transport,
        clock=clock.time,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        min_interval=0.0,
    )

    with pytest.raises(BnetAuthError):
        client.get_json("/data/wow/search/item", params={"name.en_US": "Linen"})
    assert token_calls == 1

    # Next call must fetch a fresh token because API 401 cleared the cached token
    r_linen = client.get_json("/data/wow/search/item", params={"name.en_US": "Linen"}, ttl_seconds=600)
    assert token_calls == 2
    assert r_linen is not None and r_linen.from_cache is False
    assert r_linen.payload["results"][0]["id"] == 2589

    # Different query params use a distinct cache key
    r_wool = client.get_json("/data/wow/search/item", params={"name.en_US": "Wool"}, ttl_seconds=600)
    assert r_wool is not None and r_wool.from_cache is False
    assert r_wool.payload["results"][0]["id"] == 2592

    # force_refresh bypasses the valid cache entry and refreshes it
    r_linen_fresh = client.get_json(
        "/data/wow/search/item",
        params={"name.en_US": "Linen"},
        ttl_seconds=600,
        force_refresh=True,
    )
    assert r_linen_fresh is not None and r_linen_fresh.from_cache is False
    assert r_linen_fresh.payload["results"][0]["tag"] > r_linen.payload["results"][0]["tag"]
