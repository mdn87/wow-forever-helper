"""Read-only digest of the last encounter in a WoW combat log; no writes, game access, or transport.

Only the tail of the log is read. Field layouts differ across Retail, Classic, and Forever and are
not pinned, so the damage layout is detected per log and anything unrecognised is reported as a gap
instead of guessed. Players are aliased unless names are requested; GUIDs, realms, and raw lines
never reach the digest.
"""

from bisect import bisect_right
from collections import deque
import csv
from datetime import date
import math
import os
from pathlib import Path
import re

from .chat import ChatError

MAX_BYTES = 48_000_000
MAX_LINES = 3_000_000
TEXT_LIMIT = 24_000
FALLBACK_SECONDS = 180
MAX_DEATHS = 40
MAX_LAST_HITS = 8
TOP_SPELLS = 10
FINAL_WINDOW = 10.0
HP_LEAD = 3.0
NAME_LIMIT = 60
NULL_GUID = "0000000000000000"
GUID_PREFIXES = ("Player-", "Creature-", "Pet-", "Vehicle-", "GameObject-", "Vignette-")
NPC_PREFIXES = ("Creature-", "Vehicle-", "GameObject-")
# Fields between the eight base fields and the advanced block; SWING has none.
DAMAGE_EVENTS = {"SWING_DAMAGE": 0, "RANGE_DAMAGE": 3, "SPELL_DAMAGE": 3, "SPELL_PERIODIC_DAMAGE": 3,
                 "SPELL_BUILDING_DAMAGE": 3, "ENVIRONMENTAL_DAMAGE": 1}
WANTED = frozenset(DAMAGE_EVENTS) | {"COMBAT_LOG_VERSION", "ENCOUNTER_START", "ENCOUNTER_END",
                                     "UNIT_DIED", "SPELL_CAST_SUCCESS"}
LAYOUTS = tuple((adv, base) for adv in (0, 17, 18, 19) for base in (False, True))
TIMESTAMP = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))? (\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?"
                       r"(?:[+-]\d{1,2}(?::?\d{2})?)?")
HEADER_VALUE = re.compile(r"[A-Za-z0-9._]{1,24}")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
READ_ERROR = "The combat log could not be read. Check that combat logging produced a file and try again."


def find_combat_log(install_roots, flavor):
    """The newest `WoWCombatLog*.txt` in `<root>/<flavor>/Logs/` across roots, or None."""
    found = []
    for root in install_roots:
        folder = Path(root) / flavor / "Logs"
        try:
            entries = list(folder.glob("WoWCombatLog*.txt"))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink() or not entry.is_file():
                    continue
                found.append((entry.stat().st_mtime, str(entry), entry))
            except OSError:
                continue
    return max(found)[2] if found else None


class _Clock:
    """Float seconds from the logged date and time of day, kept monotonic across midnight and year turns."""

    def __init__(self):
        self.days, self.origin, self.shift, self.last = {}, None, 0.0, None

    def __call__(self, stamp):
        match = TIMESTAMP.fullmatch(stamp)
        if not match:
            return None
        month, day, year, hour, minute, second, fraction = match.groups()
        key = (month, day, year)
        ordinal = self.days.get(key)
        if ordinal is None:
            try:
                # Logs without a year use a leap year so 2/29 still parses.
                ordinal = date(int(year or 2000), int(month), int(day)).toordinal()
            except ValueError:
                return None
            self.days[key] = ordinal
        hour, minute, second = int(hour), int(minute), int(second)
        if hour > 23 or minute > 59 or second > 60:
            return None
        if self.origin is None:
            self.origin = ordinal
        value = ((ordinal - self.origin) * 86400 + hour * 3600 + minute * 60 + second + self.shift
                 + (int(fraction) / 10 ** len(fraction) if fraction else 0.0))
        if self.last is not None and value < self.last - 43200:
            days = math.ceil((self.last - value) / 86400)
            self.shift += days * 86400
            value += days * 86400
        self.last = value if self.last is None else max(self.last, value)
        return value


