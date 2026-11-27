"""Hands-free spoken in-game live-test walkthrough and local result log.

Guides the player through the remaining manual in-game checks for chips #30,
#21, #22, and #23 via short spoken instructions delivered through Lugos Voice
(or printed by the CLI). Saves pass/fail/skip outcomes and optional notes in
ignored .runtime/live-test-results.json. Never sends game input or changes focus.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from .chat import ROOT, read_json, write_json

DEFAULT_STORE = ROOT / ".runtime" / "live-test-results.json"
VALID_STATUSES = ("pass", "fail", "skipped")


@dataclass(frozen=True)
class LiveTestItem:
    number: int
    id: str
    chip: str
    title: str
    spoken: str


ITEMS: tuple[LiveTestItem, ...] = (
    LiveTestItem(
        number=1,
        id="bnet-ah-house",
        chip="#30",
        title="Match your Forever auction house ID",
        spoken=(
            "Stand at your faction auction house in Classic Forever and search for Linen Cloth. "
            "Compare the lowest unit price and listing count against the five-house table from "
            "market compare-houses, and note which house ID matches."
        ),
    ),
    LiveTestItem(
        number=2,
        id="bnet-voice-market",
        chip="#30",
        title="Spoken Forever auction house price check",
        spoken=(
            "Keep WoW in front and say: price check Linen Cloth. "
            "Confirm you hear a minimum and median price, total units, and Blizzard attribution "
            "while WoW keeps keyboard focus."
        ),
    ),
    LiveTestItem(
        number=3,
        id="bnet-voice-item",
        chip="#30",
        title="Spoken Forever item stats and Wowhead fallback",
        spoken=(
            "Keep WoW in front and say: item stats for Thunderfury. "
            "Confirm you hear its stats, weapon DPS, and Blizzard attribution. "
            "Optionally ask for an item missing from the API to confirm it falls back to Classic Wowhead."
        ),
    ),
    LiveTestItem(
        number=4,
        id="live-gear-compare",
        chip="#21",
        title="Player-operated live gear tooltip comparison",
        spoken=(
            "Open Live gear comparison in the companion, review a capture box around your tooltip area, "
            "and enable the shortcut. In WoW, hold Shift over a candidate item so both tooltips show, "
            "then press Control Alt F9 or say compare gear. Check that WoW keeps focus and the stat "
            "differences match the tooltips."
        ),
    ),
    LiveTestItem(
        number=5,
        id="live-ptt-dictation",
        chip="#21",
        title="Push-to-talk Whisper dictation accuracy",
        spoken=(
            "Enable Voice input on a chat window, then hold Keypad minus until Recording appears. "
            "Speak a short WoW question with spell or zone names and release. "
            "Confirm the text lands accurately in the draft without auto-sending."
        ),
    ),
    LiveTestItem(
        number=6,
        id="live-ux-themes",
        chip="#21",
        title="Visual inspection in Classic and Modern Synth themes",
        spoken=(
            "Look over Chat, Quest guide, Character status, and Settings in Classic theme, "
            "then switch to Modern Synth under Interface and transparency. "
            "Check text contrast, equipment table alignment, and readable pre-send review tabs with no clipped controls."
        ),
    ),
    LiveTestItem(
        number=7,
        id="live-browser-focus",
        chip="#21",
        title="Voice browser and normal browser link focus",
        spoken=(
            "With WoW active on your main screen, say: look up frostbolt, then open the first result, "
            "then read the page. Move your character between turns to confirm WoW keeps keyboard focus. "
            "If you enabled normal browser links on a chat, also confirm where opened links land."
        ),
    ),
    LiveTestItem(
        number=8,
        id="live-handsfree-fight",
        chip="#21",
        title="Real combat log digest via Ask about the last fight",
        spoken=(
            "In WoW, type slash combatlog before a pull and finish one fight. "
            "Then say: ask about the last fight, press read combat log, and press prepare review. "
            "Confirm the digest parses deaths or damage cleanly with player names aliased."
        ),
    ),
    LiveTestItem(
        number=9,
        id="context-addon-reload",
        chip="#22",
        title="Addon 0.4.1 logout guard and snapshot check",
        spoken=(
            "With WoW Companion enabled at character select, play for a minute, log out cleanly, "
            "and run check-snapshot. Confirm gold and rested XP show real values rather than zero "
            "and unload reads is confirmed."
        ),
    ),
    LiveTestItem(
        number=10,
        id="context-probe-strip",
        chip="#22",
        title="Context probe pixel strip capture",
        spoken=(
            "With WoW Companion Probe enabled, type slash wfhprobe strip in game, "
            "then run context-probe source window while the strip is visible. "
            "Confirm whether the packet decodes as fresh and note your display mode and UI scale."
        ),
    ),
    LiveTestItem(
        number=11,
        id="context-probe-copy",
        chip="#22",
        title="Context probe clipboard copy and secret values",
        spoken=(
            "Type slash wfhprobe copy in game, press Control C, then Escape, and run context-probe source clipboard. "
            "Also try slash wfhprobe copy api to see whether Forever allows CopyToClipboard, "
            "and note any fields reported as missing."
        ),
    ),
    LiveTestItem(
        number=12,
        id="economy-journalator-csv",
        chip="#23",
        title="Real Journalator Summary By Type CSV import",
        spoken=(
            "In game, open Journalator Summary By Type and export CSV. "
            "In the companion, open Session economy analysis, paste the CSV with a private alias and time range, "
            "and click Prepare review. Confirm all category rows and copper totals parse cleanly."
        ),
    ),
)

ITEMS_BY_ID = {item.id: item for item in ITEMS}
ITEMS_BY_NUMBER = {item.number: item for item in ITEMS}


class LiveTestGuide:
    """Stateful local live-test walkthrough with speakable prompts and durable results."""

    def __init__(self, store: Path | str | None = None, *, clock=time.time):
        self.store = Path(DEFAULT_STORE if store is None else store)
        self._clock = clock

    def _load(self) -> dict:
        raw = read_json(self.store)
        results = raw.get("results") if isinstance(raw.get("results"), dict) else {}
        current = raw.get("current") if isinstance(raw.get("current"), str) and raw.get("current") in ITEMS_BY_ID else None
        return {"version": 1, "current": current, "results": dict(results)}

    def _save(self, state: dict) -> None:
        write_json(self.store, state)

    def _first_pending(self, results: dict) -> LiveTestItem | None:
        for item in ITEMS:
            if item.id not in results:
                return item
        for item in ITEMS:
            if isinstance(results.get(item.id), dict) and results[item.id].get("status") == "skipped":
                return item
        return None

    def _current_item(self, state: dict) -> LiveTestItem | None:
        cid = state.get("current")
        if cid and cid in ITEMS_BY_ID:
            rec = state["results"].get(cid)
            if not isinstance(rec, dict) or rec.get("status") not in {"pass", "fail"}:
                return ITEMS_BY_ID[cid]
        return self._first_pending(state["results"])

    def format_spoken_item(self, item: LiveTestItem, *, prefix: str = "") -> str:
        cue = "Say pass test, fail test with a reason, or skip test."
        if item.id == "bnet-ah-house":
            cue = "Say pass test followed by your house ID, fail test with what differed, or skip test."
        body = f"Test {item.number} of {len(ITEMS)}, chip {item.chip}: {item.title}. {item.spoken} {cue}"
        return f"{prefix} {body}".strip() if prefix else body

    def next_prompt(self) -> str:
        state = self._load()
        item = self._current_item(state)
        if item is None:
            return self.status_spoken(prefix="All live tests have been recorded.")
        state["current"] = item.id
        self._save(state)
        return self.format_spoken_item(item)

    def repeat_prompt(self) -> str:
        state = self._load()
        item = self._current_item(state)
        if item is None:
            return self.status_spoken(prefix="All live tests have been recorded.")
        return self.format_spoken_item(item)

    def goto(self, number: int) -> str:
        item = ITEMS_BY_NUMBER.get(int(number))
        if item is None:
            return f"Choose a test number from 1 to {len(ITEMS)}."
        state = self._load()
        state["current"] = item.id
        self._save(state)
        return self.format_spoken_item(item)

    def record(self, status: str, *, item_id: str | None = None, note: str = "") -> tuple[dict, str]:
        if status not in VALID_STATUSES:
            raise ValueError(f"status must be one of {', '.join(VALID_STATUSES)}")
        state = self._load()
        if item_id is not None:
            target = ITEMS_BY_ID.get(item_id) or (ITEMS_BY_NUMBER.get(int(item_id)) if str(item_id).isdigit() else None)
        else:
            target = self._current_item(state)
        if target is None:
            return state, self.status_spoken(prefix="All live tests are already recorded.")

        clean_note = str(note or "").strip()[:300]
        state["results"][target.id] = {
            "status": status,
            "note": clean_note,
            "at": float(self._clock()),
        }
        # Advance to the next unrecorded item after target, wrapping to any earlier unrecorded/skipped item
        nxt = None
        for candidate in ITEMS:
            if candidate.number > target.number and candidate.id not in state["results"]:
                nxt = candidate
                break
        if nxt is None:
            nxt = self._first_pending(state["results"])
        state["current"] = nxt.id if nxt else None
        self._save(state)

        verb = {"pass": "Passed", "fail": "Failed", "skipped": "Skipped"}[status]
        ack = f"{verb} test {target.number}" + (f" ({clean_note})" if clean_note else "") + "."
        if nxt is None:
            return state, self.status_spoken(prefix=f"{ack} All live tests are now recorded.")
        return state, self.format_spoken_item(nxt, prefix=ack)

    def reset(self) -> str:
        self._save({"version": 1, "current": ITEMS[0].id, "results": {}})
        return f"Cleared saved live test results. {self.format_spoken_item(ITEMS[0])}"

    def summary(self, *, chip: str | None = None) -> dict:
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
            rec = results.get(item.id)
            st = rec.get("status") if isinstance(rec, dict) and rec.get("status") in VALID_STATUSES else "pending"
            counts[st] += 1
            rows.append(
                {
                    "number": item.number,
                    "id": item.id,
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
            "next_number": nxt.number if nxt else None,
            "next_id": nxt.id if nxt else None,
            "items": rows,
        }

    def status_spoken(self, *, prefix: str = "") -> str:
        info = self.summary()
        c = info["counts"]
        line = (
            f"Live test status: {c['pass']} passed, {c['fail']} failed, "
            f"{c['skipped']} skipped, {c['pending']} pending out of {info['total']}."
        )
        if info["next_number"] is not None:
            nxt = ITEMS_BY_NUMBER[info["next_number"]]
            line += f" Next is test {nxt.number}: {nxt.title}."
        return f"{prefix} {line}".strip() if prefix else line


def as_text(info: dict) -> str:
    c = info["counts"]
    lines = [
        f"Live in-game tests: {c['pass']} pass, {c['fail']} fail, {c['skipped']} skipped, {c['pending']} pending ({info['total']} total)."
    ]
    for row in info["items"]:
        note = f" — {row['note']}" if row.get("note") else ""
        lines.append(f"{row['number']:2d}. [{row['status'].upper():7s}] ({row['chip']}) {row['title']}{note}")
    return "\n".join(lines)
