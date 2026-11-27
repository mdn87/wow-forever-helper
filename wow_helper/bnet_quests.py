"""Forever static quest reward and repeatability enrichment via Battle.net API.

Adds reward XP, choice/fixed reward item IDs (optionally resolved via
bnet_items), reputation gains, quest description, and repeatability to Quest
guide and Quest chat. Blizzard's quest endpoint does not supply prerequisite
quest chains or objective coordinates; quest_chain.py remains authoritative for
chain research.
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
from .bnet_items import format_item_summary, lookup_item
from .character import gold

DEFAULT_QUEST_TTL = 7 * 24 * 3600  # 7 days (<= 30-day Terms ceiling)
DEFAULT_NOT_FOUND_TTL = 3600


def _extract_reward_items(raw_list) -> list[dict]:
    items: list[dict] = []
    for entry in raw_list or []:
        if not isinstance(entry, dict):
            continue
        ref = entry.get("item") if isinstance(entry.get("item"), dict) else entry
        if not isinstance(ref, dict) or not isinstance(ref.get("id"), int):
            continue
        items.append({"id": int(ref["id"]), "name": str(ref.get("name") or "") or None})
    return items


def parse_quest_metadata(payload: dict) -> dict:
    area = payload.get("area") if isinstance(payload.get("area"), dict) else {}
    rewards = payload.get("rewards") if isinstance(payload.get("rewards"), dict) else {}
    raw_items = rewards.get("items") if isinstance(rewards.get("items"), dict) else {}

    reputations: list[dict] = []
    for rep in rewards.get("reputations") or []:
        if not isinstance(rep, dict):
            continue
        ref = rep.get("reward") if isinstance(rep.get("reward"), dict) else {}
        val = rep.get("value")
        if isinstance(val, int) and not isinstance(val, bool):
            reputations.append(
                {
                    "faction_id": ref.get("id") if isinstance(ref.get("id"), int) else None,
                    "faction_name": str(ref.get("name") or "") or None,
                    "value": val,
                }
            )

    money = rewards.get("money")
    money_value = money.get("value") if isinstance(money, dict) else money
    money_copper = money_value if isinstance(money_value, int) and not isinstance(money_value, bool) and money_value > 0 else None
    xp = rewards.get("experience")
    xp_val = xp if isinstance(xp, int) and not isinstance(xp, bool) and xp > 0 else None

    return {
        "id": payload.get("id"),
        "title": payload.get("title"),
        "area_id": area.get("id") if isinstance(area.get("id"), int) else None,
        "area_name": str(area.get("name") or "") or None,
        "description": str(payload.get("description") or "")[:1200],
        "is_repeatable": payload.get("is_repeatable") is True,
        "rewards": {
            "experience": xp_val,
            "money_copper": money_copper,
            "money_gold": gold(money_copper) if money_copper else None,
            "reputations": reputations,
            "choice_items": _extract_reward_items(raw_items.get("choice_of")),
            "fixed_items": _extract_reward_items(raw_items.get("items")),
        },
        "prerequisites_available": False,
    }


def lookup_quest(
    client: BnetClient,
    quest_id: int,
    *,
    resolve_reward_items: bool = True,
    ttl_seconds: int = DEFAULT_QUEST_TTL,
    not_found_ttl: int | None = DEFAULT_NOT_FOUND_TTL,
    cache_only: bool = False,
) -> dict:
    if isinstance(quest_id, bool) or not isinstance(quest_id, int) or quest_id <= 0:
        raise BnetConfigError("quest_id must be a positive integer.")
    try:
        resp = client.get_json(
            f"/data/wow/quest/{quest_id}",
            namespace=static_namespace(client.region),
            ttl_seconds=ttl_seconds,
            not_found_ttl=not_found_ttl,
            cache_only=cache_only,
        )
    except BnetNotFoundError as exc:
        return {"status": "not_found", "id": quest_id, "from_cache": exc.from_cache, "attribution": ATTRIBUTION}
    if resp is None:
        return {"status": "cache_miss", "id": quest_id, "from_cache": False, "attribution": ATTRIBUTION}
    if not isinstance(resp.payload, dict):
        return {"status": "not_found", "id": quest_id, "from_cache": resp.from_cache, "attribution": ATTRIBUTION}

    quest = parse_quest_metadata(resp.payload)
    if resolve_reward_items:
        for bucket in ("choice_items", "fixed_items"):
            for item_ref in quest["rewards"][bucket]:
                try:
                    item_res = lookup_item(client, item_ref["id"], cache_only=cache_only)
                except BnetConfigError:
                    item_ref["bnet_status"] = "unavailable"
                    continue
                item_ref["bnet_status"] = item_res["status"]
                if item_res["status"] == "ok":
                    item_ref["item"] = item_res["item"]
                    item_ref["summary"] = format_item_summary(item_res["item"])

    return {
        "status": "ok",
        "id": quest_id,
        "quest": quest,
        "served_namespace": resp.served_namespace,
        "from_cache": resp.from_cache,
        "age_seconds": resp.age_seconds(),
        "attribution": resp.attribution,
    }


def format_rewards_brief(quest: dict) -> str:
    rewards = quest.get("rewards") if isinstance(quest.get("rewards"), dict) else {}
    bits: list[str] = []
    if rewards.get("experience"):
        bits.append(f"{rewards['experience']:,} XP")
    if rewards.get("money_gold"):
        bits.append(str(rewards["money_gold"]))
    choice = rewards.get("choice_items") or []
    fixed = rewards.get("fixed_items") or []
    if choice:
        names = ", ".join(str(i.get("name") or f"#{i['id']}") for i in choice[:3])
        bits.append(f"choose 1 of {len(choice)}: {names}")
    if fixed:
        names = ", ".join(str(i.get("name") or f"#{i['id']}") for i in fixed[:3])
        bits.append(f"rewards: {names}")
    reps = rewards.get("reputations") or []
    if reps:
        rep_str = ", ".join(f"+{r['value']} {r.get('faction_name') or 'reputation'}" for r in reps[:2])
        bits.append(rep_str)
    if quest.get("is_repeatable"):
        bits.append("repeatable")
    return "; ".join(bits)


def enrich_quest_report(
    report: dict,
    client: BnetClient,
    *,
    resolve_reward_items: bool = False,
    cache_only: bool = False,
) -> dict:
    """Return a non-mutating copy of quests.report() with Forever quest reward summaries."""
    enriched = deepcopy(report)
    resolved = 0
    not_found = 0
    unavailable = 0

    for step in enriched.get("plan") or []:
        qid = step.get("id") if isinstance(step, dict) else None
        if not isinstance(qid, int) or qid <= 0:
            continue
        try:
            outcome = lookup_quest(client, qid, resolve_reward_items=resolve_reward_items, cache_only=cache_only)
        except BnetConfigError:
            step["bnet_status"] = "unavailable"
            unavailable += 1
            continue
        step["bnet_status"] = outcome["status"]
        if outcome["status"] == "ok":
            quest = outcome["quest"]
            step["bnet_rewards"] = quest["rewards"]
            step["bnet_repeatable"] = quest["is_repeatable"]
            brief = format_rewards_brief(quest)
            if brief:
                step["bnet_rewards_text"] = brief
            resolved += 1
        elif outcome["status"] == "not_found":
            not_found += 1
        else:
            unavailable += 1

    enriched["bnet_summary"] = {"resolved": resolved, "not_found": not_found, "unavailable": unavailable}
    enriched["bnet_attribution"] = ATTRIBUTION
    return enriched


def enrich_quest_chat_context(
    context: dict,
    client: BnetClient,
    *,
    resolve_reward_items: bool = True,
    cache_only: bool = False,
) -> dict:
    """Attach Forever quest rewards and repeatability to a quest_chat context payload."""
    enriched = deepcopy(context)
    quest_obj = enriched.get("quest") if isinstance(enriched.get("quest"), dict) else {}
    qid = quest_obj.get("id")
    if not isinstance(qid, int) or qid <= 0:
        return enriched
    try:
        outcome = lookup_quest(client, qid, resolve_reward_items=resolve_reward_items, cache_only=cache_only)
    except BnetConfigError:
        enriched["bnet_quest"] = {"status": "unavailable", "attribution": ATTRIBUTION}
        return enriched
    if outcome["status"] == "ok":
        enriched["bnet_quest"] = {
            "status": "ok",
            "quest": outcome["quest"],
            "rewards_text": format_rewards_brief(outcome["quest"]),
            "served_namespace": outcome.get("served_namespace"),
            "caveat": "Blizzard quest API provides rewards and repeatability only; prerequisites and objectives are not included.",
            "attribution": ATTRIBUTION,
        }
    else:
        enriched["bnet_quest"] = {"status": outcome["status"], "id": qid, "attribution": ATTRIBUTION}
    return enriched
