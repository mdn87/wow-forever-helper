# WoW: Forever Companion — pivot plan (draft)

Status: **draft for review, 2026-09-23.** Nothing here is implemented. This plan proposes retargeting the BG3 Companion prototype at *World of Warcraft: Forever* (Blizzard's Classic+ game; beta opened 2026-09-17, launch announced for 2026-11-04).

## 1. Goal

Build a second-screen companion for WoW: Forever. It explains what is on screen, suggests next steps (quests, talents, gear, dungeon prep), and keeps a local play journal. It keeps the existing architecture: a local Windows/Python/Tk panel with an existing Codex conversation as the AI, and no separate API key.

## 2. The decisive difference from BG3: no game input

**The companion must never send mouse or keyboard input to WoW.** BG3 is a single-player offline game. WoW: Forever is an online Blizzard game covered by the Battle.net EULA, which prohibits bots and third-party automation. Warden anti-cheat can detect synthetic input. Even a bounded, permissioned "Smart next move" risks the user's Battle.net account.

Consequences:
- Remove INPUT, the gesture budget, `SendInput` code paths, and "Smart system setup" menu clicking from the WoW build. Settings help becomes advice plus reading `Config.wtf`.
- **STOP** is still useful for cancelling a pending AI request.
- Screenshots (a passive screen capture) and addons (Blizzard's sanctioned Lua UI API) are the legitimate data channels.
- Open question for review: does capturing the screen with `mss` carry any detection risk? The working assumption is no, because OBS and Discord do the same thing, but this is unverified.

## 3. Data sources, in order of trust

| Source | What it gives | Evidence level |
| --- | --- | --- |
| Screenshot of the WoW window | What is visible now | Visual, can be misread |
| Companion addon `SavedVariables` (`WTF/Account/<ACCT>/SavedVariables/WoWCompanion.lua`) | Character, level, zone, quest log, gear, talents, and gold at the last `/reload` or logout | Structured, but stale between reloads |
| `WTF/Config.wtf` and per-character `config-cache.wtf` | Graphics/settings values | Configured, not live-verified |
| `Interface/AddOns/*/*.toc` | Installed addon inventory (replaces the BG3 mod-list plan) | File presence only |
| `Logs/WoWCombatLog.txt` (after `/combatlog`) | Fight events for post-fight review | Structured, opt-in |

Addons cannot write files except through SavedVariables at reload or logout. They cannot open sockets. A "live" feed is therefore impossible by design. The companion reads snapshots and must label how old each one is.

## 4. What carries over vs. what changes

Reuse largely as-is:
- `bootstrap.py`, `diagnostics.py`, `setup.ps1`, `launch.*`: installation and diagnostics
- `session.py`: `codex queue` routing
- `history.py`: sessions and journal events. Replace BG3 `.lsv` save discovery with character/realm selection from the `WTF` tree.
- `panel.py`, `dialogs.py`: panel and dialogs, reskinned
- `transport.py`: loopback bridge, keeping only the capture and status operations
- Window capture in `windows.py`: retarget from the BG3 window to `Wow.exe` / `WowClassic.exe`. **Exact process name for Forever is not yet verified.**

Remove or disable:
- The `SendInput` gesture API, input hotkeys, the INPUT switch, and gesture validation in `core.py`
- `bg3-smart-move` and `bg3-system-setup` skills. Replace them with advice-only `wow-observe`, `wow-next-step`, and `wow-settings`.

New:
- `wow_addon/WoWCompanion/`: a minimal Lua addon (`.toc` + `.lua`) that serializes character state into SavedVariables. Read-only snapshot, no automation, no chat or protected API use.
- `wow_helper/wtf.py`: locate the install, list accounts/realms/characters, and parse SavedVariables safely. SavedVariables are Lua, so use a restricted table parser. Never `exec` or `loadstring` them.
- A panel pane showing snapshot age: "Addon data from 14 min ago (last /reload)"

## 5. Milestones

1. **M0 — Decide the repo shape (needs the operator).** Choose between renaming this repo or creating a new `wow-companion` repo from this code. Recommendation: **new repo**, with this one archived as `bg3-companion`. BG3 history and docs would stay coherent, and the WoW repo would start clean of input code.
2. **M1 — Advice-only core.** Strip input, retarget capture, rename the package (`wow_helper`), and add `wow-observe` / `wow-next-step` skills. Accept when Explain screen works against the Forever beta client and all remaining tests pass. Input tests are deleted, not skipped.
3. **M2 — Character context.** Add the addon plus `wtf.py`. Accept when a snapshot is parsed, shown with its age, and attached to requests. Use a fuzz/synthetic-file test for the parser.
4. **M3 — Journal.** Record per-character sessions: level-ups, zones, and notes. Replace the "save reference" with "character@realm".
5. **M4 — Later/optional.** Post-fight combat-log summaries, addon inventory report (the BG3 mod-report idea, reborn), and a settings audit from `Config.wtf`.

## 6. Privacy

- Screenshots can include chat, other players' names, and whispers. They go to Codex when AI help is requested. Default to cropping or warning about the chat frame, which is an open design question.
- The account folder name in `WTF/Account/` is often the Battle.net account name or email-derived. Never send it, log it, or put it in reports.
- Never read `WTF/Account/*/SavedVariables/` of third-party addons beyond the companion's own file unless the user opts in.

## 7. Risks and unknowns

- **ToS:** Confirm Blizzard's current policy on screen-reading assistants. Advice-only is believed compliant because it works like a human reading a guide on a second monitor. This is unverified.
- The Forever client's process name, install path (`_forever_`?), and Interface version number for `.toc` `## Interface:` are unknown until checked on the beta client.
- Beta content changes weekly, so AI advice about new Forever-only quests, zones, and the Skyborne race will be unreliable. Advice about vanilla-era content is likely better.
- Codex latency makes this a between-pulls helper, not a combat-time assistant.

## 8. Decisions needed from the operator

1. New repo vs. rename in place. Recommended: new repo.
2. Confirm that input automation is fully dropped. Recommended: yes, since keeping it would risk the Battle.net account.
3. Faction/character to test on in the beta, which is needed for M1/M2 acceptance.