def _fields(payload):
    try:
        row = next(csv.reader((payload,)), [])
    except csv.Error:
        return []
    return [None if field == "nil" else field for field in row]


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _guid_like(value):
    return value is not None and (value == NULL_GUID or value.startswith(GUID_PREFIXES))


def _header(fields):
    pairs = dict(zip(fields[0::2], fields[1::2]))
    value = {key: (pairs.get(name) if HEADER_VALUE.fullmatch(pairs.get(name) or "") else None)
             for key, name in (("version", "COMBAT_LOG_VERSION"), ("build", "BUILD_VERSION"),
                               ("project", "PROJECT_ID"))}
    value["advanced"] = {"1": True, "0": False}.get(pairs.get("ADVANCED_LOG_ENABLED"))
    return value


def _read_tail(path, max_bytes):
    """Read-only: at most `max_bytes` from the end, without the partial first line."""
    try:
        with open(path, "rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            offset = max(0, size - max_bytes)
            stream.seek(offset)
            raw = stream.read(max_bytes)
    except OSError:
        raise ChatError(READ_ERROR) from None
    if offset:
        cut = raw.find(b"\n")
        raw = raw[cut + 1:] if cut >= 0 else b""
    return raw.decode("utf-8", errors="replace").removeprefix("﻿"), offset, len(raw)


def _scan(text):
    """One pass: keep the last ENCOUNTER_START's lines, or a rolling fallback window if none."""
    clock, header = _Clock(), None
    fallback, window, start, end, start_header = deque(), None, None, None, None
    open_encounter = orphan_end = capped = False
    first_ts = last_ts = None
    for count, line in enumerate(text.split("\n"), 1):
        if count > MAX_LINES:
            capped = True
            break
        stamp, separator, payload = line.rstrip("\r").partition("  ")
        if not separator:
            continue
        ts = clock(stamp)
        if ts is None:
            continue
        if first_ts is None:
            first_ts = ts
        last_ts = max(last_ts, ts) if last_ts is not None else ts
        comma = payload.find(",")
        event = payload[:comma] if comma >= 0 else payload
        if event not in WANTED:
            continue
        if event == "COMBAT_LOG_VERSION":
            header = _header(_fields(payload))
            continue
        if event == "ENCOUNTER_START":
            fields = _fields(payload)
            if len(fields) >= 6 and _int(fields[1]) is not None:
                start, end, start_header, open_encounter = (ts, fields), None, header, True
                window, fallback = [(ts, event, payload)], None
            continue
        if window is None:
            orphan_end = orphan_end or event == "ENCOUNTER_END"
            fallback.append((ts, event, payload))
            while fallback[0][0] < ts - FALLBACK_SECONDS:
                fallback.popleft()
            continue
        if open_encounter:
            window.append((ts, event, payload))
            if event == "ENCOUNTER_END":
                fields = _fields(payload)
                if len(fields) >= 2 and _int(fields[1]) == _int(start[1][1]):
                    end, open_encounter = (ts, fields), False
    return {"header": header, "start": start, "end": end, "start_header": start_header,
            "window": window, "fallback": fallback, "orphan_end": orphan_end, "capped": capped,
            "first_ts": first_ts, "last_ts": last_ts}


def _damage(fields, layout):
    """Decode one damage line under a candidate layout, or None when it does not validate."""
    adv_len, base_amount = layout
    event = fields[0]
    size = DAMAGE_EVENTS[event]
    at = 9 + size + adv_len
    if len(fields) < at + (4 if base_amount else 3) or len(fields) < 9:
        return None
    amount = _int(fields[at])
    if amount is None or amount < 0:
        return None
    if base_amount:
        base = _int(fields[at + 1])
        if base is None or base < 0:
            return None
        at += 1
    overkill, school = _int(fields[at + 1]), _int(fields[at + 2])
    if overkill is None or overkill < -1 or school is None or not 1 <= school <= 127:
        return None
    hp, kind_at = None, 9
    if adv_len:
        adv = 9 + size
        if event == "ENVIRONMENTAL_DAMAGE" and not _guid_like(fields[adv]):
            # Some builds log the environmental type after the advanced block instead of before it.
            adv, kind_at = 9, 9 + adv_len
        if not _guid_like(fields[adv]):
            return None
        current, maximum = _int(fields[adv + 2]), _int(fields[adv + 3])
        if current is None or maximum is None or maximum <= 0 or not 0 <= current <= maximum:
            return None
        if fields[adv] == fields[5]:
            hp = (current, maximum)
    if event == "SWING_DAMAGE":
        spell_id, spell = None, "Melee"
    elif event == "ENVIRONMENTAL_DAMAGE":
        spell_id, spell = None, (fields[kind_at] or "Environment").title()
    else:
        spell_id, spell = _int(fields[9]), fields[10] or "Unknown spell"
    return {"src": fields[1], "src_name": fields[2], "dst": fields[5], "spell_id": spell_id,
            "spell": spell, "amount": amount, "overkill": overkill if overkill > 0 else None,
            "hp": hp, "environment": event == "ENVIRONMENTAL_DAMAGE"}


def _witness(casts, lengths):
    """SPELL_CAST_SUCCESS has no suffix, so its field count names the advanced block length.

    Damage lines alone cannot separate (k, baseAmount) from (k + 1, no baseAmount).
    """
    counts = {}
    for fields in casts:
        n = len(fields) - 12
        if n in lengths and _guid_like(fields[12]):
            counts[n] = counts.get(n, 0) + 1
    if not counts:
        return None
    best = max(counts, key=counts.get)
    return best if counts[best] >= 0.98 * len(casts) else None


def _detect(lines, casts, advanced):
    """Score each candidate over the window's damage lines; accept only a clear winner."""
    candidates = [layout for layout in LAYOUTS if advanced is None or (layout[0] > 0) == advanced]
    witness = _witness(casts, {adv for adv, _ in candidates if adv})
    if witness:
        candidates = [layout for layout in candidates if layout[0] == witness]
    total = len(lines)
    allowed = total * 0.10  # more failures than this cannot reach the 0.90 runner-up bar
    fails = dict.fromkeys(candidates, 0)
    live = list(candidates)
    for fields in lines:
        for layout in tuple(live):
            if _damage(fields, layout) is None:
                fails[layout] += 1
                if fails[layout] > allowed:
                    live.remove(layout)
    ranked = sorted(((1 - fails[layout] / total, layout) for layout in live), reverse=True)
    if not ranked:
        return None, 0.0, witness
    best, runner = ranked[0][0], (ranked[1][0] if len(ranked) > 1 else 0.0)
    clear = (best >= 0.98 and runner < 0.90) if total >= 20 else (best == 1.0 and runner < 1.0)
    return (ranked[0][1] if clear else None), best, witness


def _clean(value, realms=()):
    text = CONTROL.sub("", value or "").strip()
    for realm in realms:
        text = text.replace("-" + realm, "")
    return text[:NAME_LIMIT] or None


def _seconds(value):
    value = max(0, int(round(value)))
    return f"{value // 60}:{value % 60:02d}"


def _count(number, noun):
    return f"{number:,} {noun}" + ("" if number == 1 else "s")


def _spell_label(spell, spell_id):
    return f"{spell} ({spell_id})" if spell_id is not None else spell


def _labels(records, include_names, own_name):
    """Aliases in order of first appearance as source or destination."""
    own = own_name.split("-")[0].strip().casefold() if own_name else None
    labels, realms, used, number = {}, set(), set(), 0
    for fields in records:
        for guid, name in ((fields[1], fields[2]), (fields[5], fields[6])):
            if not guid or not guid.startswith("Player-") or guid in labels:
                continue
            short, _, realm = (name or "").partition("-")
            if realm:
                realms.add(realm)
            short = _clean(short)
            if own and short and short.casefold() == own:
                label = "You"
            elif include_names and short:
                label = short
            else:
                number += 1
                label = f"Player {number}"
            base, extra = label, 1
            while label in used:
                extra += 1
                label = f"{base} ({extra})"
            used.add(label)
            labels[guid] = label
    return labels, realms


def _source(hit, labels, realms):
    guid = hit["src"]
    if hit["environment"]:
        return "environment"
    if guid and guid.startswith("Player-"):
        return labels.get(guid, "a player")
    if guid and guid.startswith("Pet-"):
        return "a player's pet"
    if guid and guid.startswith(NPC_PREFIXES):
        return _clean(hit["src_name"], realms) or "an NPC"
    return "no source recorded"


def _death(guid, at, hits, times, previous, labels, realms):
    """Observations for one death: the hits since the player's previous death, up to the death."""
    lo = bisect_right(times, previous) if previous is not None else 0
    segment = hits[lo:bisect_right(times, at)]
    blow = next((hit for hit in reversed(segment) if hit["overkill"]), None)
    basis = "overkill"
    if blow is None and segment:
        blow, basis = segment[-1], "last hit, no overkill recorded"
    final = [hit for hit in segment if hit["ts"] >= at - FINAL_WINDOW]
    by_spell = {}
    for hit in final:
        key = (hit["spell_id"], hit["spell"])
        by_spell[key] = by_spell.get(key, 0) + hit["amount"]
    hp = next((hit["hp"] for hit in reversed(final) if hit["hp"] and hit["ts"] <= at - HP_LEAD), None)

    def describe(hit):
        return {"spell": _clean(hit["spell"], realms) or "Unknown spell", "spell_id": hit["spell_id"],
                "source": _source(hit, labels, realms), "amount": hit["amount"]}
    return {
        "who": labels.get(guid, "a player"),
        "killing_blow": ({**describe(blow), "overkill": blow["overkill"], "basis": basis} if blow else None),
        "final_10s": {"total": sum(by_spell.values()),
                      "top_spells": [{"spell": _clean(spell, realms) or "Unknown spell", "spell_id": spell_id,
                                      "total": total}
                                     for (spell_id, spell), total in sorted(by_spell.items(),
                                                                            key=lambda item: -item[1])[:3]]},
        "last_hits": [{**describe(hit), "seconds_before": round(at - hit["ts"], 1),
                       "overkill": bool(hit["overkill"])} for hit in reversed(segment[-MAX_LAST_HITS:])],
        "hp_percent_3s_before": round(100 * hp[0] / hp[1]) if hp else None,
        "_blow_key": (blow["spell_id"], blow["spell"]) if blow else None,
    }


def _analyse(window, start_ts, layout_info, include_names, own_name, gaps):
    parsed = [(ts, event, _fields(payload)) for ts, event, payload in window
              if event in DAMAGE_EVENTS or event in ("UNIT_DIED", "SPELL_CAST_SUCCESS")]
    damage = [(ts, fields) for ts, event, fields in parsed if event in DAMAGE_EVENTS and len(fields) >= 9]
    casts = [fields for _, event, fields in parsed if event == "SPELL_CAST_SUCCESS" and len(fields) >= 13]
    deaths = [(ts, fields) for ts, event, fields in parsed if event == "UNIT_DIED" and len(fields) >= 9]
    labels, realms = _labels([fields for _, event, fields in parsed if event != "SPELL_CAST_SUCCESS"
                              and len(fields) >= 9], include_names, own_name)
    layout, score, witness = (None, 0.0, None)
    if damage:
        layout, score, witness = _detect([fields for _, fields in damage], casts, layout_info["advanced"])
        if layout is None:
            return None, labels
    hits_by_player, rejected = {}, 0
    for ts, fields in damage:
        hit = _damage(fields, layout)
        if hit is None:
            rejected += 1
            continue
        if hit["dst"] and hit["dst"].startswith("Player-"):
            hit["ts"] = ts
            hits_by_player.setdefault(hit["dst"], []).append(hit)
    if rejected:
        gaps.append(f"{rejected:,} damage lines did not match the detected layout and were left out.")
    if not damage:
        gaps.append("No damage events were found in the examined window, so no killing blows or damage totals "
                    "are available.")
    elif layout[0] == 0 and layout_info["advanced"] is not False:
        gaps.append("The log has no advanced fields, so HP before death is unknown.")
    for hits in hits_by_player.values():
        hits.sort(key=lambda hit: hit["ts"])  # stable, so same-time lines keep log order
    times = {guid: [hit["ts"] for hit in hits] for guid, hits in hits_by_player.items()}
    all_deaths, previous = [], {}
    for ts, fields in deaths:
        guid = fields[5]
        if not guid or not guid.startswith("Player-"):
            continue
        record = _death(guid, ts, hits_by_player.get(guid, []), times.get(guid, []), previous.get(guid),
                        labels, realms)
        record["at_s"] = round(ts - start_ts, 1)
        previous[guid] = ts
        all_deaths.append(record)
    spells = {}
    for hits in hits_by_player.values():
        for hit in hits:
            key = (hit["spell_id"], hit["spell"])
            row = spells.setdefault(key, {"spell": _clean(hit["spell"], realms) or "Unknown spell",
                                          "spell_id": hit["spell_id"], "total": 0, "hits": 0,
                                          "players": set(), "killing_blows": 0})
            row["total"] += hit["amount"]
            row["hits"] += 1
            row["players"].add(hit["dst"])
    for record in all_deaths:
        key = record.pop("_blow_key")
        if key in spells:
            spells[key]["killing_blows"] += 1
    table = sorted(spells.values(), key=lambda row: (-row["total"], row["spell"]))
    for row in table:
        row["players_hit"] = len(row.pop("players"))
    detected = None
    if layout is not None:
        detected = {"advanced_fields": layout[0], "base_amount": layout[1], "score": round(score, 4),
                    "damage_lines": len(damage), "rejected_lines": rejected,
                    "advanced_length_from": "cast events" if witness else "damage events"}
    return {"layout": detected, "deaths": all_deaths[:MAX_DEATHS],
            "deaths_not_shown": max(0, len(all_deaths) - MAX_DEATHS),
            "damage_taken_by_spell": table[:TOP_SPELLS], "spells_not_shown": max(0, len(table) - TOP_SPELLS),
            "totals": {"player_deaths": len(all_deaths), "players_seen": len(labels)}}, labels


def _death_lines(index, death):
    lines = [f"{index}. {death['who']} died at {death['at_s']:.1f} s"]
    blow = death["killing_blow"]
    if blow:
        detail = (f"{blow['amount']:,} damage, {blow['overkill']:,} overkill" if blow["overkill"]
                  else f"{blow['amount']:,} damage ({blow['basis']})")
        lines.append(f"   Killing blow: {_spell_label(blow['spell'], blow['spell_id'])} from {blow['source']}, "
                     f"{detail}")
    else:
        lines.append("   Killing blow: no damage to this player was recorded before the death")
    final = death["final_10s"]
    top = "; ".join(f"{_spell_label(row['spell'], row['spell_id'])} {row['total']:,}" for row in final["top_spells"])
    lines.append(f"   Damage taken in the final 10 s: {final['total']:,}" + (f" (top: {top})" if top else ""))
    hp = death["hp_percent_3s_before"]
    lines.append("   HP about 3 s before death: "
                 + (f"{hp}%" if hp is not None else "unknown (advanced combat logging off or no sample)"))
    if death["last_hits"]:
        lines.append("   Last hits, newest first:")
        lines.extend(f"     {hit['seconds_before']:.1f} s before: {_spell_label(hit['spell'], hit['spell_id'])} "
                     f"from {hit['source']}, {hit['amount']:,}" + (", overkill" if hit["overkill"] else "")
                     for hit in death["last_hits"])
    return lines


def _size(lines):
    return sum(len(line.encode("utf-8")) + 1 for line in lines)


def _compose(head, digest, gaps):
    """Join sections within TEXT_LIMIT bytes; deaths give way first, with an explicit count."""
    tail = []
    if digest is not None:
        table = digest["damage_taken_by_spell"]
        if table:
            tail.append("")
            tail.append("Damage taken by players, by spell:")
            tail.extend(f"- {_spell_label(row['spell'], row['spell_id'])}: {row['total']:,} total, "
                        f"{_count(row['hits'], 'hit')}, {_count(row['players_hit'], 'player')} hit, "
                        f"{_count(row['killing_blows'], 'killing blow')}" for row in table)
            if digest["spells_not_shown"]:
                tail.append(f"- {digest['spells_not_shown']:,} more spells not shown")
    if gaps:
        tail += ["", "Coverage notes:"] + [f"- {gap}" for gap in gaps]
    body = list(head)
    if digest is not None and digest["deaths"]:
        body += ["", "Player deaths, in order:"]
        budget = TEXT_LIMIT - _size(body) - _size(tail) - 80
        shown = 0
        for index, death in enumerate(digest["deaths"], 1):
            block = _death_lines(index, death)
            if _size(block) > budget:
                break
            body += block
            budget -= _size(block)
            shown = index
        hidden = digest["totals"]["player_deaths"] - shown
        if hidden:
            body.append(f"{hidden:,} more deaths not shown")
    lines = body + tail
    while _size(lines) > TEXT_LIMIT + 1 and len(lines) > 1:  # last resort; sections above are bounded
        lines = lines[:-2] + ["Further lines not shown (text limit)."]
    return "\n".join(lines)


def last_encounter_digest(path, *, include_names=False, own_name=None, max_bytes=MAX_BYTES):
    """Digest the last encounter in the log at `path`; returns {"status", "text", "data", "gaps"}."""
    max_bytes = max(1, int(max_bytes))
    text, offset, bytes_read = _read_tail(path, max_bytes)
    scan = _scan(text)
    gaps = []
    if offset:
        amount = (f"{max_bytes / 1_000_000:g} MB" if max_bytes >= 1_000_000 else f"{max_bytes:,} bytes")
        gaps.append(f"Only the last {amount} of the log were read; earlier lines were not examined.")
    if scan["capped"]:
        gaps.append(f"Reading stopped after {MAX_LINES:,} lines; later lines were not examined.")
    read = {"truncated": bool(offset), "bytes_read": bytes_read}
    if scan["last_ts"] is None:
        gaps.append("No timestamped combat log lines were found in the part that was read.")
        return {"status": "empty", "text": "The combat log has no readable fight data yet.",
                "data": {"read": read}, "gaps": gaps}

    header = scan["start_header"] if scan["start"] else scan["header"]
    header = header or {"version": None, "build": None, "project": None, "advanced": None}
    if scan["header"] is None and scan["start_header"] is None:
        gaps.append("The log header (COMBAT_LOG_VERSION) was not in the part that was read, so the log version "
                    "and advanced-logging state are unknown.")
    elif header["advanced"] is False:
        gaps.append("Advanced combat logging was off, so HP before death is unknown.")

    encounter = None
    if scan["start"]:
        start_ts, fields = scan["start"]
        window = scan["window"]
        encounter = {"id": _int(fields[1]), "name": _clean(fields[2]) or "Unknown encounter",
                     "difficulty_id": _int(fields[3]), "group_size": _int(fields[4]),
                     "instance_id": _int(fields[5]) if len(fields) > 5 else None}
        if scan["end"]:
            end_ts, end = scan["end"]
            success = end[5] if len(end) > 5 else None
            encounter["result"] = {"1": "kill", "0": "wipe"}.get(success, "unknown")
            fight_ms = _int(end[6]) if len(end) > 6 else None
            if fight_ms is not None and fight_ms >= 0:
                encounter["duration_s"], encounter["duration_source"] = round(fight_ms / 1000, 1), "fightTime"
            else:
                encounter["duration_s"], encounter["duration_source"] = round(end_ts - start_ts, 1), "timestamps"
            status = "ok"
        else:
            encounter["result"] = "unknown"
            encounter["duration_s"] = round(scan["last_ts"] - start_ts, 1)
            encounter["duration_source"] = "timestamps, encounter not ended"
            gaps.append("The last encounter has no ENCOUNTER_END before the end of the log; it may still be in "
                        "progress or the log was cut off, so the result is unknown.")
            status = "incomplete"
        window_info = {"kind": "encounter"}
    else:
        start_ts = max(scan["first_ts"], scan["last_ts"] - FALLBACK_SECONDS)
        window = [record for record in scan["fallback"] if record[0] >= start_ts]
        status = "no_encounter_markers"
        gaps.append(f"No ENCOUNTER_START was found, so the last {FALLBACK_SECONDS} seconds before the final "
                    "timestamp were examined instead; this window may not match a single pull.")
        if scan["orphan_end"]:
            gaps.append("An ENCOUNTER_END appeared without its ENCOUNTER_START in the part that was read.")
        window_info = {"kind": "fallback", "seconds": round(scan["last_ts"] - start_ts, 1)}
    gaps.append("Only damage events and player deaths are examined; healing, absorbs, auras, and avoidance are "
                "not counted, and damage to pets and NPCs is excluded from the damage-taken table.")

    log_info = {key: header[key] for key in ("version", "build", "project", "advanced")}
    digest, _ = _analyse(window, start_ts, log_info, include_names, own_name, gaps)
    head = []
    if encounter:
        head.append(f"Encounter: {encounter['name']} (ID {encounter['id']}), difficulty {encounter['difficulty_id']}, "
                    f"group size {encounter['group_size']}")
        if digest is not None:
            head.append(f"Result: {encounter['result']}; duration {_seconds(encounter['duration_s'])} "
                        f"(from {encounter['duration_source']})")
    else:
        head.append(f"No encounter markers: the last {_seconds(window_info['seconds'])} of logged combat "
                    "(times are from the start of that window)")
    advanced = {True: "on", False: "off"}.get(log_info["advanced"], "unknown")
    head.append(f"Log: version {log_info['version'] or 'unknown'}, build {log_info['build'] or 'unknown'}, "
                f"advanced logging {advanced}")
    if digest is None:
        status = "unsupported_layout"
        gaps.insert(0, f"The damage field layout of this log (combat log version {log_info['version'] or 'unknown'}, "
                       f"build {log_info['build'] or 'unknown'}) was not recognised, so no damage, death, or HP "
                       "figures are reported.")
        data = {"status": status, "log": log_info, "encounter": encounter and
                {"name": encounter["name"], "id": encounter["id"]}, "window": window_info, "layout": None,
                "read": read}
        return {"status": status, "text": _compose(head, None, gaps), "data": data, "gaps": gaps}
    totals = digest["totals"]
    head.append(f"Totals: {_count(totals['player_deaths'], 'player death')}, "
                f"{_count(totals['players_seen'], 'player')} seen")
    if digest["layout"]:
        layout = digest["layout"]
        head.append(f"Damage layout: {layout['advanced_fields']} advanced fields, base amount "
                    f"{'present' if layout['base_amount'] else 'absent'}")
    data = {"status": status, "log": log_info, "encounter": encounter, "window": window_info, "read": read,
            **digest}
    return {"status": status, "text": _compose(head, digest, gaps), "data": data, "gaps": gaps}
