# Quest companion

`python -m wow_helper quests` lists the quests in your log and suggests an order to do them in. It is advice for you to read. It never presses keys, and quest data never feeds the assistive-input command.

## How it gets the data

The game does not let other programs read the quest log, so a small addon copies it out:

1. `wow_addon/WoWCompanion/` is a read-only addon. On login, zone changes, and quest-log updates it copies the quest log into its SavedVariables table, `WoWCompanionDB`. It also saves the completed quest IDs and the quests available on the current map (see below). It records each quest's ID, title, level, suggested group size, quest-log header (usually the zone), complete and failed flags, and objectives with their counts. It also records the player's level, class, XP, and zone. On modern clients it adds the distance in yards to each quest's objective area. Since addon 0.4.0 it also records the client's version, build, and interface number from `GetBuildInfo`, and which API each feature read, so the helper can report what the client actually offered. It stores no character or realm name, prints nothing, and calls no action, chat, targeting, or settings API. `tests/test_no_input.py` scans it for those calls.
2. The game writes that table to `WTF/Account/<ID>/SavedVariables/WoWCompanion.lua` only on `/reload` or logout. The data is therefore a snapshot, and every answer says how old it is.
3. `wow_helper/savedvars.py` reads the file with the restricted grammar from [PLAN.md](PLAN.md) section 5.1. Nothing from disk is executed. The file must stay unchanged for one second before it is trusted, because the game may still be writing it.

`wow_helper/wtf.py` finds the install through the Windows uninstall registry, the default Program Files folders, or `--wow-root`. When several game folders (`_retail_`, `_classic_`, `_classic_beta_`, ...) have a snapshot, it uses the most recently written one. The account folder name and local paths are never printed.

Use `--flavor` with `quests` or `character` to read only one game edition. The helper chooses the newest snapshot within that edition and refuses the request if none exists; it never falls back to another edition. This choice applies only to the current report and is not remembered. It does not select a character or account within that edition.

## Setup

```console
python -m wow_helper install-addon            # or --wow-root "<install folder>" --flavor _classic_beta_
```

This copies the two addon files into `Interface/AddOns/WoWCompanion` in each game folder that has a `WTF` folder, meaning the game has run there. Then enable **WoW Companion** at character select. If the client calls it out of date, tick "Load out of date AddOns". The `.toc` interface number `16001` was confirmed on Classic Forever beta client 1.60.1, build 70338, on 2026-10-10; `120001` for retail remains unverified. Then `/reload` once in game.

The current addon has no visible windows, buttons, or slash commands. It exports snapshots in the background. Use `check-snapshot` to verify that it is working; the separate [desktop chat workspace](CHAT.md) is launched from the helper CLI, not from WoW.

## Use

```console
python -m wow_helper quests --text     # readable lines, suitable for speech
python -m wow_helper quests            # JSON: player, plan steps, warnings, snapshot age
python -m wow_helper quests --flavor _classic_beta_ --text
python -m wow_helper character --flavor _retail_ --text
```

An explicit `--file` already selects the snapshot; combining it with `--flavor` is refused.

By voice, a question such as "what quests am I on" goes to Claude, which runs the command above. It never goes through the teleport path, which only takes spell requests. `/reload` first for current data.

## How the order is chosen

The rules are deliberately simple and visible in `wow_helper/quests.py`:

1. **Turn in** completed quests, nearest zone first.
2. **Restart** failed quests: abandon them and pick them up again.
3. **Finish** doable quests. Quests in your current zone come first, then quests with the most progress, then the nearest by distance where the client reports it.
4. **Finish** gray quests last: their level is at or below the classic con-colour threshold, so they give little XP.
5. **Later**: quests five or more levels above you, and orange group quests.

Each step lists the remaining objectives and a Wowhead link. The link uses Wowhead's classic section for every client except `_retail_`. Whether Forever quests resolve there is unverified.

Warnings cover a snapshot older than 15 minutes, collapsed quest-log headers (the classic API hides the quests under them), and an addon data version that does not match the helper.

## Quests to pick up, and quests already done

`quests` also lists quests you can pick up on your current map, and counts the quests this character has completed. Both come only from the game's own API:

- **Completed quests:** `C_QuestLog.GetAllCompletedQuestIDs` on Forever and retail. Older classic clients use `GetQuestsCompleted`. The addon saves the quest IDs, and the helper uses them to leave finished quests out of the pick-up list.
- **Quests to pick up:** `C_QuestLine.GetAvailableQuestLines` for the map the player is on, found with `C_Map.GetBestMapForUnit`. The addon saves each quest's ID, title, quest-line name, map coordinates, and daily flag. The helper leaves out quests already in the log or completed, and shows coordinates as percentages, the same way map addons do. The first read of a map asks the game to load its quest lines, and `QUESTLINE_UPDATE` then triggers a fresh copy.

```console
python -m wow_helper quests --text
# ...
# To pick up here: Synthetic Welcome (at 45.1, 62); Test Board Notice.
# 3 quests completed on this character.
```

