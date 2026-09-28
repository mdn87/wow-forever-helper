"""Turn the companion addon's quest snapshot into an ordered, advice-only plan.

The plan is a suggestion for the player to read. Nothing here sends input or feeds the
assistive-input path: quest data must never choose or trigger an action (AGENTS.md).
"""

from dataclasses import dataclass, field
import re
import time

from .savedvars import SavedVariablesError, as_list

VARIABLE = "WoWCompanionDB"
SCHEMA = 1
STALE_AFTER = 15 * 60
# Forever's Wowhead section is not known yet; classic IDs are the closest match (unverified).
LINKS = {"_retail_": "https://www.wowhead.com/quest=", "classic": "https://www.wowhead.com/classic/quest="}


@dataclass
class Objective:
    text: str
    done: bool
    have: int | None = None
    need: int | None = None

    @property
    def progress(self):
        if self.done:
            return 1.0
        if isinstance(self.have, int) and isinstance(self.need, int) and self.need > 0:
            return max(0.0, min(1.0, self.have / self.need))
        return 0.0


@dataclass
class Quest:
    id: int | None
    title: str
    level: int | None
    zone: str | None
    complete: bool
    failed: bool
    group: int
    distance: int | None
    objectives: list[Objective] = field(default_factory=list)

    @property
    def progress(self):
        if self.complete:
            return 1.0
        if not self.objectives:
            return 0.0
        return sum(o.progress for o in self.objectives) / len(self.objectives)


@dataclass
class Snapshot:
    level: int | None
    player_class: str | None
    zone: str | None
    subzone: str | None
    saved_at: float | None
    quests: list[Quest]
    collapsed: list[str]
    schema: int | None


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value if isinstance(value, int) else None


# The game's inline markup: colour starts, colour ends, and hyperlink wrappers.
_MARKUP = re.compile(r"\|c[0-9A-Fa-f]{8}|\|r|\|H[^|]*\|h|\|h")


def _str(value):
    if not isinstance(value, str):
        return None
    return _MARKUP.sub("", value).strip() or None


def load(parsed):
    """Build a Snapshot from parse() output; raises SavedVariablesError when it has none."""
    db = parsed.get(VARIABLE) if isinstance(parsed, dict) else None
    if not isinstance(db, dict) or "quests" not in db:
        raise SavedVariablesError("The addon has not saved a quest log yet: /reload in game.")
    player = db.get("player") if isinstance(db.get("player"), dict) else {}
    quests = []
    for raw in as_list(db.get("quests")):
        if not isinstance(raw, dict) or not _str(raw.get("title")):
            continue
        objectives = [Objective(_str(o.get("text")) or "objective", o.get("finished") is True,
                                _int(o.get("have")), _int(o.get("need")))
                      for o in as_list(raw.get("objectives")) if isinstance(o, dict)]
        quests.append(Quest(_int(raw.get("id")), _str(raw["title"]), _int(raw.get("level")), _str(raw.get("header")),
                            raw.get("complete") is True, raw.get("failed") is True,
                            _int(raw.get("group")) or 0, _int(raw.get("distance")), objectives))
    saved_at = db.get("savedAt")
    return Snapshot(_int(player.get("level")), _str(player.get("class")), _str(player.get("zone")),
                    _str(player.get("subzone")), saved_at if isinstance(saved_at, (int, float)) else None,
                    quests, [h for h in as_list(db.get("collapsedHeaders")) if isinstance(h, str)],
                    _int(db.get("schema")))


def gray_level(level):
    """Highest quest level that gives little XP, from the classic con-colour rule (approximate)."""
    if level is None or level <= 5:
        return 0
    if level < 40:
        return level - level // 10 - 5
    return level - level // 5 - 1


def difficulty(quest, level):
    if quest.level is None or level is None:
        return "unknown"
    if quest.level >= level + 5:
        return "red"
    if quest.level >= level + 3:
        return "orange"
    if quest.level <= gray_level(level):
        return "gray"
    return "normal"


def remaining(quest):
    left = []
    for o in quest.objectives:
        if o.done:
            continue
        # Classic objective text already reads "Test Pelt: 3/8"; do not repeat the count.
        if o.need and o.have is not None and f"{o.have}/{o.need}" not in o.text:
            left.append(f"{o.text} ({o.have}/{o.need})")
        else:
            left.append(o.text)
    return left


