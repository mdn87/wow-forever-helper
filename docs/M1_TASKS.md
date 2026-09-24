# M1 task breakdown

Work breakdown for milestone M1 in `PLAN.md` §6, written so a multi-model orchestrator can dispatch each task independently. Every task states the files it owns (no other task edits them concurrently), what it depends on, the evidence that closes it, and a routing tag.

Routing tags:

- **size** — S (under ~50 changed lines), M (~50-250), L (over 250).
- **tier** — `mechanical` (rename, delete, move; a small model with tests is enough), `standard` (ordinary coding against clear tests), `reasoning` (design or prose judgement; use a stronger model), `human` (needs the operator or a game client).

Branch strategy: all tasks land on one branch, `feat/m1-port`, off `main`. `tests/test_no_input.py` **will fail** on that branch from M1-01 until M1-02 and M1-03 land; that is the intended gate, not a reason to weaken the test. The branch merges only when M1-13 passes. The pre-push hook runs the leak check on every push, so every task must be leak-clean on its own.

Global rules for every task: follow `AGENTS.md`; synthetic values only; no local paths in files or test output; conventional-commit messages; delete dead code rather than commenting it out; do not skip tests, delete them.

| ID | Task | Owns | Depends on | Size | Tier |
| --- | --- | --- | --- | --- | --- |
| M1-01 | Port the prototype | `wow_helper/**`, `tests/test_*.py` (except `test_no_input.py`), `pyproject.toml`, `setup.ps1`, `launch.cmd`, `launch.ps1`, `launch-dev.cmd`, `dev.ps1` | — | L | mechanical |
| M1-02 | Strip input from the desktop layer | `wow_helper/windows.py`, `wow_helper/shortcuts.py`, `wow_helper/test_arena.py` | M1-01 | M | standard |
| M1-03 | Strip input from the bridge core | `wow_helper/core.py`, `tests/test_core.py` | M1-02 | M | standard |
| M1-04 | Remove input and settings endpoints | `wow_helper/transport.py`, `wow_helper/__main__.py`, `wow_helper/settings.py` (delete), `tests/test_transport.py`, `tests/test_history_settings.py` | M1-03 | M | standard |
| M1-05 | Rewrite the session layer for advice-only kinds | `wow_helper/session.py`, `tests/test_session.py` | M1-03 | M | reasoning |
| M1-06 | Retarget capture to the WoW client | `wow_helper/windows.py` (after M1-02), `tests/test_core.py` (capture-target tests only, after M1-03) | M1-02, M1-03 | S | standard |
| M1-07 | Write the two skills | `.agents/skills/wow-observe/**`, `.agents/skills/wow-next-step/**` | M1-05 (CLI and kind names) | M | reasoning |
| M1-08 | Panel and dialogs | `wow_helper/panel.py`, `wow_helper/dialogs.py` | M1-04, M1-05 | M | standard |
| M1-09 | Bootstrap and diagnostics strings | `wow_helper/bootstrap.py`, `wow_helper/diagnostics.py`, `tests/test_startup.py` | M1-07 (skill names) | S | mechanical |
| M1-10 | History without saves or legacy import | `wow_helper/history.py`, `tests/test_history_settings.py` (history half, after M1-04) | M1-04 | S | standard |
| M1-11 | Docs and status | `README.md`, `docs/PLAN.md` (status line only), `AGENTS.md` (only if a rule needs a path fixed) | M1-08, M1-09, M1-10 | S | mechanical |
| M1-12 | Beta-client acceptance | nothing in the repo; evidence goes in the PR description | M1-06, M1-07, M1-08, Decision 4 in `PLAN.md` §8 | — | human |
| M1-13 | Integration gate and merge | branch merge only | all of the above except M1-12 if the beta has closed | S | mechanical |

Parallel lanes once M1-03 is in: {M1-04 → M1-10}, {M1-05 → M1-07 → M1-09}, {M1-06}; then M1-08, then M1-11, M1-13.

## Task details

### M1-01 Port the prototype

Copy the prototype's `bg3_helper/` package into `wow_helper/`, its `tests/`, `pyproject.toml`, and the five launcher scripts. Rename the package everywhere (`bg3_helper` → `wow_helper`, distribution name `wow-forever-helper`). Do not change behaviour in this task; the input code comes along and is removed by M1-02/03. Do **not** copy `.runtime/`, `play-sessions/`, `.agents/skills/` (rewritten in M1-07), or any image.

