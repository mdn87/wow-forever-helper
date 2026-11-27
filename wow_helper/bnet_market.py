"""Read-only Forever Auction House and commodity price lookup via Battle.net API.

Reads only numeric and enum listing fields (item.id, unit_price, buyout, bid,
quantity, time_left). Never inspects, stores, or outputs player names.
"""

from __future__ import annotations

from .bnet_api import (
    ATTRIBUTION,
    BnetClient,
    BnetConfigError,
    BnetNotFoundError,
    dynamic_namespace,
    static_namespace,
)
from .character import gold

DEFAULT_RULESET_ID = 1
DEFAULT_MARKET_TTL = 900  # 15 minutes
DEFAULT_INDEX_TTL = 3600  # 1 hour
DEFAULT_ITEM_TTL = 7 * 24 * 3600  # 7 days (well under 30-day ceiling)


def _positive_int(value: int | str, label: str) -> int:
    if isinstance(value, bool):
        raise BnetConfigError(f"{label} must be a positive integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise BnetConfigError(f"{label} must be a positive integer.") from None
    if parsed <= 0:
        raise BnetConfigError(f"{label} must be a positive integer.")
    return parsed


def list_rulesets(
    client: BnetClient,
    *,
    ttl_seconds: int = DEFAULT_INDEX_TTL,
    cache_only: bool = False,
    force_refresh: bool = False,
) -> dict:
    resp = client.get_json(
        "/data/wow/ruleset/index",
        namespace=dynamic_namespace(client.region),
        ttl_seconds=ttl_seconds,
        cache_only=cache_only,
        force_refresh=force_refresh,
    )
    if resp is None:
        return {"status": "cache_miss", "rulesets": [], "attribution": ATTRIBUTION}
    raw_rulesets = resp.payload.get("rulesets") if isinstance(resp.payload, dict) else []
    rulesets = [
        {"id": int(r["id"]), "name": str(r.get("name") or "")}
        for r in (raw_rulesets or [])
        if isinstance(r, dict) and isinstance(r.get("id"), int)
    ]
    return {
        "status": "ok",
        "region": client.region,
        "rulesets": rulesets,
        "from_cache": resp.from_cache,
        "age_seconds": resp.age_seconds(),
        "attribution": resp.attribution,
    }


def list_houses(
    client: BnetClient,
    ruleset_id: int = DEFAULT_RULESET_ID,
    *,
    ttl_seconds: int = DEFAULT_INDEX_TTL,
    cache_only: bool = False,
    force_refresh: bool = False,
) -> dict:
    rid = _positive_int(ruleset_id, "ruleset_id")
    # Trailing slash is required by Blizzard's Forever auctions index route.
    resp = client.get_json(
        f"/data/wow/ruleset/{rid}/auctions/",
        namespace=dynamic_namespace(client.region),
        ttl_seconds=ttl_seconds,
        cache_only=cache_only,
        force_refresh=force_refresh,
    )
    if resp is None:
        return {"status": "cache_miss", "ruleset_id": rid, "houses": [], "attribution": ATTRIBUTION}
    raw_houses = resp.payload.get("auctions") if isinstance(resp.payload, dict) else []
    houses = [
        {"id": int(h["id"]), "name": str(h.get("name") or "")}
        for h in (raw_houses or [])
        if isinstance(h, dict) and isinstance(h.get("id"), int)
    ]
    return {
        "status": "ok",
        "region": client.region,
        "ruleset_id": rid,
        "house_count": len(houses),
        "houses": houses,
        "from_cache": resp.from_cache,
        "age_seconds": resp.age_seconds(),
        "attribution": resp.attribution,
    }


def _extract_search_name(data: dict, locale: str) -> str:
    raw_name = data.get("name")
    if isinstance(raw_name, dict):
        return str(raw_name.get(locale) or raw_name.get("en_US") or next(iter(raw_name.values()), ""))
    return str(raw_name or "")


def resolve_item_target(
    client: BnetClient,
    *,
    item_id: int | None = None,
    query: str | None = None,
    ttl_seconds: int = DEFAULT_ITEM_TTL,
    cache_only: bool = False,
) -> tuple[int, str | None, str, list[dict]]:
    """Return (item_id, item_name_or_none, item_lookup_status, candidate_matches)."""
    if item_id is not None and query:
        raise BnetConfigError("Specify either item_id or query, not both.")
    if item_id is None and (not query or not str(query).strip()):
        raise BnetConfigError("Specify either an item ID or an item search query.")

    if item_id is not None:
        iid = _positive_int(item_id, "item_id")
        try:
            resp = client.get_json(
                f"/data/wow/item/{iid}",
                namespace=static_namespace(client.region),
                ttl_seconds=ttl_seconds,
                not_found_ttl=3600,
                cache_only=cache_only,
            )
        except BnetNotFoundError:
            return iid, None, "not_found", []
        if resp is None:
            return iid, None, "cache_miss", []
        name = resp.payload.get("name") if isinstance(resp.payload, dict) else None
        return iid, str(name) if isinstance(name, str) and name else None, "found", []

    clean_query = str(query).strip()
    if clean_query.isdigit():
        return resolve_item_target(client, item_id=int(clean_query), ttl_seconds=ttl_seconds, cache_only=cache_only)

    resp = client.get_json(
        "/data/wow/search/item",
        namespace=static_namespace(client.region),
        params={f"name.{client.locale}": clean_query, "_pageSize": "10"},
        ttl_seconds=ttl_seconds,
        cache_only=cache_only,
    )
    if resp is None:
        raise BnetNotFoundError(f"Item search for '{clean_query}' was not found in local cache.", from_cache=True)

    results = resp.payload.get("results") if isinstance(resp.payload, dict) else []
    candidates: list[dict] = []
    for entry in results or []:
        data = entry.get("data") if isinstance(entry, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("id"), int):
            continue
        candidates.append({"id": int(data["id"]), "name": _extract_search_name(data, client.locale)})

    if not candidates:
        raise BnetNotFoundError(f"No Forever item matched '{clean_query}' in Battle.net item search.")

    target_cf = clean_query.casefold()
    exact = next((c for c in candidates if c["name"].casefold() == target_cf), None)
    chosen = exact or candidates[0]
    return chosen["id"], chosen["name"] or None, "found", candidates[:5]


def _weighted_median(unit_prices_and_qty: list[tuple[int, int]]) -> int | None:
    if not unit_prices_and_qty:
        return None
    ordered = sorted(unit_prices_and_qty, key=lambda pair: pair[0])
    total = sum(qty for _, qty in ordered)
    if total <= 0:
        return None
    midpoint = (total + 1) // 2
    seen = 0
    for price, qty in ordered:
        seen += qty
        if seen >= midpoint:
            return price
    return ordered[-1][0]


def _summarize_listings(rows: list[tuple[int, int]]) -> dict:
    if not rows:
        return {
            "listing_count": 0,
            "total_quantity": 0,
            "min_unit_copper": None,
            "median_unit_copper": None,
            "max_unit_copper": None,
            "min_unit_gold": None,
            "median_unit_gold": None,
        }
    prices = [p for p, _ in rows]
    min_p = min(prices)
    max_p = max(prices)
    med_p = _weighted_median(rows)
    return {
        "listing_count": len(rows),
        "total_quantity": sum(q for _, q in rows),
        "min_unit_copper": min_p,
        "median_unit_copper": med_p,
        "max_unit_copper": max_p,
        "min_unit_gold": gold(min_p),
        "median_unit_gold": gold(med_p) if med_p is not None else None,
    }


def price_summary(
    client: BnetClient,
    *,
    ruleset_id: int = DEFAULT_RULESET_ID,
    house_id: int,
    item_id: int | None = None,
    query: str | None = None,
    ttl_seconds: int = DEFAULT_MARKET_TTL,
    include_commodities: bool = True,
    include_auctions: bool = True,
    cache_only: bool = False,
    force_refresh: bool = False,
) -> dict:
    """Summarize live/cached Forever AH and commodity listings for one item on one house."""
    rid = _positive_int(ruleset_id, "ruleset_id")
    hid = _positive_int(house_id, "house_id")
    if not include_commodities and not include_auctions:
        raise BnetConfigError("Enable at least one of commodities or auctions.")

    resolved_id, item_name, item_lookup_status, candidates = resolve_item_target(
        client,
        item_id=item_id,
        query=query,
        cache_only=cache_only,
    )

    commodity_rows: list[tuple[int, int]] = []
    auction_rows: list[tuple[int, int]] = []
    sources: dict[str, dict] = {}
    house_name: str | None = None
    any_cache_miss = False

    dyn_ns = dynamic_namespace(client.region)

    if include_commodities:
        c_resp = client.get_json(
            f"/data/wow/ruleset/{rid}/auctions/{hid}/commodities",
            namespace=dyn_ns,
            ttl_seconds=ttl_seconds,
            cache_only=cache_only,
            force_refresh=force_refresh,
        )
        if c_resp is None:
            any_cache_miss = True
            sources["commodities"] = {"status": "cache_miss"}
        else:
            entries = c_resp.payload.get("auctions") if isinstance(c_resp.payload, dict) else []
            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                item = entry.get("item")
                if not isinstance(item, dict) or item.get("id") != resolved_id:
                    continue
                unit_price = entry.get("unit_price")
                qty = entry.get("quantity", 1)
                if (
                    isinstance(unit_price, int)
                    and not isinstance(unit_price, bool)
                    and unit_price > 0
                    and isinstance(qty, int)
                    and not isinstance(qty, bool)
                    and qty > 0
                ):
                    commodity_rows.append((unit_price, qty))
            sources["commodities"] = {
                "status": "ok",
                "from_cache": c_resp.from_cache,
                "age_seconds": c_resp.age_seconds(),
                "total_snapshot_entries": len(entries) if isinstance(entries, list) else 0,
            }

    if include_auctions:
        a_resp = client.get_json(
            f"/data/wow/ruleset/{rid}/auctions/{hid}",
            namespace=dyn_ns,
            ttl_seconds=ttl_seconds,
            cache_only=cache_only,
            force_refresh=force_refresh,
        )
        if a_resp is None:
            any_cache_miss = True
            sources["auctions"] = {"status": "cache_miss"}
        else:
            if isinstance(a_resp.payload, dict) and isinstance(a_resp.payload.get("name"), str):
                house_name = a_resp.payload["name"]
            entries = a_resp.payload.get("auctions") if isinstance(a_resp.payload, dict) else []
            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                item = entry.get("item")
                if not isinstance(item, dict) or item.get("id") != resolved_id:
                    continue
                buyout = entry.get("buyout")
                qty = entry.get("quantity", 1)
                if (
                    isinstance(buyout, int)
                    and not isinstance(buyout, bool)
                    and buyout > 0
                    and isinstance(qty, int)
                    and not isinstance(qty, bool)
                    and qty > 0
                ):
                    auction_rows.append((buyout // qty, qty))
            sources["auctions"] = {
                "status": "ok",
                "from_cache": a_resp.from_cache,
                "age_seconds": a_resp.age_seconds(),
                "total_snapshot_entries": len(entries) if isinstance(entries, list) else 0,
            }

    combined_rows = commodity_rows + auction_rows
    return {
        "status": "cache_miss" if (any_cache_miss and not combined_rows and all(s.get("status") == "cache_miss" for s in sources.values())) else "ok",
        "region": client.region,
        "ruleset_id": rid,
        "house_id": hid,
        "house_name": house_name,
        "item_id": resolved_id,
        "item_name": item_name,
        "item_lookup_status": item_lookup_status,
        "search_candidates": candidates,
        "summary": _summarize_listings(combined_rows),
        "commodities": _summarize_listings(commodity_rows),
        "auctions": _summarize_listings(auction_rows),
        "sources": sources,
        "attribution": ATTRIBUTION,
    }


def compare_houses(
    client: BnetClient,
    *,
    ruleset_id: int = DEFAULT_RULESET_ID,
    faction: str | None = None,
    item_id: int | None = None,
    query: str | None = None,
    ttl_seconds: int = DEFAULT_MARKET_TTL,
    include_commodities: bool = True,
    include_auctions: bool = False,
    cache_only: bool = False,
    force_refresh: bool = False,
) -> dict:
    """Compare one item's prices across matching Forever auction houses on a ruleset."""
    rid = _positive_int(ruleset_id, "ruleset_id")
    if faction is not None and faction not in {"alliance", "horde", "blackwater"}:
        raise BnetConfigError("faction must be alliance, horde, or blackwater.")
    resolved_id, item_name, item_lookup_status, _ = resolve_item_target(
        client,
        item_id=item_id,
        query=query,
        cache_only=cache_only,
    )
    listed = list_houses(client, rid, cache_only=cache_only, force_refresh=force_refresh)
    if listed["status"] != "ok":
        return {
            "status": listed["status"],
            "region": client.region,
            "ruleset_id": rid,
            "faction": faction,
            "item_id": resolved_id,
            "item_name": item_name,
            "comparisons": [],
            "attribution": ATTRIBUTION,
        }
    houses = listed["houses"]
    if faction:
        houses = [h for h in houses if faction in h["name"].casefold()]
    comparisons = []
    for house in houses:
        one = price_summary(
            client,
            ruleset_id=rid,
            house_id=house["id"],
            item_id=resolved_id,
            ttl_seconds=ttl_seconds,
            include_commodities=include_commodities,
            include_auctions=include_auctions,
            cache_only=cache_only,
            force_refresh=force_refresh,
        )
        comparisons.append(
            {
                "house_id": house["id"],
                "house_name": house["name"],
                "status": one["status"],
                "summary": one["summary"],
            }
        )
    return {
        "status": "ok",
        "region": client.region,
        "ruleset_id": rid,
        "faction": faction,
        "item_id": resolved_id,
        "item_name": item_name,
        "item_lookup_status": item_lookup_status,
        "comparisons": comparisons,
        "attribution": ATTRIBUTION,
    }


def as_text(result: dict) -> str:
    """Short, speakable summary of a market or index lookup with Blizzard attribution."""
    if "comparisons" in result:
        label = f"{result['item_name']} (#{result['item_id']})" if result.get("item_name") else f"Item {result['item_id']}"
        fac = f" ({result['faction']})" if result.get("faction") else ""
        lines = [f"{label} across ruleset {result['ruleset_id']}{fac} auction houses:"]
        for row in result["comparisons"]:
            s = row["summary"]
            if row["status"] == "cache_miss":
                detail = "no cached snapshot"
            elif not s["listing_count"]:
                detail = "no listings"
            else:
                detail = f"min {s['min_unit_gold']}, median {s['median_unit_gold']} ({s['total_quantity']:,} units, {s['listing_count']:,} listings)"
            lines.append(f"- House {row['house_id']} ({row['house_name']}): {detail}")
        lines.append(result.get("attribution", ATTRIBUTION))
        return "\n".join(lines)

    if "rulesets" in result:
        items = ", ".join(f"{r['id']}: {r['name']}" for r in result["rulesets"]) or "none"
        return f"Forever rulesets ({result.get('region', 'us')}): {items}.\n{result.get('attribution', ATTRIBUTION)}"

    if "houses" in result:
        items = ", ".join(f"{h['id']} ({h['name']})" for h in result["houses"]) or "none"
        return (
            f"Ruleset {result['ruleset_id']} auction houses ({len(result['houses'])}): {items}.\n"
            f"{result.get('attribution', ATTRIBUTION)}"
        )

    label = result.get("item_name") or f"Item {result['item_id']}"
    if result.get("item_name"):
        label = f"{result['item_name']} (#{result['item_id']})"
    house_desc = f"house {result['house_id']}" + (f" ({result['house_name']})" if result.get("house_name") else "")
    summary = result.get("summary") or {}
    if result.get("status") == "cache_miss":
        return f"{label} on ruleset {result['ruleset_id']}, {house_desc}: no fresh cached snapshot available.\n{result.get('attribution', ATTRIBUTION)}"
    if not summary.get("listing_count"):
        return f"{label} on ruleset {result['ruleset_id']}, {house_desc}: no buyout or commodity listings found.\n{result.get('attribution', ATTRIBUTION)}"

    return (
        f"{label} on ruleset {result['ruleset_id']}, {house_desc}: "
        f"min {summary['min_unit_gold']}, median {summary['median_unit_gold']} "
        f"({summary['total_quantity']:,} units across {summary['listing_count']:,} listings).\n"
        f"{result.get('attribution', ATTRIBUTION)}"
    )