def plan(snapshot, flavor=None):
    """Ordered steps: turn-ins, restarts, quests to finish now, then quests for later."""
    here = (snapshot.zone or "").casefold()
    base = LINKS.get(flavor, LINKS["classic"])

    def near(quest):
        return ((quest.zone or "").casefold() != here, quest.distance if quest.distance is not None else 10**9)

    turn_in, restart, now, low, later = [], [], [], [], []
    for quest in snapshot.quests:
        con = difficulty(quest, snapshot.level)
        if quest.complete:
            turn_in.append((quest, "turn in", ["objectives done; hand it in"]))
        elif quest.failed:
            restart.append((quest, "restart", ["failed; abandon it and pick it up again from the quest giver"]))
        elif con == "red" or (quest.group > 1 and con == "orange"):
            why = [f"level {quest.level} is well above you"] if con == "red" else []
            if quest.group > 1:
                why.append(f"group quest for {quest.group} players")
            later.append((quest, "later", why or ["too hard for now"]))
        else:
            notes = []
            if con == "orange":
                notes.append(f"level {quest.level} is hard for level {snapshot.level}; pull carefully")
            if quest.group > 1:
                notes.append(f"suggested group of {quest.group}")
            if quest.progress >= 0.5:
                notes.append("more than half done")
            (low if con == "gray" else now).append((quest, "finish", notes))
    low = [(q, a, n + ["low XP at your level; finish it only if you pass by"]) for q, a, n in low]
    turn_in.sort(key=lambda item: near(item[0]))
    now.sort(key=lambda item: (near(item[0])[0], -round(item[0].progress, 2), near(item[0])[1], item[0].level or 0))
    low.sort(key=lambda item: near(item[0]))
    later.sort(key=lambda item: (item[0].level or 0))
    steps = []
    for quest, action, notes in turn_in + restart + now + low + later:
        steps.append({"step": len(steps) + 1, "action": action, "id": quest.id, "title": quest.title,
                      "zone": quest.zone, "level": quest.level, "remaining": remaining(quest),
                      "distance_yards": quest.distance, "notes": notes,
                      "link": f"{base}{quest.id}" if quest.id else None})
    return steps


def report(snapshot, mtime, *, flavor=None, now=None):
    now = time.time() if now is None else now
    age = max(0, int(now - mtime))
    warnings = []
    if age > STALE_AFTER:
        warnings.append(f"The snapshot is {age // 60} minutes old; /reload in game for current quests.")
    if snapshot.collapsed:
        warnings.append("Collapsed quest-log headers can hide quests; expand them and /reload: "
                        + ", ".join(snapshot.collapsed) + ".")
    if snapshot.schema != SCHEMA:
        warnings.append("The addon's data version differs from this helper's; update the addon.")
    return {"status": "ok", "age_seconds": age,
            "player": {"level": snapshot.level, "class": snapshot.player_class,
                       "zone": snapshot.zone, "subzone": snapshot.subzone},
            "quest_count": len(snapshot.quests), "plan": plan(snapshot, flavor), "warnings": warnings}


def _age(seconds):
    if seconds < 90:
        return "just now"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} minutes ago"
    return f"{round(seconds / 3600)} hours ago"


def as_text(result):
    """A short readable (and speakable) version of report()."""
    player = result["player"]
    who = " ".join(str(v) for v in (f"level {player['level']}" if player["level"] else None,
                                    (player["class"] or "").title() or None) if v)
    where = f" in {player['zone']}" if player["zone"] else ""
    lines = [f"Quest log from {_age(result['age_seconds'])}: {who or 'your character'}{where}, "
             f"{result['quest_count']} quests."]
    verbs = {"turn in": "Turn in", "restart": "Restart", "finish": "Finish", "later": "Later"}
    for step in result["plan"]:
        detail = [step["zone"]] if step["zone"] else []
        detail += step["remaining"][:3] + step["notes"]
        suffix = f" ({'; '.join(detail)})" if detail else ""
        lines.append(f"{step['step']}. {verbs[step['action']]}: {step['title']}{suffix}")
    lines += result["warnings"]
    return "\n".join(lines)
