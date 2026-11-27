"""Forever static item metadata resolution with graceful 404 fallback.

Resolves numeric item IDs against static-forever-<region> for Character status,
upgrade guidance, quest rewards, and hands-free lookups. Explicitly tolerates
HTTP 404 responses because roughly half of equipped Forever items are currently
omitted from Blizzard's static /item endpoint.
"""

from __future__ import annotations

from copy import deepcopy

from .bnet_api import (
    ATTRIBUTION,
    BnetClient,
    BnetConfigError,
    BnetNotFoundError,
    static_namespace,
)
from .character import gold

DEFAULT_ITEM_TTL = 7 * 24 * 3600  # 7 days (<= 30-day Terms ceiling)
DEFAULT_NOT_FOUND_TTL = 3600  # 1 hour negative cache to avoid repeating 404 bursts


def parse_item_metadata(payload: dict) -> dict:
    """Extract a compact, bounded metadata record from a /data/wow/item/{id} payload."""
    preview = payload.get("preview_item") if isinstance(payload.get("preview_item"), dict) else {}
    quality_obj = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
    item_class = payload.get("item_class") if isinstance(payload.get("item_class"), dict) else {}
    item_subclass = payload.get("item_subclass") if isinstance(payload.get("item_subclass"), dict) else {}
    inv_type = payload.get("inventory_type") if isinstance(payload.get("inventory_type"), dict) else {}
    binding_obj = preview.get("binding") if isinstance(preview.get("binding"), dict) else {}

    stats: list[dict] = []
    for raw_stat in preview.get("stats") or []:
        if not isinstance(raw_stat, dict):
            continue
        stat_type = raw_stat.get("type") if isinstance(raw_stat.get("type"), dict) else {}
        display = raw_stat.get("display") if isinstance(raw_stat.get("display"), dict) else {}
        stats.append(
            {
                "type": stat_type.get("type"),
                "name": stat_type.get("name"),
                "value": raw_stat.get("value"),
                "display": display.get("display_string"),
            }
        )

    spells: list[dict] = []
    for raw_spell in preview.get("spells") or []:
        if not isinstance(raw_spell, dict):
            continue
        spell_ref = raw_spell.get("spell") if isinstance(raw_spell.get("spell"), dict) else {}
        spells.append(
            {
                "id": spell_ref.get("id"),
                "name": spell_ref.get("name"),
                "description": str(raw_spell.get("description") or "")[:600],
            }
        )

    weapon_info = None
    raw_weapon = preview.get("weapon")
    if isinstance(raw_weapon, dict):
        dmg = raw_weapon.get("damage") if isinstance(raw_weapon.get("damage"), dict) else {}
        speed = raw_weapon.get("attack_speed") if isinstance(raw_weapon.get("attack_speed"), dict) else {}
        dps = raw_weapon.get("dps") if isinstance(raw_weapon.get("dps"), dict) else {}
        weapon_info = {
            "min_damage": dmg.get("min_value"),
            "max_damage": dmg.get("max_value"),
            "damage_display": dmg.get("display_string"),
            "speed_display": speed.get("display_string"),
            "dps": round(float(dps["value"]), 2) if isinstance(dps.get("value"), (int, float)) else None,
            "dps_display": dps.get("display_string"),
        }

    armor_info = None
    raw_armor = preview.get("armor")
    if isinstance(raw_armor, dict):
        display = raw_armor.get("display") if isinstance(raw_armor.get("display"), dict) else {}
        armor_info = {"value": raw_armor.get("value"), "display": display.get("display_string")}

    sell_price = payload.get("sell_price")
    purchase_price = payload.get("purchase_price")

    return {
        "id": payload.get("id"),
        "name": payload.get("name"),
        "quality": quality_obj.get("name"),
        "quality_type": quality_obj.get("type"),
        "level": payload.get("level"),
        "required_level": payload.get("required_level"),
        "item_class": item_class.get("name"),
        "item_subclass": item_subclass.get("name"),
        "inventory_type": inv_type.get("name"),
        "binding": binding_obj.get("name"),
        "is_equippable": bool(payload.get("is_equippable")),
        "sell_price_copper": sell_price if isinstance(sell_price, int) else None,
        "sell_price_gold": gold(sell_price) if isinstance(sell_price, int) and sell_price > 0 else None,
        "purchase_price_copper": purchase_price if isinstance(purchase_price, int) else None,
        "weapon": weapon_info,
        "armor": armor_info,
        "stats": stats,
        "spells": spells,
    }


def lookup_item(
    client: BnetClient,
    item_id: int,
    *,
    ttl_seconds: int = DEFAULT_ITEM_TTL,
    not_found_ttl: int | None = DEFAULT_NOT_FOUND_TTL,
    cache_only: bool = False,
    force_refresh: bool = False,
) -> dict:
    """Resolve one Forever item ID; returns structured status on 404 or cache miss."""
    if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
        raise BnetConfigError("item_id must be a positive integer.")
    try:
        resp = client.get_json(
            f"/data/wow/item/{item_id}",
            namespace=static_namespace(client.region),
            ttl_seconds=ttl_seconds,
            not_found_ttl=not_found_ttl,
            cache_only=cache_only,
            force_refresh=force_refresh,
        )
    except BnetNotFoundError as exc:
        return {
            "status": "not_found",
            "id": item_id,
            "from_cache": exc.from_cache,
            "attribution": ATTRIBUTION,
        }
    if resp is None:
        return {
            "status": "cache_miss",
            "id": item_id,
            "from_cache": False,
            "attribution": ATTRIBUTION,
        }
    if not isinstance(resp.payload, dict):
        return {
            "status": "not_found",
            "id": item_id,
            "from_cache": resp.from_cache,
            "attribution": ATTRIBUTION,
        }
    return {
        "status": "ok",
        "id": item_id,
        "item": parse_item_metadata(resp.payload),
        "served_namespace": resp.served_namespace,
        "from_cache": resp.from_cache,
        "age_seconds": resp.age_seconds(),
        "attribution": resp.attribution,
    }