Evidence:
- `python -m wow_helper doctor` runs and reports its checks.
- `python -m pytest -p no:cacheprovider tests` shows only `tests/test_no_input.py` failing (expected until M1-03).
- `git grep -n bg3_helper` is empty; `scripts/leakcheck.sh` is clean.

### M1-02 Strip input from the desktop layer

In `windows.py` delete the `MOUSEINPUT`, `KEYBDINPUT`, `HARDWAREINPUT`, `INPUTUNION`, and `INPUT` structures, the `SendInput` argtype/restype setup, `send`, `foreground`, and `return_focus`. Keep `executable` (`OpenProcess` with `0x1000` is allowed; see `AGENTS.md`). In `shortcuts.py` delete `INPUT_SHORTCUT` and move STOP to Numpad 1; update `Hotkeys` accordingly. In `test_arena.py` delete the click/key/scroll counters and their bindings, keep the window-property marker, and rename the title and property to `WoW Helper Test Arena` / `WoWHelperTestArena`. Update the module docstring.

Evidence:
- `tests/test_no_input.py::test_python_has_no_input_or_memory_access` no longer lists `windows.py`, `shortcuts.py`, or `test_arena.py`.
- `git grep -n -e SendInput -e INPUT_SHORTCUT -- wow_helper` is empty.

### M1-03 Strip input from the bridge core

In `core.py` delete `GAME_KEYS`, `visual_difference`, `Bridge.arm`, `Bridge.armed`, `Bridge.act`, the `settings` attribute, and the arming fields in `status`. `Bridge.stop` keeps incrementing the stop revision and cancels the pending request through the session. Keep `pixel_point`; `crop` uses it. In `tests/test_core.py` delete the tests for unsafe actions, unknown input results, bounded gestures, arm/stop races, and the "without sending input" naming; add tests that `Bridge` has no `act`/`arm` attribute and that `stop` after `capture` leaves the last frame intact.

Evidence:
- `tests/test_no_input.py` passes in full.
- `tests/test_core.py` passes; no test is marked skip or xfail.

### M1-04 Remove input and settings endpoints

In `transport.py` delete the `/action`, `/profiles`, `/settings-snapshot`, `/settings-observe`, and `/settings` branches; unknown paths already 404. Rename `/saves` to `/characters` returning `[]` for now. In `__main__.py` delete the `act` subparser and its handling; reword `stop` help. Delete `settings.py`. In `tests/test_transport.py` replace `test_cannot_arm_via_network` with a test that `POST /action` returns 404 and that `/characters` returns an empty list; drop the settings assertions from `test_play_settings_and_history_over_http`. In `tests/test_history_settings.py` delete the settings, profile, observation, setup, and smart-action tests (M1-10 handles the history half).

Evidence:
- `tests/test_transport.py` passes, including the 404 test.
- `git grep -n -e '"/action"' -e settings_snapshot -- wow_helper` is empty.

### M1-05 Rewrite the session layer for advice-only kinds

In `session.py`: `submit` accepts `explain`, `next_step`, and `connection_test`; delete `allow_actions`, `gestures`, `gesture_limit`, the gesture-reservation method, the `setup` snapshot branch, and the `return_focus` parameter. `prompt()` names the skills `wow-observe` (explain) and `wow-next-step` (next_step) and instructs Codex to capture, inspect, and answer with advice only; it must not mention `act`, gestures, or `--smart-request`. Keep the connect/claim/finish/expire flow and terminal-state handling unchanged. Rewrite `tests/test_session.py`: delete the input-upgrade, gesture, rearm, and act-tagging tests; keep and adapt the expiry, stop-revocation, and failed-delivery tests; add a test that `next_step` produces a prompt naming `wow-next-step` and containing no `act`.

Evidence:
- `tests/test_session.py` passes.
- `git grep -n -e allow_actions -e gesture -e smart_request -- wow_helper` is empty.

### M1-06 Retarget capture to the WoW client

In `windows.py` replace the `{"bg3.exe", "bg3_dx11.exe"}` set with a module-level default `("wowb.exe", "wow.exe", "wowclassic.exe")`, overridable by the `WOW_HELPER_EXECUTABLES` environment variable (comma-separated, case-insensitive). `target()` label becomes "WoW: Forever". `system_info` / `status` report the matched executable basename and its parent folder name only (for example `wowb.exe` in `_classic_beta_`), never the full path. Add a unit test with a fake window list covering the default set, the override, and that the reported path is basename-plus-parent only.