An empty list is reported as "the game lists no quests to pick up on this map". It doesn't prove there are none, because the game may only list quests that belong to a quest line. A client or addon version without these calls just leaves the lines out.

### Why there is no quest database

Quest helpers such as Questie, Guidelime, and RestedXP answer "what can I pick up" from their own databases of quest givers, prerequisites, and level ranges. Blizzard has no API that returns every available quest. We checked on 2026-09-28 and found no database we could reuse cleanly:

- Questie's data comes from server-emulator databases, Wowhead scraping, and extracted game files. That clashes with this repo's rule against Blizzard and Wowhead content.
- Its license is unclear: CurseForge says GPLv3, the GitHub repo has no license file, and QuestieDB has no license.
- Its Forever data is converted Classic data, so the new Forever quests are probably missing.

So the helper uses only what the game reports. For the full picture of what to pick up, use Questie or Wowhead in game alongside it. Reading a local Questie install would be a separate operator decision.

## Character status

The same snapshot also holds character status: gold, rested XP, equipped items (slot, item ID, item level, and durability; no item names), and free bag slots. The addon refreshes it on money, equipment, durability, and bag changes as well as the quest-log events. Events a client does not know are skipped.

```console
python -m wow_helper character --text   # "Character status from just now: 12g 34s 56c gold, ..."
python -m wow_helper character          # JSON, with a Wowhead link per item
```

It warns when the most worn item is at 25% durability or less, and when two or fewer bag slots are free. The average item level leaves out the shirt and tabard. A snapshot from an addon version without character status is refused with a request to update the addon and `/reload`.

### Commands through the addon: not built

An addon cannot take commands from the helper. The game gives addons no way to read files or sockets while it runs, and spells can only be cast from a key or click the player makes. The legitimate pattern is an addon that owns secure action buttons with key bindings, pressed by the helper's one explicit key chord. That pattern needs `SecureActionButtonTemplate` and `SetBinding`, which `tests/test_no_input.py` bans under the operator decision of 2026-09-27 ("addon automation remain[s] excluded"). Building it is the operator's call and would change that rule first.

## Checking the first real snapshot

`python -m wow_helper check-snapshot --text` reads the newest snapshot (or one edition with `--flavor`, or one file with `--file`) and reports, check by check, which of the helper's assumptions the game client confirmed. Each line is `confirmed`, `missing`, or `mismatch`, with the fix spelled out where there is one. It takes no action and sends no input.

The output names counts, the client's version, build, and interface number, and the API each feature came from. It never prints a character, realm, account, zone, quest title, or path, so it can be pasted into an issue or a commit message as evidence.

To run the first live check:

1. `python -m wow_helper install-addon`, enable **WoW Companion** at character select, and tick "Load out of date AddOns" if the client asks.
2. Log in on a character with at least one quest that has a counter, then `/reload`.
3. `python -m wow_helper check-snapshot --text`.

What each result means:

- `toc_interface` mismatch: the client's interface number is not in the `.toc`. The addon still loads with "Load out of date AddOns" ticked; update the `## Interface:` line with the reported number.
- `distance` missing on a client that reported the modern API: the client has no `GetDistanceSqToQuest`, or no quest objective is on the current continent. The `api_sources` line says which.
- `available_quests` confirmed with 0 quests: the API answered but listed nothing. Compare with the map before concluding Forever does not fill it.
- `objective_counts` missing with objectives present: the classic leaderboard API is in use and counts come only from the objective text.
- `addon_version` or `client_build` missing: the snapshot came from an older addon. Reinstall and `/reload`.

The check reads the same snapshot as `quests` and `character`, so a snapshot that passes here is the one they report from.

## What has been verified

- Parser, advice order, CLI, discovery, addon install, and the snapshot check are covered by automated tests. The tests use the synthetic fixtures `tests/fixtures/savedvariables_quests.lua` and `tests/fixtures/savedvariables_check.lua` and fake install folders.
- The addon's Lua was syntax-checked with `luaparser`.
- **Live check on 2026-10-10:** addon 0.4.0 was installed in `_classic_beta_` on Windows. After the operator enabled it and ran `/reload`, `check-snapshot --flavor _classic_beta_ --text` reported 13 confirmed, 0 missing, and 0 mismatched checks. The client reported version 1.60.1, build 70338, interface 16001, and the modern quest-log API. Quest objectives with counters, distance values, completed quest IDs, and character status were present. Both `quests --flavor _classic_beta_` and `character --flavor _classic_beta_` returned `status: ok` without warnings; the character report included money, rested XP, gear, durability, and bag counts. The real snapshot remains local and is not a test fixture.
- **Still unverified:** the available-quest API returned an empty list in this check, so a populated result and coverage of quests visible in game need testing. The presence of objective counters, distances, and character stats does not establish their accuracy against the in-game display. Retail and other clients, the classic text-only objective fallback, and Forever quest links have not been verified by this live check. Chat does not yet attach quest or character reports automatically.
