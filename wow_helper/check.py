"""Check the first real addon snapshot against the helper's assumptions.

Read-only, like quests.py and character.py. The result names counts, API sources, and the client
build, never a character, realm, account, zone, quest title, or path, so it can be pasted into an
issue or a commit message as evidence of what a game client confirmed.
"""

import re

from .quests import SCHEMA, STALE_AFTER, VARIABLE, _age, _int, _str
from .savedvars import SavedVariablesError, as_list
from .wtf import ADDON_SOURCE

ADDON_VERSION = "0.4.0"  # the first addon version that saves client build info and API sources
TOC = ADDON_SOURCE / "WoWCompanion.toc"
CONFIRMED, MISSING, MISMATCH = "confirmed", "missing", "mismatch"


def toc_lines(path=TOC):
    """The interface numbers and the version the shipped .toc declares."""
    interfaces, version = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Interface:"):
            interfaces = [int(n) for n in re.findall(r"\d+", line)]
        elif line.startswith("## Version:"):
            version = line.split(":", 1)[1].strip()
    return interfaces, version


def report(parsed, mtime, *, flavor=None, now, interfaces=None):
    """Checks from parse() output; raises SavedVariablesError when the addon saved nothing."""
    db = parsed.get(VARIABLE) if isinstance(parsed, dict) else None
    if not isinstance(db, dict):
        raise SavedVariablesError("The addon has not saved anything yet: enable WoW Companion at character select, then /reload.")
    interfaces = toc_lines()[0] if interfaces is None else list(interfaces)
    checks = []

    def check(name, result, detail):
        checks.append({"check": name, "result": result, "detail": detail})

    addon = _str(db.get("addon"))
    if addon == ADDON_VERSION:
        check("addon_version", CONFIRMED, f"addon {addon} saved this snapshot")
    elif addon:
        check("addon_version", MISMATCH, f"addon {addon} saved it; this helper ships {ADDON_VERSION}; run install-addon and /reload")
    else:
        check("addon_version", MISSING, f"saved by an addon older than {ADDON_VERSION}; run install-addon and /reload")
    schema = _int(db.get("schema"))
    if schema == SCHEMA:
        check("schema", CONFIRMED, f"data version {schema}")
    else:
        check("schema", MISMATCH, f"data version {schema}; this helper reads {SCHEMA}")

    client = db.get("client") if isinstance(db.get("client"), dict) else None
    client = {"version": _str(client.get("version")), "build": _str(client.get("build")) or _int(client.get("build")),
              "interface": _int(client.get("interface"))} if client else None
    if client and client["interface"]:
        check("client_build", CONFIRMED, f"client {client['version']} build {client['build']}, interface {client['interface']}")
        if client["interface"] in interfaces:
            check("toc_interface", CONFIRMED, f"the .toc lists interface {client['interface']}")
        else:
            listed = ", ".join(str(n) for n in interfaces) or "nothing"
            check("toc_interface", MISMATCH, f"the client reports interface {client['interface']} but the .toc lists {listed}; "
                                             "tick Load out of date AddOns, then update the .toc")
    else:
        check("client_build", MISSING, "no client build saved; needs the current addon")
        check("toc_interface", MISSING, "unknown until the addon saves the client build")

    api = _str(db.get("api"))
    if api in {"modern", "classic"}:
        check("quest_api", CONFIRMED, f"the {api} quest-log API is in use")
    else:
        check("quest_api", MISSING, "the addon did not record which quest-log API it used")

    quests = [q for q in as_list(db.get("quests")) if isinstance(q, dict)]
    collapsed = len(as_list(db.get("collapsedHeaders")))
    if quests:
        check("quest_log", CONFIRMED, f"{len(quests)} quests saved, {collapsed} collapsed headers")
    else:
        check("quest_log", MISSING, f"no quests saved ({collapsed} collapsed headers); add a quest or expand the headers, then /reload")
    objectives = [o for q in quests for o in as_list(q.get("objectives")) if isinstance(o, dict)]
    counted = [o for o in objectives if _int(o.get("have")) is not None and _int(o.get("need")) is not None]
    if counted:
        check("objective_counts", CONFIRMED, f"{len(counted)} of {len(objectives)} objectives carry counts")
    elif objectives:
        check("objective_counts", MISSING, f"{len(objectives)} objectives carry text only; expected on the classic leaderboard API")
    else:
        check("objective_counts", MISSING, "no objectives saved; pick up a quest with a counter, then /reload")
    distances = [q for q in quests if _int(q.get("distance")) is not None]
    if distances:
        check("distance", CONFIRMED, f"distance reported for {len(distances)} of {len(quests)} quests")
    else:
        check("distance", MISSING, "no distances; expected on the classic API, or no quest objective on this continent")

    completed = db.get("completedQuests")
    if completed is not None:
        check("completed_quests", CONFIRMED, f"{len(as_list(completed))} completed quest IDs")
    else:
        check("completed_quests", MISSING, "this client offers neither GetAllCompletedQuestIDs nor GetQuestsCompleted")
    available = db.get("available")
    if available is not None:
        count, map_id = len(as_list(available)), _int(db.get("mapID"))
        note = "" if count else "; the game may list only quest-line quests, so compare with the map"
        check("available_quests", CONFIRMED, f"{count} quests listed for map {map_id}{note}")
    else:
        check("available_quests", MISSING, "this client offers no C_QuestLine map listing")

    status = db.get("character") if isinstance(db.get("character"), dict) else None
    if status and _int(status.get("money")) is not None:
        bags = status.get("bags") if isinstance(status.get("bags"), dict) else {}
        gear = len([g for g in as_list(status.get("gear")) if isinstance(g, dict)])
        bag_note = f"{_int(bags.get('free'))} of {_int(bags.get('total'))} bag slots free" if bags else "no bag counts"
        check("character_status", CONFIRMED, f"money, {gear} gear slots, {bag_note}")
    else:
        check("character_status", MISSING, "no character status; needs addon 0.3.0 or newer")
    player = db.get("player") if isinstance(db.get("player"), dict) else {}
    if _int(player.get("level")) and _str(player.get("class")):
        check("player", CONFIRMED, f"level {_int(player.get('level'))} {_str(player.get('class')).lower()}")
    else:
        check("player", MISSING, "no player level or class saved")

    raw_sources = db.get("sources") if isinstance(db.get("sources"), dict) else None
    sources = {k: _str(v) for k, v in raw_sources.items() if isinstance(k, str) and _str(v)} if raw_sources else None
    if sources:
        check("api_sources", CONFIRMED, ", ".join(f"{k} from {v}" for k, v in sorted(sources.items())))
    else:
        check("api_sources", MISSING, "no API sources recorded; needs the current addon")

    age = max(0, int(now - mtime))
    warnings = []
    if age > STALE_AFTER:
        warnings.append(f"The snapshot is {age // 60} minutes old; /reload in game and check again.")
    counts = {r: sum(1 for c in checks if c["result"] == r) for r in (CONFIRMED, MISSING, MISMATCH)}
    return {"status": "ok", "age_seconds": age, "flavor": flavor,
            "addon": {"version": addon, "schema": schema, "api": api}, "client": client, "sources": sources,
            "checks": checks, "counts": counts, "warnings": warnings}


def as_text(result):
    """Readable lines: a summary, one line per check, then warnings. Safe to paste as evidence."""
    counts = result["counts"]
    edition = f" (edition {result['flavor']})" if result["flavor"] else ""
    lines = [f"Snapshot check from {_age(result['age_seconds'])}{edition}: {counts[CONFIRMED]} confirmed, "
             f"{counts[MISSING]} missing, {counts[MISMATCH]} mismatched."]
    lines += [f"  {c['result']:<10} {c['check']}: {c['detail']}" for c in result["checks"]]
    return "\n".join(lines + result["warnings"])
