# Combat log analyzers and the between-pulls idea loop

Status: concept, proposed 2026-10-30. Nothing here is implemented, and no real Forever combat log has been read. This document takes an idea from the operator to a shape that can be reviewed and scheduled. It extends the queued [F15 post-fight coaching](UPGRADE_IMPLEMENTATION_PLAN.md#f15-post-fight-coaching) and [F18 local read-only agent tools](UPGRADE_IMPLEMENTATION_PLAN.md#f18-local-read-only-agent-tools) items and resolves the combat-log question left open in [PLAN.md section 5.3](PLAN.md).

## The idea

A raid wipes and someone asks "what's killing everyone so fast?" The helper has no view for that. The fight data already exists, so a new view should be possible during the run back: the player says the question aloud, an agent builds the analysis, the player checks it against the pull that just happened, and it runs on every pull after that. No addon rebuild, no `/reload`, no companion restart.

Two things make this worth building:

1. **A smart log of what happened.** Record each pull from the data the game already writes, then review it: deaths, damage taken, the player's own casting, and how a pull differs from the player's best attempt or a declared plan.
2. **New analyses on demand.** Ideas raised mid-session become working views between pulls, with the player deciding what goes live.

This is not a rotation helper. Addons that predict the next button already exist. This reviews what happened, after the pull, and compares attempts.

## Constraints

### What addons can no longer see

Midnight's addon rules, per [Warcraft Wiki's 12.0.0 API changes](https://warcraft.wiki.gg/wiki/Patch_12.0.0/Planned_API_changes) and [COMBAT_LOG_EVENT](https://warcraft.wiki.gg/wiki/COMBAT_LOG_EVENT):

- Combat log events are not available to addons. Registering for them is forbidden.
- Aura and cooldown details are secret values in combat and during encounters. Creature names, GUIDs, and IDs are secret in instances.
- Addon messaging and chat reading are restricted during encounters, keystone runs, and PvP matches.

**Forever:** a fan site reports a Blizzard Discord remark that Midnight's restrictions apply to Forever ([source](https://wowforevertierlist.com/addons/restrictions)). This is reported, not verified. The site says it has not tested the restrictions on a Forever build. Treat the rules above as the expected case.

The companion addon therefore cannot be the fight data source. It also cannot display live results: addons read no files and open no sockets, and SavedVariables reach disk only on reload or logout.

### What the game still writes

The client still writes `Logs/WoWCombatLog.txt` after `/combatlog`. Advanced combat logging (System, Network, or the `advancedCombatLogging` CVar) adds current HP, max HP, map position, and level or item level to unit events. Warcraft Logs and similar tools read the same file ([WowCoach](https://wowcoach.gg/blog/how-to-enable-combat-logging-wow)). The file is outside the addon sandbox, so a desktop process can read it while the game runs.

Unverified for Forever: which events and advanced fields appear, whether `ENCOUNTER_START` and `ENCOUNTER_END` lines are present as they are in Retail logs, and how quickly new lines reach disk. Logging must be re-enabled after each login or reload.

### Rules this project already has

- No game input, automation, hooks, or memory reading ([AGENTS.md](../AGENTS.md)).
- No arbitrary script execution. The live loop below is designed around this rule; the Python option needs an explicit exception.
- `WoWCombatLog.txt` and anything derived from real play is never committed. `.gitignore` already covers `WoWCombatLog*.txt`, `Logs/`, and SQLite files.

## How it works

```text
WoWCombatLog.txt --> Log reader --> Pull store (SQLite, local) --> Analyzers --> Fight card
                      (tail)        pulls, units, events, deaths    built-in      (companion window /
                                                                   + specs        second display)
```

Everything runs on the Windows PC that runs the game, inside the existing companion. No addon change is required.

### Log reader

- A background worker (`pythonw.exe`, `CREATE_NO_WINDOW`) follows the selected edition's log by position and size, survives rotation or deletion, and never writes to the file.
- Lines are parsed by a bounded CSV-style parser that tolerates unknown subevents and field counts, and records the `COMBAT_LOG_VERSION` header.
- Pulls start and end on `ENCOUNTER_START` and `ENCOUNTER_END` where present, with an idle-gap fallback for trash and open-world fights.
- Reading starts only when the player enables it, and Stop is available from every companion window. It does not turn on combat logging; that stays a player action.

### Pull store

A local SQLite database in the ignored data directory, written in WAL mode so analyzers can read while the reader writes.

| Table | Contents |
| --- | --- |
| `sessions` | Log file identity, edition, log version, first and last line time |
| `pulls` | Encounter ID and name, difficulty, group size, start, end, success, attempt number |
| `units` | Per-pull units by GUID: name, type (player, pet, NPC), class where known |
| `events` | Time, subevent, source, target, spell ID, school, amount, overkill, absorbed, HP after, max HP, x, y |
| `deaths` | Each player death with its preceding 10 seconds of damage and healing, precomputed |
| `findings` | Analyzer output per pull with evidence event IDs |

Retention is configurable per session. Raw log files stay where the game writes them; the store holds parsed rows only.

### Analyzers

An analyzer takes one pull, optionally earlier pulls of the same encounter, and returns findings. Each finding names its evidence rows, so the Fight card can show why it says what it says. Three kinds:

1. **Built-in analyzers** ship in the repo with synthetic fixtures and tests: deaths, avoidable damage taken, the player's own casting gaps, and buff or cooldown usage from the player's own cast events.
2. **Analyzer specs** are declarative JSON documents interpreted by a fixed engine: filter events, choose a time window relative to an anchor (death, cast, pull start), group, aggregate, threshold, and phrase the result. They contain no code. This is the default output of the live loop.
3. **Python analyzers** are reserved for logic a spec cannot express. They arrive through a normal pull request with synthetic fixtures, never mid-raid, unless the operator later grants the exception described below.

### Fight card

A new activity card, available on the [WoW companion displays](DIAS_INTEGRATION_PLAN.md). After each pull ends it shows enabled analyzers' findings, a comparison with the previous attempt, and a comparison with the player's best attempt. Selecting a finding expands its evidence. **Ask about this pull** prepares a conversation with the findings, never the raw log. Saving to Journal reuses existing reviewed saving.

The card updates when a pull ends, not during combat. See [Risks](#risks-and-open-questions) for why.

### Divergence from the ideal

"Ideal" means one of two things the player chooses, never a simulation:

- **Own best attempt:** the successful or longest pull of the same encounter. Compare casting gaps, cooldown use relative to pull start, damage taken by spell, and death timing.
- **Declared plan:** a short player-written list such as "major cooldown in the first 5 seconds", "interrupt spell X", or "no deaths to spell Y". Each item becomes a check against the pull.

Patterns across pulls are counts and trends with the number of attempts shown: "died to spell Y in 4 of the last 5 pulls". No claim is stronger than its evidence.

## The between-pulls idea loop

1. **Ask.** Hold Keypad minus and speak, using existing [push-to-talk dictation](CHAT.md#push-to-talk-voice-input), in a new **Analyzer** chat type. The draft still needs Send.
2. **Build.** The agent reads the store schema, the spec language reference, and synthetic fixtures through a `wow-analyzer-author` skill. It writes one spec file into a staging folder. It does not receive the raw log or other players' names.
3. **Check.** The companion validates the spec against the schema, then runs it on the last recorded pull and on a synthetic fixture. Errors return to the same conversation for one revision.
4. **Preview.** The Fight card shows what the new analyzer would have said about the last pull, marked as a preview.
5. **Enable.** The player presses Enable. From the next pull it runs automatically after each encounter. Disable and delete are always available. Restarting never re-enables a disabled analyzer.
6. **Keep.** After the session, a useful spec can be promoted into the repo through a pull request with a synthetic fixture. Staged specs live in ignored local storage.

### Worked example: "What's killing everyone so fast?"

Spec in outline:

- **Anchor:** every `UNIT_DIED` for a player unit in the pull.
- **Window:** the 10 seconds before each death.
- **Collect:** damage taken by the dead player (amount, spell, source type), healing received, HP after each hit.
- **Killing blow:** the last damage event with overkill greater than zero.
- **Classify:** HP above 80 percent within 3 seconds of death means a likely burst or one-shot; otherwise likely attrition.
- **Group:** deaths by killing-blow spell, then share of damage in the final 5 seconds.

Example output on the card:

> 6 of 8 deaths: Spell X was the killing blow. 4 of those players were above 80% HP 3 seconds earlier: likely burst, check positioning or the mechanic. 2 were attrition: healing received fell in the final 5 seconds.
> Pull 7 vs pull 6: deaths to Spell X rose from 2 to 6.

"Likely" is deliberate. As F15 already requires, aggregate damage cannot establish an exact cause of death. The card states what was observed and labels the interpretation.

## AGENTS.md changes this needs

Proposed wording for operator review, in the style of the existing exceptions:

1. **Combat log reading (operator decision required).** The companion may read the game's combat log file, read-only, after the player enables reading. It never enables logging, writes to the file, or reads other game files beyond the existing allowlists. Parsed data stays in ignored local storage.
2. **Analyzer authoring sessions (operator decision required).** A companion-created Analyzer conversation may write JSON spec files to one staging folder. All other tools stay read-only. Specs are data interpreted by a fixed engine. They execute nothing, and a spec runs only after an explicit Enable.
3. **Optional, separate decision: live Python analyzers.** Allowing agent-written Python mid-session would be arbitrary script execution under the current rules. If ever granted, it needs a subprocess, an import allowlist, no file, network, or input access, review before Enable, and the acknowledgement that these checks reduce mistakes but are not a security boundary. This concept does not depend on it.

## Risks and open questions

- **Forever log contents.** Events, advanced fields, encounter markers, and naming are unverified until a real Forever log exists. Launch is November 4; raids are reported to open December 9.
- **Write delay.** How long new lines take to reach disk is unmeasured. If the game buffers heavily, a pull's data may arrive seconds after it ends. The card must show "waiting for log" rather than partial results.
- **Other raiders' data.** The log contains every player's name, class, and performance. It stays local. Agents get spell- and role-level summaries by default, with names only on the player's explicit choice per request. Nothing derived from a real log enters the repo, issues, or CI output.
- **Review versus live decision-making.** Midnight's restrictions exist to stop addons from making combat decisions for players. Reading the log after a pull, as Warcraft Logs does, is review. Showing findings during combat, timed callouts, or predicting the next mechanic from live log data would move toward what Blizzard restricted, even though it happens outside the client. This concept updates between pulls only. That is a design line, not a claim of Blizzard approval.
- **Spec language scope.** Some questions will not fit filters, windows, and aggregates. The first version should cover the death, damage-taken, and own-casting questions, and report "not expressible as a spec" rather than stretching.
- **Disk and performance.** Long raid nights produce large logs. Reader batching, store retention, and analyzer time limits need measurements on real hardware before defaults are chosen.
- **Edition differences.** Field layouts may differ between Forever, Classic, and Retail logs. The reader records log version and refuses unknown layouts instead of guessing.

## Path to integration

Each phase lands, is verified, and is documented before the next starts.

| Phase | Deliver | Done when |
| --- | --- | --- |
| 0. Decide | Operator accepts or edits this concept and the AGENTS.md wording | Exceptions 1 and 2 merged into AGENTS.md, or the concept is parked |
| 1. Log proof | Read-only parser and reader against a synthetic fixture; one real Forever log checked locally, results recorded without content | Field coverage table and measured write delay in this document |
| 2. Store and built-ins | Pull store, deaths and damage-taken analyzers, Fight card after each pull | Synthetic tests pass; one real raid night produces correct pull splits and death summaries |
| 3. Spec engine | Declarative spec language, validator, replay against stored pulls, built-ins re-expressed as specs where possible | Specs written by hand reproduce built-in results on fixtures |
| 4. Idea loop | Analyzer chat type, staging folder write grant, preview, Enable, Disable | A new spec goes from spoken idea to enabled between two pulls, on a real session |
| 5. Comparison | Best-attempt and declared-plan divergence, cross-pull trends, optional F15 Details import and F18 record access | Comparisons cite pull counts and evidence; unsupported comparisons say so |

Phase 1 is the gate. If Forever's log lacks the needed fields, the concept narrows to what the log supports before more is built.
