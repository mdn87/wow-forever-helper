# Battle.net Forever API client

Status: Slice 24 (`bnet-api-client-cache`) is implemented and covered by synthetic offline unit tests. Feature slices (AH market CLI, item/quest/catalog enrichment, hands-free lookups, and live verification closeout) remain planned on `.dias/chips.json`.

## Purpose and boundaries

`wow_helper/bnet_api.py` provides a read-only, standard-library Battle.net Game Data API client and local runtime cache for World of Warcraft: Forever (`static-forever-<region>` and `dynamic-forever-<region>`).

- **Bring-your-own credentials:** Reads `WFH_BNET_CLIENT_ID` and `WFH_BNET_CLIENT_SECRET` from process environment variables using the OAuth `client_credentials` grant (`POST https://oauth.battle.net/token`). Never bundles credentials, never saves tokens or secrets to disk, and never prints them in logs or exceptions.
- **No user login or listener:** Uses client credentials only; opens no local HTTP callback listener and restricts requests to `/data/wow/` Game Data endpoints (character, guild, and account profile endpoints are refused).
- **30-day TTL ceiling:** Cached responses live under ignored `.runtime/bnet-cache/` with atomic writes. Both write and read paths enforce a hard 30-day maximum lifetime from `fetched_at`, automatically removing expired entries on read and via `purge_expired()` / `clear()`.
- **Attribution and rate limits:** Every `BnetResponse` carries Blizzard attribution (`ATTRIBUTION`). Outbound requests enforce minimum inter-request pacing, a sliding hourly budget (default 36,000/hour), immediate stop on HTTP 429, and a consecutive HTTP 5xx circuit breaker (default 2).
- **404 handling:** Raises `BnetNotFoundError` cleanly so callers can fall back when Forever static endpoints omit items or spells, with optional short negative caching (capped at 24 hours).

## Planned slices

Tracked in `.dias/chips.json` (sequences 24–30):

1. `bnet-api-client-cache` — OAuth client and strict 30-day TTL runtime cache (implemented).
2. `bnet-forever-market-cli` — Read-only Forever AH and commodity price CLI.
3. `bnet-item-enrichment` — Character status and upgrade-guide item metadata with 404 fallback.
4. `bnet-quest-rewards-enrichment` — Quest reward items, XP, reputation, and repeatability.
5. `bnet-forever-catalogs-status` — Forever ruleset status and static reference catalogs.
6. `bnet-handsfree-item-market-lookup` — Hands-free voice item and AH lookups with voice-browser fallback.
7. `bnet-live-verification-closeout` — Live Forever verification and 15-house auction mapping check.

## Verification

- **Synthetic unit tests (`tests/test_bnet_api.py`):** Cover credential absence and 401 redaction, path/region/namespace validation, token reuse and expiry refresh, zero-network cache hits, 30-day TTL ceiling and tampered-entry eviction, `purge_expired`/`clear`, 404 and negative caching, 429 and consecutive-5xx circuit breaking, pacing and hourly quota enforcement, and malformed responses.
- **Not yet verified live:** Live end-to-end execution of `wow_helper/bnet_api.py` against `us.api.blizzard.com` is deferred to Slice 30 (`bnet-live-verification-closeout`).
