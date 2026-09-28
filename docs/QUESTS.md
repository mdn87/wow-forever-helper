# Quest companion

`python -m wow_helper quests` lists the quests in your log and suggests an order to do them in. It is advice for you to read. It never presses keys, and quest data never feeds the assistive-input command.

## How it gets the data

The game does not let other programs read the quest log, so a small addon copies it out:

1. `wow_addon/WoWCompanion/` is a read-only addon. On login, zone changes, and quest-log updates it copies the quest log into its SavedVariables table, `WoWCompanionDB`. It records each quest's ID, title, level, suggested group size, quest-log header (usually the zone), complete and failed flags, and objectives with their counts. It also records the player's level, class, XP, and zone. On modern clients it adds the distance in yards to each quest's objective area. It stores no character or realm name, prints nothing, and calls no action, chat, targeting, or settings API. `tests/test_no_input.py` scans it for those calls.
2. The game writes that table to `WTF/Account/<ID>/SavedVariables/WoWCompanion.lua` only on `/reload` or logout. The data is therefore a snapshot, and every answer says how old it is.
3. `wow_helper/savedvars.py` reads the file with the restricted grammar from [PLAN.md](PLAN.md) section 5.1. Nothing from disk is executed. The file must stay unchanged for one second before it is trusted, because the game may still be writing it.

`wow_helper/wtf.py` finds the install through the Windows uninstall registry, the default Program Files folders, or `--wow-root`. When several game folders (`_retail_`, `_classic_`, `_classic_beta_`, ...) have a snapshot, it uses the most recently written one. The account folder name and local paths are never printed.

## Setup

```console
python -m wow_helper install-addon            # or --wow-root "<install folder>" --flavor _classic_beta_
```

This copies the two addon files into `Interface/AddOns/WoWCompanion` in each game folder that has a `WTF` folder, meaning the game has run there. Then enable **WoW Companion** at character select. If the client calls it out of date, tick "Load out of date AddOns". The `.toc` interface numbers (`16001` for Forever, `120001` for retail) are unverified guesses. Then `/reload` once in game.

## Use

```console
python -m wow_helper quests --text     # readable lines, suitable for speech
python -m wow_helper quests            # JSON: player, plan steps, warnings, snapshot age
```

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

## What has been verified

- Parser, advice order, CLI, discovery, and addon install are covered by automated tests. The tests use the synthetic fixture `tests/fixtures/savedvariables_quests.lua` and fake install folders.
- The addon's Lua was syntax-checked with `luaparser`.
- **Not verified:** the addon has not been loaded in any game client. That leaves the API field names, the `.toc` interface numbers, the objective text format, and the distance values unconfirmed. The first real `/reload` is the test.
