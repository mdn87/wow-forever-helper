"""Hands-free spoken walkthrough of the runbook's play-time checks, with a local result log.

Offers the manual test runbook's open checks that can be done while playing, grouped by the
moment in play they fit: at login, while you play, after a fight, in town, at logout, or any
time. Each item keeps its runbook ID so results can be copied into the runbook later. Short
spoken instructions go out through Lugos Voice (or the CLI), and pass, fail or skip outcomes
with optional notes are saved in ignored .runtime/live-test-results.json. Checks that need a
command run at the desk while the game shows something stay in the runbook only. Never sends
game input or changes focus.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from .chat import ROOT, read_json, write_json

DEFAULT_STORE = ROOT / ".runtime" / "live-test-results.json"
VALID_STATUSES = ("pass", "fail", "skipped")
CUE = "Say pass test, fail test with a reason, or skip test."
NOTE_CUE = "Say pass test or fail test followed by what you saw, or skip test."


@dataclass(frozen=True)
class Moment:
    key: str
    name: str   # "No fight tests are left."
    when: str   # "Test 20 of 34, after a fight: ..."


MOMENTS: tuple[Moment, ...] = (
    Moment("login", "login", "at login"),
    Moment("play", "play", "while you play"),
    Moment("fight", "fight", "after a fight"),
    Moment("town", "town", "in town"),
    Moment("logout", "logout", "at logout"),
    Moment("anytime", "any-time", "any time"),
)
MOMENTS_BY_KEY = {moment.key: moment for moment in MOMENTS}
# Spoken words for each moment. voice_commands.Interpreter.GRAMMAR accepts the same words.
MOMENT_WORDS = {
    "login": "login", "log in": "login", "logging in": "login", "reload": "login",
    "play": "play", "playing": "play", "questing": "play",
    "fight": "fight", "fights": "fight", "combat": "fight", "boss": "fight", "pull": "fight",
    "town": "town", "city": "town", "break": "town", "downtime": "town",
    "logout": "logout", "log out": "logout", "logging out": "logout",
    "anytime": "anytime", "any time": "anytime",
}
EDITIONS = {"retail": "Retail", "forever": "Classic Forever"}

_R, _F, _RF, _NO_GAME = ("retail",), ("forever",), ("retail", "forever"), ()


@dataclass(frozen=True)
class LiveTestItem:
    number: int
    id: str                    # runbook item ID
    moment: str                # MOMENTS key
    editions: tuple[str, ...]  # editions the check runs on; empty when it needs no game
    title: str
    spoken: str
    chip: str = ""             # Dias chip the check belongs to, if any
    cue: str = CUE


def _item(id, moment, editions, title, spoken, *, chip="", cue=CUE):
    return {"id": id, "moment": moment, "editions": editions, "title": title, "spoken": spoken,
            "chip": chip, "cue": cue}


_ROWS = (
    # -- at login, or after /reload
    _item("2.5", "login", _R, "Probe status",
          "With the WoW Companion Probe addon enabled, type slash reload, then slash wfhprobe status. "
          "Status lines should print in chat."),
    _item("2.13", "login", _R, "Retail snapshot",
          "On a character with a quest that has a counter, type slash reload. Open the Quest guide and "
          "Character status and check objectives, counters, gold, durability and bags against the game. "
          "An agent reads the snapshot report and its interface number later, so judge what you see."),
    _item("2.14", "login", _R, "Quests to pick up",
          "Stand where quest givers show on the map and type slash reload. In the Quest guide, the Nearby "
          "pickups group should be filled and match the map."),
    _item("4.7", "login", _F, "Forever quests and links",
          "Type slash reload. Check the Quest guide and Character status against the game, and the Nearby "
          "pickups group against the map. Then click one Wowhead link: it should open the right quest. An "
          "agent reads the interface number from the snapshot later."),
    _item("6.4", "login", _F, "Quest guide, Character table and setup",
          "Type slash reload and open the Quest guide. Select a quest, copy an objective from the details "
          "below the list, and click a source link: it should open in your browser. Open Character status "
          "and read the gear table. Then in Settings, Preferences, WoW setup and addon health, press Check "
          "snapshot: it should report your edition with no missing fields."),
    _item("4.6", "login", _F, "Clipboard copy on Forever",
          "With the probe addon enabled, type slash wfhprobe copy api. Whatever it prints is the result.",
          chip="#22", cue="Say pass test followed by what it printed, fail test with a reason, or skip test."),
    # -- while you play
    _item("2.1", "play", _R, "Control Alt H with WoW in front",
          "Use Settings, Windows, Hide all windows. Then, with WoW in front, press Control Alt H, once in "
          "windowed and once in fullscreen windowed. The windows, and the two display windows if they were "
          "open, should come back with drafts intact, WoW should keep the keyboard, and no key should reach "
          "the game."),
    _item("2.4", "play", _R, "Readable over the game",
          "Put a Modern Synth chat window and a Play card at 340 by 300 and 65 percent opacity over the "
          "game. Both should stay readable while you play."),
    _item("2.3", "play", _R, "Capture WoW in each mode",
          "In a Screen adviser window, press Capture WoW in windowed, in fullscreen windowed, with HDR on if "
          "your screen supports it, and at a lower render scale. Each image should be fresh, the focus "
          "should not move, and it should never fall back to a desktop capture."),
    _item("2.2", "play", _R, "Exclusive fullscreen",
          "If WoW offers exclusive fullscreen, switch to it. Repeat the Control Alt H check and one Screen "
          "adviser Capture WoW. This mode has never been checked, so whatever happens is worth recording.",
          cue=NOTE_CUE),
    _item("2.15", "play", _R, "Full live gear comparison",
          "Open Live gear comparison, choose the edition, and enter your build and goal. Take a capture "
          "preview, drag the region over the tooltip, review it, pick a chat that takes images, and enable "
          "the shortcut. In WoW, hover an item with the comparison tooltip showing and press Control Alt F9. "
          "Check the result against the image and save it to the Journal. Repeat with a ring or trinket: "
          "both equipped panels stay separate. Last, disable the shortcut and press it: nothing happens.",
          chip="#21"),
    _item("2.25", "play", _R, "Gear comparison, hands-free",
          "With Live gear comparison set up and its shortcut enabled, hover an item in WoW and say: compare. "
          "One comparison should start, the same as Control Alt F9, and WoW should keep the focus."),
    _item("4.8", "play", _F, "Forever capture and gear",
          "In a Screen adviser window, press Capture WoW in windowed and in fullscreen windowed, then run "
          "one full Live gear comparison with Control Alt F9. Captures should be fresh, the focus should "
          "stay on WoW, and the comparison should match the tooltip."),
    _item("2.27", "play", _R, "Voice browser with WoW in front",
          "With WoW in front, say: open the browser. Then say look up frostbolt, open the first result, read "
          "the page, read more, scroll down, and go back, moving your character between turns. Every answer "
          "should be spoken, the Chrome window should change, and WoW should keep the keyboard the whole "
          "time. If the companion reports a foreground change, note what was in front.",
          chip="#21"),
    _item("6.6", "play", _RF, "Links from chat open in your browser",
          "In a chat window, open Settings, Windows, Window setup, and on Capabilities turn on Allow agent "
          "chats from this window to open web links. Start a new chat. With WoW in front, ask it for a guide "
          "link. The link should open once in your default browser, and the chat should show the link it "
          "opened. If the chat says Opening status unknown, Open anyway may open a second tab.",
          chip="#21"),
    _item("2.17", "play", _R, "Voice input with game audio",
          "With Voice input on Keypad minus enabled for a chat window, keep game audio playing and WoW "
          "focused. Hold Keypad minus, wait for Recording, speak, and release. The hold should still record "
          "into the draft, and the game should not act on Keypad minus."),
    _item("4.12", "play", _F, "Command library sharpening fix",
          "In the Command library, select the FSR sharpening fix, press Copy read value, paste it into game "
          "chat, and note the value. Press Copy command and paste it, then move where the ground brightness "
          "used to shift: the shift should stop. Then press Copy reset and paste it, or type your noted "
          "value back.",
          cue="Say pass test followed by the value you noted, fail test with a reason, or skip test."),
    _item("4.11", "play", _F, "Play Forever hands-free",
          "Play a stretch with hands-free connected: ask the agent questions, change settings, look things "
          "up in the voice browser, and after a boss ask about the last fight by voice. Use the mouse only "
          "when a step cannot be done by voice. Normal play should need no mouse for companion actions."),
    _item("2.26", "play", _RF, "Teleport, hands-free",
          "This needs setup first: an agent at the desk binds and enables the teleport key for your action "
          "bar slot, as in runbook 2.16. Then, with WoW in front and no chat box open, say: cast teleport to "
          "Orgrimmar on my mage. You should hear that the key was sent, and the spell should cast. If WoW is "
          "not in front, the request is refused. Afterwards, have the agent turn assistive input off again."),
    # -- after a fight
    _item("2.18", "fight", _R, "Bookmark and coaching",
          "After a fight, use Bookmark this moment with a Capture WoW image. Open Post-fight coaching for the "
          "first attempt, and after the next attempt use Compare later attempt in the same conversation. Mask "
          "other players' names before sending any capture. The bookmark should keep the image, and the "
          "second review should include the saved notes from the first."),
    _item("2.23", "fight", _R, "Ask about the last fight",
          "Type slash combatlog before a boss pull. Afterwards, open Ask about the last fight in Settings, "
          "type your question, press Read combat log, and read the Digest tab. Prepare review, send once to "
          "a chat, and ask a follow-up. The encounter, result and deaths should match what happened, and "
          "players should show as Player N or You. Leave Include player names off unless you need them."),
    _item("2.24", "fight", _R, "Ask about the last fight, hands-free",
          "With hands-free connected and slash combatlog on, after a pull say: ask about the last fight. Say "
          "type, then your question, then press read combat log. Then say press prepare review, read it, "
          "and send. The result should match the mouse version, and a second send should be refused.",
          chip="#21"),
    _item("4.9", "fight", _F, "Forever coaching and bookmarks",
          "After a fight, use Bookmark this moment with a Capture WoW image, then Post-fight coaching, and "
          "Compare later attempt after the next try. Mask other players' names before sending any capture. "
          "It should work the same as on Retail."),
    _item("4.10", "fight", _F, "Forever combat log digest",
          "Type slash combatlog before a dungeon or raid boss. Afterwards, open Ask about the last fight and "
          "press Read combat log. The digest status should not say unsupported layout, and encounter "
          "markers should be present."),
    # -- in town, or any quiet moment
    _item("2.22", "town", _R, "Research spot check",
          "Compare one quest-chain research result and one goal research result against the game or "
          "Wowhead. Both should match."),
    _item("2.19", "town", _R, "Journalator export",
          "With Journalator 171, Auctionator 341 and the English client, open Journalator Summary, By Type, "
          "and export the CSV. In Session economy analysis, import or paste it, declare the period, profile "
          "and filter exactly, and prepare review. Compare the totals with the in-game summary, then send. "
          "It should import without refusal, totals should match, and missing categories should be listed. "
          "Keep the CSV local.",
          chip="#23",
          cue="Say pass test, fail test with a reason, or skip test with the reason if your version is refused."),
    _item("2.20", "town", _R, "BugSack error",
          "Copy a real BugSack error into Addon troubleshooting, or use Import error text. Press Prepare "
          "review: locals should be left out and names replaced. Then send. The redaction should be "
          "complete before anything is sent."),
    _item("2.21", "town", _R, "SimC profile",
          "Type slash simc and copy the profile into Build tutor and experiments. Prepare review, then send. "
          "Identity fields should be left out, unsupported lines listed by key only, and talents and items "
          "parsed."),
    # -- at logout
    _item("4.3", "logout", _F, "Logout guard",
          "Log out to character select and back in. Character status should show your real gold and rested "
          "XP rather than zero. An agent reads the unload check in the snapshot report later.",
          chip="#22"),
    # -- any time; these need no game
    _item("1.25", "anytime", _NO_GAME, "Push-to-talk accuracy",
          "In a chat window, open Settings, Preferences, Voice input, choose Keypad minus, and enable it for "
          "this chat window. Hold Keypad minus, wait for Recording, speak, and release, with about ten WoW "
          "phrases: zones, spells, critical strike, haste and numbers. Then tap the key briefly once. Text "
          "should land in the draft and never send, the mic should stay unmuted, audio routing should not "
          "change, and a tap should not start a lasting recording.",
          chip="#21"),
    _item("1.22", "anytime", _NO_GAME, "Display pair check",
          "Open WoW companion displays from Settings, Preferences, on the touch screens. Check five things: "
          "no Dias edge strip, Swap screens works, the loading bar shows on quest reads, the F08 dialog opens "
          "in the display, and typing works there."),
    _item("1.23", "anytime", _NO_GAME, "Restart keeps screen order",
          "Note which screen holds the Quest log, then use Restart companion. The screens should not swap. "
          "They did once, and the cause is unknown."),
    _item("1.24", "anytime", _NO_GAME, "Unplugged display recovery",
          "This one is optional. Unplug one touch display, then reopen WoW companion displays. The displays "
          "should recover. Windows renumbers the screens when one is unplugged."),
    _item("0.4", "anytime", _NO_GAME, "Voice turn with no window connected",
          "Say: stop hands free. Then say one ordinary voice turn to Claude. It should reach Claude as "
          "before. Reconnect hands-free in the companion to record the result."),
)

ITEMS: tuple[LiveTestItem, ...] = tuple(LiveTestItem(number=number, **row) for number, row in enumerate(_ROWS, 1))
ITEMS_BY_ID = {item.id: item for item in ITEMS}
ITEMS_BY_NUMBER = {item.number: item for item in ITEMS}


def _status(record) -> str | None:
    status = record.get("status") if isinstance(record, dict) else None
    return status if status in VALID_STATUSES else None


class LiveTestGuide:
    """Stateful local live-test walkthrough with speakable prompts and durable results."""

    def __init__(self, store: Path | str | None = None, *, clock=time.time):
        self.store = Path(DEFAULT_STORE if store is None else store)
        self._clock = clock

    def _load(self) -> dict:
        raw = read_json(self.store)
        results = raw.get("results") if isinstance(raw.get("results"), dict) else {}
        current = raw.get("current") if isinstance(raw.get("current"), str) and raw.get("current") in ITEMS_BY_ID else None
        edition = raw.get("edition") if isinstance(raw.get("edition"), str) and raw.get("edition") in EDITIONS else None
        return {"version": 2, "current": current, "edition": edition, "results": dict(results)}

    def _save(self, state: dict) -> None:
        write_json(self.store, state)

    @staticmethod
    def _offered(item: LiveTestItem, state: dict) -> bool:
        edition = state.get("edition")
        return not edition or not item.editions or edition in item.editions

    def _open(self, state: dict, *, moment: str | None = None) -> list[LiveTestItem]:
        """Offered items still to do: unrecorded ones first, then skipped ones, in walkthrough order."""
        pool = [item for item in ITEMS
                if self._offered(item, state) and (moment is None or item.moment == moment)]
        results = state["results"]
        fresh = [item for item in pool if _status(results.get(item.id)) is None]
        skipped = [item for item in pool if _status(results.get(item.id)) == "skipped"]
        return fresh + skipped

    def _first_open(self, state: dict, *, moment: str | None = None) -> LiveTestItem | None:
        items = self._open(state, moment=moment)
        return items[0] if items else None

    def _current_item(self, state: dict) -> LiveTestItem | None:
        item = ITEMS_BY_ID.get(state.get("current"))
        if item is not None and _status(state["results"].get(item.id)) not in {"pass", "fail"}:
            return item
        return self._first_open(state)

    def _next_after(self, state: dict, target: LiveTestItem) -> LiveTestItem | None:
        """The next check to offer: the same moment first, then later moments, then skipped ones."""
        def rotated(items):
            return ([item for item in items if item.number > target.number]
                    + [item for item in items if item.number < target.number])

        results = state["results"]
        fresh = [item for item in ITEMS if self._offered(item, state) and _status(results.get(item.id)) is None]
        same_moment = rotated([item for item in fresh if item.moment == target.moment])
        if same_moment:
            return same_moment[0]
        later = rotated(fresh)
        if later:
            return later[0]
        skipped = rotated([item for item in self._open(state) if item.id != target.id])
        return skipped[0] if skipped else None

    def _finished(self, state: dict, *, prefix: str = "") -> str:
        edition = state.get("edition")
        if self._first_open(state) is not None:
            lead = "Only skipped tests are left."
        elif edition and self._first_open({**state, "edition": None}) is not None:
            lead = f"Every {EDITIONS[edition]} test is recorded."
        else:
            lead = "All live tests have been recorded."
        return self.status_spoken(prefix=f"{prefix} {lead}".strip())

    def format_spoken_item(self, item: LiveTestItem, *, prefix: str = "") -> str:
        where = MOMENTS_BY_KEY[item.moment].when
        if len(item.editions) == 1:
            where += f", on {EDITIONS[item.editions[0]]}"
        body = f"Test {item.number} of {len(ITEMS)}, {where}: {item.title}. {item.spoken} {item.cue}"
        return f"{prefix} {body}".strip() if prefix else body

    def next_prompt(self) -> str:
        state = self._load()
        item = self._current_item(state)
        if item is None:
            return self._finished(state)
        state["current"] = item.id
        self._save(state)
        return self.format_spoken_item(item)

    def repeat_prompt(self) -> str:
        state = self._load()
        item = self._current_item(state)
        return self._finished(state) if item is None else self.format_spoken_item(item)

    def goto(self, number: int) -> str:
        item = ITEMS_BY_NUMBER.get(int(number))
        if item is None:
            return f"Choose a test number from 1 to {len(ITEMS)}."
        state = self._load()
        state["current"] = item.id
        self._save(state)
        return self.format_spoken_item(item)

    def moment(self, key: str) -> str:
        """Select the first open check for a moment in play, such as after a fight."""
        moment = MOMENTS_BY_KEY[key]
        state = self._load()
        item = self._first_open(state, moment=key)
        if item is None:
            edition = state.get("edition")
            where = f" on {EDITIONS[edition]}" if edition else ""
            return self.status_spoken(prefix=f"No {moment.name} tests are left{where}.")
        state["current"] = item.id
        self._save(state)
        return self.format_spoken_item(item)

    def set_edition(self, edition: str | None) -> str:
        """Offer only one edition's checks plus those that need no game, or every check for None."""
        if edition is not None and edition not in EDITIONS:
            raise ValueError(f"edition must be one of {', '.join(EDITIONS)}")
        state = self._load()
        state["edition"] = edition
        item = ITEMS_BY_ID.get(state.get("current"))
        if item is None or not self._offered(item, state) or _status(state["results"].get(item.id)) in {"pass", "fail"}:
            item = self._first_open(state)
        state["current"] = item.id if item else None
        self._save(state)
        lead = (f"Playing {EDITIONS[edition]}: offering its tests and the ones that need no game."
                if edition else "Offering tests for every edition.")
        return self._finished(state, prefix=lead) if item is None else self.format_spoken_item(item, prefix=lead)

    def record(self, status: str, *, item_id: str | None = None, note: str = "") -> tuple[dict, str]:
        if status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {', '.join(VALID_STATUSES)}")
        state = self._load()
        if item_id is not None:
            key = str(item_id).strip()
            target = ITEMS_BY_ID.get(key) or (ITEMS_BY_NUMBER.get(int(key)) if key.isdigit() else None)
            if target is None:
                return state, f"There is no test {key}. Use a test number from 1 to {len(ITEMS)} or a runbook ID."
        else:
            target = self._current_item(state)
            if target is None:
                return state, self._finished(state)

        clean_note = str(note or "").strip()[:300]
        state["results"][target.id] = {
            "status": status,
            "note": clean_note,
            "at": float(self._clock()),
        }
        nxt = self._next_after(state, target)
        state["current"] = nxt.id if nxt else None
        self._save(state)

        verb = {"pass": "Passed", "fail": "Failed", "skipped": "Skipped"}[status]
        ack = f"{verb} test {target.number}" + (f" ({clean_note})" if clean_note else "") + "."
        if nxt is None:
            return state, self._finished(state, prefix=ack)
        return state, self.format_spoken_item(nxt, prefix=ack)

    def reset(self) -> str:
        state = self._load()
        self._save({"version": 2, "current": None, "edition": state["edition"], "results": {}})
        return f"Cleared saved live test results. {self.next_prompt()}"

    def summary(self, *, chip: str | None = None, moment: str | None = None) -> dict:
        state = self._load()
        results = state["results"]
        chip_filter = None
        if chip:
            chip_filter = chip if chip.startswith("#") else f"#{chip}"
        rows = []
        counts = {"pass": 0, "fail": 0, "skipped": 0, "pending": 0}
        for item in ITEMS:
            if chip_filter and item.chip != chip_filter:
                continue
            if moment and item.moment != moment:
                continue
            rec = results.get(item.id)
            st = _status(rec) or "pending"
            counts[st] += 1
            rows.append(
                {
                    "number": item.number,
                    "id": item.id,
                    "moment": item.moment,
                    "editions": list(item.editions),
                    "chip": item.chip,
                    "title": item.title,
                    "status": st,
                    "note": rec.get("note", "") if isinstance(rec, dict) else "",
                    "spoken": self.format_spoken_item(item),
                }
            )
        nxt = self._current_item(state)
        return {
            "status": "ok",
            "total": len(rows),
            "counts": counts,
            "edition": state["edition"],
            "next_number": nxt.number if nxt else None,
            "next_id": nxt.id if nxt else None,
            "items": rows,
        }

    def status_spoken(self, *, prefix: str = "") -> str:
        state = self._load()
        info = self.summary()
        c = info["counts"]
        line = (
            f"Live test status: {c['pass']} passed, {c['fail']} failed, "
            f"{c['skipped']} skipped, {c['pending']} pending out of {info['total']}."
        )
        open_counts = [f"{len(items)} {moment.when}" for moment in MOMENTS
                       if (items := self._open(state, moment=moment.key))]
        if open_counts:
            edition = state.get("edition")
            line += f" Open{' on ' + EDITIONS[edition] if edition else ''}: {', '.join(open_counts)}."
        nxt = self._current_item(state)
        if nxt is not None:
            line += f" Next is test {nxt.number}: {nxt.title}."
        return f"{prefix} {line}".strip() if prefix else line


def as_text(info: dict) -> str:
    c = info["counts"]
    lines = [
        f"Live in-game tests: {c['pass']} pass, {c['fail']} fail, {c['skipped']} skipped, {c['pending']} pending ({info['total']} total)."
    ]
    for row in info["items"]:
        editions = "".join(edition[0].upper() for edition in row["editions"]) or "-"
        chip = f" ({row['chip']})" if row.get("chip") else ""
        note = f" — {row['note']}" if row.get("note") else ""
        lines.append(
            f"{row['number']:2d}. [{row['status'].upper():7s}] {row['id']:<5s} {editions:<3s}"
            f"{row['moment']:<8s} {row['title']}{chip}{note}"
        )
    return "\n".join(lines)
