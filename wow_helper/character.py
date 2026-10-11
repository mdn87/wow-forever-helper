"""Character status from the companion addon's snapshot: gold, rested XP, gear, durability, bags.

Advice for the player to read, like quests.py. Nothing here sends input or chooses an action.
"""

from .quests import STALE_AFTER, VARIABLE, _age, _int, _str
from .savedvars import SavedVariablesError, as_list

SLOTS = {1: "head", 2: "neck", 3: "shoulders", 4: "shirt", 5: "chest", 6: "waist", 7: "legs", 8: "feet",
         9: "wrists", 10: "hands", 11: "ring", 12: "ring", 13: "trinket", 14: "trinket", 15: "back",
         16: "main hand", 17: "off hand", 18: "ranged", 19: "tabard"}
COSMETIC = {4, 19}  # the shirt and tabard have no item level that matters
REPAIR_AT = 25      # percent durability left on the most worn item
BAGS_LOW_AT = 2     # free bag slots
LINKS = {"_retail_": "https://www.wowhead.com/item=", "classic": "https://www.wowhead.com/classic/item="}


def gold(copper):
    g, rest = divmod(copper, 10000)
    s, c = divmod(rest, 100)
    return " ".join(f"{n}{unit}" for n, unit in ((g, "g"), (s, "s"), (c, "c")) if n) or "0c"


def report(parsed, mtime, *, flavor=None, now):
    """Status and warnings from parse() output; raises SavedVariablesError when there is none."""
    db = parsed.get(VARIABLE) if isinstance(parsed, dict) else None
    data = db.get("character") if isinstance(db, dict) else None
    if not isinstance(data, dict):
        raise SavedVariablesError("The addon has not saved character status yet: update it, then /reload in game.")
    player = db.get("player") if isinstance(db.get("player"), dict) else {}
    base = LINKS.get(flavor, LINKS["classic"])
    gear = []
    for item in as_list(data.get("gear")):
        slot, item_id = (_int(item.get("slot")), _int(item.get("id"))) if isinstance(item, dict) else (None, None)
        if slot not in SLOTS or not item_id:
            continue
        current, maximum = _int(item.get("durability")), _int(item.get("durabilityMax"))
        gear.append({"slot": SLOTS[slot], "slot_id": slot, "id": item_id, "ilvl": _int(item.get("ilvl")),
                     "durability_percent": round(100 * current / maximum) if current is not None and maximum else None,
                     "link": f"{base}{item_id}"})
    levels = [g["ilvl"] for g in gear if g["ilvl"] and g["slot_id"] not in COSMETIC]
    worn = [g for g in gear if g["durability_percent"] is not None]
    worst = min(worn, key=lambda g: g["durability_percent"]) if worn else None
    bags = data.get("bags") if isinstance(data.get("bags"), dict) else {}
    free, total = _int(bags.get("free")), _int(bags.get("total"))
    money, rested, xp_max = _int(data.get("money")), _int(data.get("rested")), _int(player.get("xpMax"))
    age = max(0, int(now - mtime))
    warnings = []
    if age > STALE_AFTER:
        warnings.append(f"The snapshot is {age // 60} minutes old; /reload in game for current status.")
    if worst and worst["durability_percent"] <= REPAIR_AT:
        state = "broken" if worst["durability_percent"] == 0 else f"at {worst['durability_percent']}%"
        warnings.append(f"Repair soon: the {worst['slot']} item is {state}.")
    if free is not None and total and free <= BAGS_LOW_AT:
        warnings.append(f"Bags nearly full: {free} free slots.")
    return {"status": "ok", "age_seconds": age,
            "player": {"level": _int(player.get("level")), "class": _str(player.get("class"))},
            "gold": gold(money) if money is not None else None, "copper": money,
            "rested_xp": rested,
            "rested_percent_of_level": round(100 * rested / xp_max) if rested is not None and xp_max else None,
            "average_item_level": round(sum(levels) / len(levels), 1) if levels else None,
            "lowest_durability": {"slot": worst["slot"], "percent": worst["durability_percent"]} if worst else None,
            "bags": {"free": free, "total": total} if total else None,
            "gear": gear, "warnings": warnings}


def as_text(result):
    """One or two short, speakable lines."""
    parts = []
    if result["gold"]:
        parts.append(f"{result['gold']} gold")
    if result["rested_percent_of_level"]:
        parts.append(f"rested for {result['rested_percent_of_level']}% of a level")
    if result["bags"]:
        parts.append(f"{result['bags']['free']} of {result['bags']['total']} bag slots free")
    if result["lowest_durability"]:
        parts.append(f"most worn item {result['lowest_durability']['percent']}% ({result['lowest_durability']['slot']})")
    if result["average_item_level"]:
        parts.append(f"average item level {result['average_item_level']:g}")
    line = f"Character status from {_age(result['age_seconds'])}: " + (", ".join(parts) or "no details saved") + "."
    return "\n".join([line] + result["warnings"])