Evidence:
- The new test passes; `python -m wow_helper status` on a machine without the client reports "not running" without printing any path.

### M1-07 Write the two skills

Create `.agents/skills/wow-observe/SKILL.md` and `.agents/skills/wow-next-step/SKILL.md` (plus each skill's `agents/` folder if the prototype layout needs one). Both: claim the request, capture through the CLI, inspect the preview and native crops, answer with advice, finish the request. `wow-observe` explains what is on screen. `wow-next-step` suggests one concrete next step and says what evidence it used and how stale it is. Both state explicitly that no command sends input and that the assistant must never suggest the player run automation. Link to Wowhead or Warcraft Wiki for game facts rather than restating them.

Evidence:
- Both files exist and `git grep -n -e ' act ' -e smart-request -- .agents` is empty.
- A reviewer (any model) confirms each skill's command list matches `python -m wow_helper --help` output from M1-04.

### M1-08 Panel and dialogs

In `panel.py` delete the INPUT card, switch, and its updater; delete the "Smart next move", "Smart system setup", and "Profiles" buttons and the profile-status polling; add a "Next step" button submitting `next_step`; update the shortcut text (capture Numpad 0, stop Numpad 1); add a standing status note "Captures may include chat; chat blanking arrives with the addon" (per `PLAN.md` §5.2). Rename "Session & save" to "Session & character". In `dialogs.py` delete `setup_dialog`; leave `session_dialog` listing whatever `/characters` returns (empty until M2).

Evidence:
- `python -m wow_helper panel --test-target` opens, all buttons are wired, and STOP is responsive while a request is pending (manual, describe in the PR).
- `git grep -n -e input_card -e setup_dialog -e Profiles -- wow_helper` is empty.

### M1-09 Bootstrap and diagnostics strings

Replace the BG3 strings listed in `PLAN.md` §4 for `bootstrap.py` and `diagnostics.py`: temp-folder name `WoWForeverHelper`, message-box title, launch hint, self-paths, `SKILLS = ("wow-observe", "wow-next-step")`, the write-check probe text, the distribution name, the source-file list, and the `doctor` help text. Update `tests/test_startup.py` expectations.

Evidence:
- `tests/test_startup.py` passes; `git grep -n -i bg3 -- wow_helper` is empty.

### M1-10 History without saves or legacy import

In `history.py` delete `discover_saves` and `import_legacy`; add `discover_characters(wtf_root)` returning `[]` with a docstring pointing at M2; rename the `linked_save` field to `linked_character` (null for now) and `link_save` to `link_character`, keeping the event record name `character_linked`. Keep the session-directory containment checks. Update the history tests kept from M1-04 and delete the two legacy-import tests.

Evidence:
- `tests/test_history_settings.py` (rename to `tests/test_history.py`) passes.
- `git grep -n -e lsv -e import_legacy -e linked_save -- wow_helper` is empty.

### M1-11 Docs and status

Update `README.md` status to "M1 in progress" or "M1 done" as appropriate, and the status line of `docs/PLAN.md`. Do not restate the plan. Fix any `AGENTS.md` reference that a rename broke.

Evidence: `scripts/leakcheck.sh` clean; a reviewer confirms the README still reads as plain language.

### M1-12 Beta-client acceptance (human)

Requires Decision 4 in `PLAN.md` §8 and the beta client. On the beta: run `python -m wow_helper status` and record the executable basename and folder name; run one capture and confirm its size equals the window's client size; run "Explain screen" once from the panel and record the elapsed time and a one-line paraphrase of the answer. Nothing captured is committed.

Evidence: the three lines above in the PR description, redacted per `AGENTS.md`. If the beta has closed, note that and defer to launch week; M1 still merges.

### M1-13 Integration gate and merge

Run, in order: `python -m pytest -p no:cacheprovider tests`; `scripts/leakcheck.sh origin/main...HEAD`; `git grep -n -i -e bg3 -e SendInput -e allow_actions -- wow_helper tests .agents` (must be empty); `python -m wow_helper doctor`. Then merge `feat/m1-port` to `main` and archive the branch per the operator's git rules.

Evidence: the four command outputs pasted into the PR, with M1 criteria 1-4 and 7 from `PLAN.md` §6 ticked, and 5-6 either ticked from M1-12 or explicitly deferred.