def search_items(
    client: BnetClient,
    query: str,
    *,
    page_size: int = 5,
    ttl_seconds: int = DEFAULT_ITEM_TTL,
    cache_only: bool = False,
) -> dict:
    clean = str(query or "").strip()
    if not clean:
        raise BnetConfigError("Item search query must be non-empty.")
    size = max(1, min(20, int(page_size)))
    resp = client.get_json(
        "/data/wow/search/item",
        namespace=static_namespace(client.region),
        params={f"name.{client.locale}": clean, "_pageSize": str(size)},
        ttl_seconds=ttl_seconds,
        cache_only=cache_only,
    )
    if resp is None:
        return {"status": "cache_miss", "query": clean, "results": [], "attribution": ATTRIBUTION}
    raw_results = resp.payload.get("results") if isinstance(resp.payload, dict) else []
    matches = []
    for entry in raw_results or []:
        data = entry.get("data") if isinstance(entry, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("id"), int):
            continue
        raw_name = data.get("name")
        if isinstance(raw_name, dict):
            name = str(raw_name.get(client.locale) or raw_name.get("en_US") or next(iter(raw_name.values()), ""))
        else:
            name = str(raw_name or "")
        quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
        matches.append(
            {
                "id": int(data["id"]),
                "name": name,
                "level": data.get("level"),
                "required_level": data.get("required_level"),
                "quality": quality.get("name", {}).get(client.locale) if isinstance(quality.get("name"), dict) else quality.get("type"),
            }
        )
    return {
        "status": "ok",
        "query": clean,
        "results": matches,
        "from_cache": resp.from_cache,
        "attribution": resp.attribution,
    }


def format_item_summary(item: dict) -> str:
    """Concise, readable item summary for UI cards, guidance context, or speech."""
    parts = [str(item.get("name") or f"Item {item.get('id')}")]
    meta = []
    if item.get("quality"):
        meta.append(str(item["quality"]))
    if item.get("level"):
        meta.append(f"ilvl {item['level']}")
    if item.get("required_level"):
        meta.append(f"req {item['required_level']}")
    if item.get("inventory_type") and item.get("inventory_type") != "Non-equippable":
        meta.append(str(item["inventory_type"]))
    if meta:
        parts[0] += f" ({', '.join(meta)})"
    weapon = item.get("weapon")
    if isinstance(weapon, dict):
        w_bits = [b for b in (weapon.get("damage_display"), weapon.get("dps_display")) if b]
        if w_bits:
            parts.append(" ".join(w_bits))
    armor = item.get("armor")
    if isinstance(armor, dict) and armor.get("display"):
        parts.append(str(armor["display"]))
    stat_bits = [str(s["display"]) for s in (item.get("stats") or []) if s.get("display")]
    if stat_bits:
        parts.append(", ".join(stat_bits[:6]))
    spell_bits = [str(sp["description"]) for sp in (item.get("spells") or []) if sp.get("description")]
    if spell_bits:
        desc = spell_bits[0]
        parts.append(desc if len(desc) <= 240 else desc[:239].rstrip() + "…")
    return "; ".join(parts)


def enrich_character_report(
    report: dict,
    client: BnetClient,
    *,
    cache_only: bool = False,
) -> dict:
    """Return a copy of a character.report() dict enriched with Forever item metadata."""
    enriched = deepcopy(report)
    resolved = 0
    not_found = 0
    unavailable = 0

    for entry in enriched.get("gear") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), int):
            continue
        try:
            outcome = lookup_item(client, entry["id"], cache_only=cache_only)
        except BnetConfigError:
            entry["bnet_status"] = "unavailable"
            unavailable += 1
            continue
        status = outcome["status"]
        entry["bnet_status"] = status
        if status == "ok":
            item = outcome["item"]
            entry["name"] = item["name"]
            entry["quality"] = item["quality"]
            entry["stats"] = item["stats"]
            entry["weapon"] = item["weapon"]
            entry["armor"] = item["armor"]
            entry["spells"] = item["spells"]
            entry["sell_price_gold"] = item["sell_price_gold"]
            entry["summary"] = format_item_summary(item)
            resolved += 1
        elif status == "not_found":
            not_found += 1
        else:
            unavailable += 1

    enriched["bnet_summary"] = {
        "resolved": resolved,
        "not_found": not_found,
        "unavailable": unavailable,
    }
    enriched["bnet_attribution"] = ATTRIBUTION
    return enriched


def enrich_gear_context(context: dict, client: BnetClient, *, cache_only: bool = False) -> dict:
    """Attach resolved Forever item details to a guidance upgrade-research context."""
    enriched = deepcopy(context)
    gear = enriched.get("gear")
    if isinstance(gear, list):
        wrapped = enrich_character_report({"gear": gear}, client, cache_only=cache_only)
        enriched["gear"] = wrapped["gear"]
        enriched["bnet_summary"] = wrapped["bnet_summary"]
        enriched["bnet_attribution"] = ATTRIBUTION
        if wrapped["bnet_summary"]["not_found"]:
            enriched.setdefault("bnet_notes", []).append(
                f"{wrapped['bnet_summary']['not_found']} equipped item ID(s) returned HTTP 404 from the Forever item API; rely on snapshot ilvl or web sources for those slots."
            )
    return enriched
