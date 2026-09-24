# WoW: Forever Helper — plan

Status: **implementation-ready, 2026-09-23. Nothing is implemented yet.** This plan retargets the BG3 Companion prototype (a separate, private repository referred to here as `bg3-helper`) at *World of Warcraft: Forever* (Blizzard's Classic+ game; beta opened 2026-09-17, beta reportedly closes 2026-10-21, launch announced for 2026-11-04). The 2026-09-23 review in `PLAN_REVIEW.md` has been folded in; that file is kept only as history.

Facts marked **reported** came from web sources during review and have not been checked against a client. Each has a verification task in `M1_TASKS.md`.

## 1. Goal

A second-screen companion for WoW: Forever. It explains what is on screen, suggests next steps (quests, talents, gear, dungeon prep), and keeps a local play journal. Architecture stays as in the prototype: a local Windows/Python/Tk panel, a loopback HTTP bridge, and an existing Codex conversation as the AI, with no separate API key.

## 2. The decisive difference from BG3: no game input

**The companion never sends mouse or keyboard input to WoW, reads its memory, hooks it, or intercepts its traffic.** BG3 is single-player and offline. WoW: Forever is an online Blizzard game under the Battle.net EULA, and even a bounded, permissioned "Smart next move" would put the player's account at risk.

Decided (see §8): input is dropped entirely. That means the INPUT switch and hotkey, the gesture budget, the `/action` endpoint, the `act` CLI command, and every `SendInput` structure and call are removed, not disabled. `tests/test_no_input.py` fails the build if any of it returns.

**STOP stays.** It cancels the pending AI request and bumps the stop revision so a late result cannot land. That is all it does now.

Legitimate data channels are a passive screenshot of the game window (GDI capture through `mss`, the same mechanism OBS and Discord use) and Blizzard's sanctioned addon API writing SavedVariables.

## 3. Data sources, in order of trust

| Source | What it gives | Evidence level |
| --- | --- | --- |
| Screenshot of the WoW window | What is visible now | Visual, can be misread |
| Companion addon SavedVariables: `WTF/Account/<numeric ID>/SavedVariables/WoWCompanion.lua` | Character, level, zone, quest log, gear, talents, gold, and the chat frame rectangle, as of the last `/reload` or logout | Structured, stale between reloads; age comes from the file mtime |
| `WTF/Config.wtf` and per-character `config-cache.wtf` | Graphics and settings values | Configured, not live-verified; read through a CVar allowlist only |
| `Interface/AddOns/*/*.toc` | Installed addon inventory | File presence only |
| `Logs/WoWCombatLog.txt` (after `/combatlog`) | Fight events for post-fight review | Structured, opt-in, and **unverified**: see §5.3 |

Addons cannot write files except through SavedVariables at reload or logout, and cannot open sockets. A live feed is impossible by design. The companion reads snapshots and always shows how old each one is.

### Client facts

| Fact | Value | Status |
| --- | --- | --- |
| Beta executable | `WowB.exe` | reported; verify in M1-12 |
| Beta install folder | `_classic_beta_` | reported; verify in M1-12 |
| Launch executable and folder | unknown until launch | the eligible executable set is configurable (M1-06) and `status` reports the observed basename and parent folder name |
| `.toc` `## Interface:` | `16001` (game version 1.60.1) | reported; verify in M2 |
| Account folder under `WTF/Account/` | numeric ID, not the email | reported; `Config.wtf` can still hold `SET accountName` with the login email, so it is never read whole |

## 4. What carries over, module by module

Verified against the prototype's `bg3_helper/` source on 2026-09-23. Line counts are approximate.

| Module | Keep | Change or remove |
| --- | --- | --- |
| `bootstrap.py` (180) | Install, instance lock, guarded launch, diagnostic log | Rename BG3 strings: the `BG3Companion` temp-folder name, the "could not start" message-box title, the "Open launch.cmd" hint, the `bg3_helper/bootstrap.py` self-paths |
| `diagnostics.py` (185) | Interpreter, Tk, pip, venv, storage, CLI-help checks | `SKILLS` tuple, the "write check" probe text, the `bg3-helper` distribution name, the source-file list, `doctor` help text that mentions input |
| `__main__.py` (120) | `panel status capture stop doctor connect request claim finish` | Delete `act` and its `--smart-request` option; `stop` help says "cancel the pending request" |
| `core.py` (290) | `BridgeError`, `Rect`, `Window`, `pixel_point` (needed by `crop`), `Bridge.status/capture/_capture/crop/play/stop` | Delete `GAME_KEYS`, `Bridge.arm`, `Bridge.armed`, `Bridge.act`, and `visual_difference` (only `act` used it). `stop` keeps the stop-revision counter. Drop the `settings` attribute |
| `windows.py` (265) | `WindowsDesktop` capture, `executable` (`OpenProcess` query-only + `QueryFullProcessImageNameW`), `windows`, `target`, `system_info`, `_visible`, `capture`, `Hotkeys` | Delete `MOUSEINPUT`/`KEYBDINPUT`/`HARDWAREINPUT`/`INPUTUNION`/`INPUT`, the `SendInput` bindings, `send`, `foreground`, `return_focus`. Eligible executables become a configurable set (§3) instead of `{"bg3.exe", "bg3_dx11.exe"}`; label "Baldur's Gate 3" becomes "WoW: Forever" |
| `shortcuts.py` (11) | Capture and STOP hotkeys | Delete `INPUT_SHORTCUT`; STOP moves to Numpad 1 |
| `session.py` (245) | `codex_command`, `queue_message`, the connect/claim/finish/expire flow, terminal-state handling | About 40% is rewritten: `submit` kinds become `explain`, `next_step`, `connection_test` (and `settings` in M4); delete `allow_actions`, `gestures`, `gesture_limit`, the gesture-reservation method, the `setup` snapshot, and `return_focus`; `prompt()` names `wow-observe` / `wow-next-step` and drops every `act` instruction |
| `transport.py` (140) | `/status /capture /crop /stop /play /history /connect /request /claim /finish /note` | Delete `/action`, `/profiles`, `/settings-snapshot`, `/settings-observe`, `/settings`. `/saves` becomes `/characters` (M1 stub, real in M2) |
| `history.py` (220) | `PlayHistory` sessions, events, `record_request`, path containment | Delete `discover_saves` (`.lsv` globbing) in favour of a `discover_characters` stub; `link_save` becomes `link_character` in M3; delete `import_legacy` (§8, BG3 history not imported) |
| `settings.py` (170) | nothing | Delete. It parses BG3's `graphicSettings.lsx` and holds setup profiles. A `Config.wtf` reader with a CVar allowlist is new M4 work in `wtf.py` |
| `panel.py` (310) | Explain screen, Capture only, STOP, Session and History buttons, status polling | Delete the INPUT card and switch, "Smart next move", "Smart system setup", "Profiles", and the shortcut text that mentions input. Add "Next step". Add the snapshot-age pane in M2 |
| `dialogs.py` (330) | `job`, `dialog`, `session_dialog`, `history_dialog`, `event_summary` | Delete `setup_dialog`; `session_dialog` lists characters instead of saves (M2) |
| `test_arena.py` (95) | The disposable Tk test window and its window-property marker. Keep it: the beta closes before launch and capture must stay testable without a client | Delete the click/key/scroll counters (they verified input); rename the title and property |
| Tests (5 files, 64 tests) | Capture, crop, history sessions, session lifecycle, startup, transport | Delete input, gesture, arming, profile, and settings tests outright (not skipped). Add advice-only equivalents: `/action` is 404, `Bridge` has no `act`, STOP cancels a pending request |
| Skills (`.agents/skills/`) | `bg3-observe` becomes `wow-observe` (rewritten) | `bg3-smart-move` is replaced by the advice-only `wow-next-step`; `bg3-system-setup` is replaced by `wow-settings` in M4 |
| `setup.ps1`, `launch.cmd`, `launch.ps1`, `launch-dev.cmd`, `dev.ps1`, `pyproject.toml` | All | Package and product names only |

New in later milestones:

- `wow_addon/WoWCompanion/`: a minimal Lua addon (`.toc` + `.lua`) that serialises character state into SavedVariables on `PLAYER_LOGOUT` and on demand via `/reload`. Read-only, no chat, no protected or secure API use, no `SetCVar`.
- `wow_helper/wtf.py`: locate the install, list accounts/realms/characters from the `WTF` tree, parse the companion's SavedVariables (§5.1), and read an allowlisted subset of `Config.wtf` (M4).
- A panel pane showing snapshot age: "Addon data from 14 min ago (last /reload)".

## 5. Requirements carried in from review

### 5.1 SavedVariables parser (M2)

SavedVariables is Lua, so it is parsed with a restricted grammar, never executed. Requirements:

- Accept only top-level `Name = <table>` assignments; tables of `[key] = value` and positional entries; keys that are strings or integers; values that are strings, numbers, `true`, `false`, `nil`, or nested tables. Reject identifiers, operators, function calls, and anything else.
- Handle the game's `-- [n]` trailing comments and its string escapes: `\"`, `\\`, `\n`, `\r`, and decimal `\ddd` (WoW writes `|` as `\124`).
- Cap file size (4 MB) and nesting depth (32). Reject unbalanced tables with a clear error.
- The game rewrites the file on reload and logout. Require a stable mtime (unchanged across two reads at least one second apart) before trusting the contents.
- Snapshot age is derived from the file mtime; the addon also stores its own `savedAt` server time for cross-checking.
- Tested with hand-written synthetic fixtures and a fuzz test that feeds mutated fixtures and asserts the parser either returns a table or raises the parser's own error, never anything else.

### 5.2 Chat-frame cropping (M2)

Screenshots can include chat, whispers, and other players' names. The addon records `ChatFrame1:GetRect()` together with `UIParent:GetEffectiveScale()` and the screen size so the companion can convert the rectangle to window pixels. By default the companion blanks that rectangle in every capture sent to Codex and says so in the status line. The user can turn blanking off per session. Until M2 lands, M1 shows a standing warning that captures may include chat.

### 5.3 Secret values (M4 constraint)

Forever uses the modern client API with the Midnight-era "secret values" restriction: enemy health, damage, and threat are hidden from addons. Character data for M2 is unaffected. The M4 combat-log feature is **unverified** and must be prototyped against a real log before it is scheduled.

### 5.4 Privacy

- The numeric account folder name is never sent, logged, printed, or written to reports; `status` reports only that an account was found.
- `Config.wtf` is read through an allowlist of graphics CVars. `SET accountName` and anything not on the list are never read into memory.
- Third-party addons' SavedVariables are never read unless the user opts in per addon.
- Test and app output never contains local paths or account folder names (public CI logs).

## 6. Milestones

**M0 — Repo shape.** Done: this repository (see §8).

**M1 — Advice-only core.** Port the prototype into `wow_helper/`, strip input, retarget capture, add `wow-observe` and `wow-next-step`. Tasks and routing tags are in `M1_TASKS.md`. Accepted when all of the following hold:

1. `tests/test_no_input.py` passes over the ported source, and `git grep -n SendInput -- wow_helper` is empty.
2. `POST /action` on the loopback bridge returns 404, covered by a test.
3. `Bridge` has no `act` or `arm`; STOP cancels a pending request and a late result for that request is rejected, covered by tests.
4. The disposable test arena is captured at its native size by `python -m wow_helper capture --test-target`, and the existing capture and crop tests pass against it.
5. On the beta client, `python -m wow_helper status` reports the observed executable basename (expected `wowb.exe`) and install-folder name, and a capture is produced at the window's native resolution. Evidence is a redacted status line in the PR, never a screenshot.
6. "Explain screen" returns a sensible explanation from the linked Codex conversation for one on-screen situation on the beta client. Evidence is the request kind, the elapsed time, and a one-line paraphrase; no capture is committed.
7. The full test suite passes with input tests deleted, not skipped, and `scripts/leakcheck.sh` is clean.

Criteria 5 and 6 need a client and are time-boxed to the beta window; if the beta closes first, they move to launch week and M1 merges on criteria 1-4 and 7 with a note.

**M2 — Character context.** Addon plus `wtf.py`, parser per §5.1, chat-frame blanking per §5.2. Accepted when a synthetic snapshot is parsed, shown with its age, attached to a request, and the fuzz test passes; and when a real snapshot from the test character parses on the client.

**M3 — Journal.** Per-character sessions keyed by `character@realm`. Level-ups and zone changes are **diffs between snapshots**, not live events; notes are user-entered.

**M4 — Later, optional.** Settings audit from an allowlisted `Config.wtf` read (`wow-settings`, advice only), addon inventory report, and post-fight combat-log summaries if §5.3 checks out.

## 7. Risks

- **Policy risk, accepted.** The Battle.net EULA's definition of an unauthorised third-party program covers software that intercepts, mines, or otherwise collects information from or through the game. Passive screen reading arguably fits, and no official ruling is expected. This project proceeds on the judgement that advice from a screenshot is the same activity as reading a guide on a second monitor. Mitigations: no injection, no memory reads, no hooks or overlays, no network interception, GDI capture only, and the addon uses only the public API. Warden detection risk of a plain screenshot is judged low; the residual risk is policy enforcement, so testing happens on an expendable account. README states this to users.
- Beta content changes weekly, so advice about Forever-only quests, zones, and the Skyborne race will be unreliable. Advice about vanilla-era content is likely better.
- Codex latency makes this a between-pulls helper, not a combat-time assistant.
- The beta closes before launch. Between those dates only the test arena is available, which is why it stays.

## 8. Decisions

Recorded:

1. **New repository.** This is it. The prototype stays where it is. Git history was **not** imported (the repo started from a clean seed), and `history.import_legacy` is deleted rather than ported; BG3 play history is not brought across for now.
2. **Input dropped entirely.** INPUT switch, hotkey, `/action`, `act`, and the gesture budget go. STOP is kept as "cancel the pending request".
3. **Author email.** The operator's git author email on commits is intentionally public. Every other personal detail follows `AGENTS.md`.

Open:

4. **Test character (operator).** Reviewer recommendation: a low-level character of a vanilla race on an expendable account, with a Skyborne character used only to check advice quality on new content. Needed before M1 criteria 5-6 and all of M2 acceptance.
