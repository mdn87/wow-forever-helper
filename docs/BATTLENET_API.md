# Battle.net Forever API integration

Status: Slices 24–29 are implemented and verified with synthetic offline tests plus live non-character API smoke checks on 2026-11-27. Slice 30 (`bnet-live-verification-closeout`) remains open only for the in-game player-to-house mapping check and live spoken voice verification.

## Architecture and boundaries

All Battle.net calls flow through `wow_helper/bnet_api.py` (standard library only, read-only):

- **Bring-your-own credentials:** Reads `WFH_BNET_CLIENT_ID` and `WFH_BNET_CLIENT_SECRET` from process environment variables using OAuth `client_credentials` (`POST https://oauth.battle.net/token`). Never bundles credentials, never saves tokens or secrets to disk, and never prints them in logs or exceptions.
- **Game Data only, no listener:** Restricts requests to `/data/wow/` under `static-forever-<region>` and `dynamic-forever-<region>`. Character, guild, and account profile endpoints remain out of scope; no OAuth authorization-code login or local HTTP listener is opened.
- **30-day TTL ceiling:** Cached responses live under ignored `.runtime/bnet-cache/` with atomic writes. Both write and read paths enforce a hard 30-day maximum lifetime from `fetched_at`, automatically deleting expired or tampered entries on read and via `purge_expired()` / `clear()`.
- **Attribution and rate limits:** Every response carries Blizzard attribution (`ATTRIBUTION`). Outbound calls enforce inter-request pacing (`0.2s`), a sliding hourly quota (`36,000/hr`), immediate stop on HTTP 429, and a consecutive HTTP 5xx circuit breaker (default 2).

## Implemented modules and CLI

- **Client & TTL cache (`wow_helper/bnet_api.py`):** OAuth token management, path/namespace validation, 30-day TTL cache, negative 404 caching, and typed errors.
- **Forever AH & commodity prices (`wow_helper/bnet_market.py`, `python -m wow_helper market`):** Lists rulesets (`--list-rulesets`) and 15 auction houses per ruleset (`--ruleset 1 --list-houses`), and summarizes min buyout/unit price, quantity-weighted median, and supply depth (`--ruleset 1 --house 110 --item 2589` or `--query "..."`, plus `--cache-only` and `--text`). Reads numeric/enum fields only; zero player names.
- **Item metadata enrichment (`wow_helper/bnet_items.py`, `character --enrich-bnet`, `task_window.py`):** Resolves item names, weapon damage/DPS, stats, on-use/proc text, and vendor sell price with clean fallback when `/data/wow/item/{id}` returns HTTP 404.
- **Quest rewards enrichment (`wow_helper/bnet_quests.py`, `quests --enrich-bnet`):** Attaches reward XP, choice/fixed reward items, reputation gains, and repeatability to quest plans and Quest chat context. Blizzard's quest API does not include prerequisites or objective locations; `wow_helper/quest_chain.py` remains authoritative for chains.
- **Forever ruleset status & static catalogs (`wow_helper/bnet_catalogs.py`, `python -m wow_helper catalog`):** Checks ruleset `UP` status (`catalog ruleset`) and lists/searches 10 verified Forever static catalogs (`races`, `specs`, `professions`, `item-classes`, `achievements`, `mounts`, `pets`, `creature-families`, `quest-areas`, `quest-categories`). Excludes empty `journal-instance/index`.
- **Hands-free voice lookups (`wow_helper/bnet_voice.py`, `voice_commands.py`, `handsfree.py`):** Routes spoken `"price check …"` / `"how much is … on the auction house"` and `"item stats for …"` turns to cached lookups on a worker thread with Blizzard attribution, falling back to Classic Wowhead in the voice browser when an item 404s or credentials are absent. Spell lookups (`"look up frostbolt"`) continue directly to the voice browser because `/data/wow/spell/{id}` returns HTTP 404 on Forever.

## Verification

- **Synthetic offline tests:** `tests/test_bnet_api.py`, `tests/test_bnet_market.py`, `tests/test_bnet_items.py`, `tests/test_bnet_quests.py`, `tests/test_bnet_catalogs.py`, `tests/test_bnet_voice.py`, `tests/test_handsfree.py`, `tests/test_cli.py`, and `tests/test_no_input.py`.
- **Live non-character API smoke check (2026-11-27, US region):** Verified live HTTP 200 responses and caching for `market` (item 2589 on ruleset 1, house 110: 19,155 units across 275 listings), `bnet_items.lookup_item` (200 on item 19019 and graceful `not_found` fallback on item 17719), `bnet_quests.lookup_quest` (quest 11 rewards), `bnet_catalogs` (ruleset 1 `Up`, Forever Skyborne races), `bnet_voice.BnetVoiceLookup` (cached market + item answers), and zero-credential `python -m wow_helper market --cache-only --text`.
- **Remaining unverified (Slice 30):** Confirming in game which of the 15 auction houses per ruleset corresponds to the player's character, and verifying live spoken voice turns through the installed Lugos Voice listener.
