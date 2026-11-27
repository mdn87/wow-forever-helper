"""Forever ruleset status and static reference catalogs via Battle.net API.

Caches verified static-forever-<region> indexes only under ignored runtime
storage (<=30-day TTL). Deliberately excludes journal-instance/index, which
returns an empty payload on Forever.
"""

from __future__ import annotations

from .bnet_api import (
    ATTRIBUTION,
    BnetClient,
    BnetConfigError,
    dynamic_namespace,
    static_namespace,
)

DEFAULT_RULESET_TTL = 300  # 5 minutes
DEFAULT_CATALOG_TTL = 7 * 24 * 3600  # 7 days (<= 30-day Terms ceiling)

# Map of supported catalog kind -> (endpoint path, list field name)
CATALOGS: dict[str, tuple[str, str]] = {
    "races": ("/data/wow/playable-race/index", "races"),
    "specs": ("/data/wow/playable-specialization/index", "character_specializations"),
    "professions": ("/data/wow/profession/index", "professions"),
    "item-classes": ("/data/wow/item-class/index", "item_classes"),
    "achievements": ("/data/wow/achievement/index", "achievements"),
    "mounts": ("/data/wow/mount/index", "mounts"),
    "pets": ("/data/wow/pet/index", "pets"),
    "creature-families": ("/data/wow/creature-family/index", "creature_families"),
    "quest-areas": ("/data/wow/quest/area/index", "areas"),
    "quest-categories": ("/data/wow/quest/category/index", "categories"),
}


def ruleset_status(
    client: BnetClient,
    ruleset_id: int | None = None,
    *,
    ttl_seconds: int = DEFAULT_RULESET_TTL,
    cache_only: bool = False,
    force_refresh: bool = False,
) -> dict:
    """Return status for one Forever ruleset or all rulesets in the region."""
    dyn_ns = dynamic_namespace(client.region)
    if ruleset_id is not None:
        if isinstance(ruleset_id, bool) or not isinstance(ruleset_id, int) or ruleset_id <= 0:
            raise BnetConfigError("ruleset_id must be a positive integer.")
        resp = client.get_json(
            f"/data/wow/ruleset/{ruleset_id}",
            namespace=dyn_ns,
            ttl_seconds=ttl_seconds,
            cache_only=cache_only,
            force_refresh=force_refresh,
        )
        if resp is None:
            return {"status": "cache_miss", "rulesets": [], "attribution": ATTRIBUTION}
        payload = resp.payload if isinstance(resp.payload, dict) else {}
        status_obj = payload.get("status") if isinstance(payload.get("status"), dict) else {}
        return {
            "status": "ok",
            "region": client.region,
            "rulesets": [
                {
                    "id": payload.get("id", ruleset_id),
                    "name": str(payload.get("name") or ""),
                    "status_type": status_obj.get("type"),
                    "status_name": status_obj.get("name"),
                }
            ],
            "from_cache": resp.from_cache,
            "age_seconds": resp.age_seconds(),
            "attribution": resp.attribution,
        }

    idx = client.get_json(
        "/data/wow/ruleset/index",
        namespace=dyn_ns,
        ttl_seconds=ttl_seconds,
        cache_only=cache_only,
        force_refresh=force_refresh,
    )
    if idx is None:
        return {"status": "cache_miss", "rulesets": [], "attribution": ATTRIBUTION}
    raw_list = idx.payload.get("rulesets") if isinstance(idx.payload, dict) else []
    results: list[dict] = []
    for item in raw_list or []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            continue
        one = ruleset_status(
            client,
            item["id"],
            ttl_seconds=ttl_seconds,
            cache_only=cache_only,
            force_refresh=force_refresh,
        )
        if one["status"] == "ok" and one["rulesets"]:
            results.append(one["rulesets"][0])
        else:
            results.append({"id": item["id"], "name": str(item.get("name") or ""), "status_type": None, "status_name": "Unknown"})
    return {
        "status": "ok",
        "region": client.region,
        "rulesets": results,
        "from_cache": idx.from_cache,
        "attribution": ATTRIBUTION,
    }


def fetch_catalog(
    client: BnetClient,
    kind: str,
    *,
    ttl_seconds: int = DEFAULT_CATALOG_TTL,
    cache_only: bool = False,
    force_refresh: bool = False,
) -> dict:
    """Fetch one supported Forever static reference catalog."""
    if kind not in CATALOGS:
        raise BnetConfigError(f"Unsupported Forever catalog '{kind}'. Choose one of: {', '.join(sorted(CATALOGS))}.")
    path, list_key = CATALOGS[kind]
    resp = client.get_json(
        path,
        namespace=static_namespace(client.region),
        ttl_seconds=ttl_seconds,
        cache_only=cache_only,
        force_refresh=force_refresh,
    )
    if resp is None:
        return {"status": "cache_miss", "kind": kind, "count": 0, "entries": [], "attribution": ATTRIBUTION}
    raw_entries = resp.payload.get(list_key) if isinstance(resp.payload, dict) else []
    entries = [
        {"id": int(e["id"]), "name": str(e.get("name") or "")}
        for e in (raw_entries or [])
        if isinstance(e, dict) and isinstance(e.get("id"), int)
    ]
    return {
        "status": "ok",
        "region": client.region,
        "kind": kind,
        "count": len(entries),
        "entries": entries,
        "served_namespace": resp.served_namespace,
        "from_cache": resp.from_cache,
        "age_seconds": resp.age_seconds(),
        "attribution": resp.attribution,
    }


def search_catalog(
    client: BnetClient,
    kind: str,
    query: str,
    *,
    limit: int = 10,
    ttl_seconds: int = DEFAULT_CATALOG_TTL,
    cache_only: bool = False,
) -> dict:
    catalog = fetch_catalog(client, kind, ttl_seconds=ttl_seconds, cache_only=cache_only)
    if catalog["status"] != "ok":
        return {**catalog, "query": str(query or ""), "matches": []}
    needle = str(query or "").strip().casefold()
    cap = max(1, min(100, int(limit)))
    matches = [e for e in catalog["entries"] if not needle or needle in e["name"].casefold()]
    return {
        "status": "ok",
        "region": catalog["region"],
        "kind": kind,
        "query": str(query or "").strip(),
        "total_matches": len(matches),
        "matches": matches[:cap],
        "served_namespace": catalog.get("served_namespace"),
        "from_cache": catalog["from_cache"],
        "attribution": catalog["attribution"],
    }


def as_text(result: dict) -> str:
    if "rulesets" in result:
        if not result["rulesets"]:
            return f"No Forever ruleset status available.\n{result.get('attribution', ATTRIBUTION)}"
        lines = [
            f"Ruleset {r['id']} ({r['name']}): {r.get('status_name') or r.get('status_type') or 'Unknown'}"
            for r in result["rulesets"]
        ]
        return "\n".join(lines) + f"\n{result.get('attribution', ATTRIBUTION)}"

    entries = result.get("matches") if "matches" in result else result.get("entries") or []
    kind = result.get("kind", "catalog")
    if not entries:
        return f"Forever {kind}: no matching entries.\n{result.get('attribution', ATTRIBUTION)}"
    shown = ", ".join(f"{e['name']} ({e['id']})" for e in entries[:15])
    total = result.get("total_matches", result.get("count", len(entries)))
    extra = f" (showing {min(len(entries), 15)} of {total})" if total > 15 else f" ({total} total)"
    return f"Forever {kind}{extra}: {shown}.\n{result.get('attribution', ATTRIBUTION)}"
