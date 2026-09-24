# Fable review of PLAN.md (2026-09-23)

> **Historical record.** Every finding below was folded into `PLAN.md` on 2026-09-23; read the plan, not this file, for current intent.

Reviewed by Fable (claude-fable-5-1) as a read-only pass. Web-sourced facts below come from the reviewer and have **not** been checked against a local Forever client.

## Blocker
- **ToS framing (§2, §7):** The EULA's definition of an unauthorized third-party program covers anything that "intercepts, mines, or otherwise collects information from or through" WoW. Passive screen reading arguably fits, and no official ruling is expected. Recast this as an accepted policy risk. Mitigations: no injection, no memory reads, no overlay hooks, and GDI capture only. Test on an expendable account. Warden detection risk is low; the real risk is policy.

## Should-fix
- **Process/folder (§4, §7):** The beta client is reportedly `WowB.exe` in `_classic_beta_`, and the launch name is unknown. Make the eligible executable set configurable and log the observed path in `status`.
- **Interface version (§7):** Reportedly `## Interface: 16001` (game version 1.60.1).
- **Account folder (§6):** Modern clients use a numeric ID, not the email. `Config.wtf` can contain `SET accountName` (the login email), so whitelist CVar keys when reading it.
- **Section 4 reuse claims are wrong in places:**
  - `session.py` hardcodes smart/setup kinds, `allow_actions`, `gesture_limit`, and bg3 skill names, so roughly 40% of it needs rewriting.
  - `transport.py` must keep `/connect /request /claim /finish /note /history /play /crop /stop`; only `/action` and the settings endpoints go.
  - `SendInput` lives in `windows.py`, not `core.py`. `core.py` holds `act`, `arm`, and `GAME_KEYS`.
  - The plan omits `settings.py` (the BG3 `graphicSettings.lsx` parser), `dialogs.setup_dialog`, the INPUT card in `panel.py`, `diagnostics.SKILLS`, the bootstrap BG3 strings and temp folder, and `history.import_legacy`.
  - Keep `test_arena.py`, because the beta closes on 2026-10-21 and no client is available until launch.
- **Secret values:** Forever uses the modern API with Midnight-era hidden enemy health, damage, and threat. M2 character data is fine, but the M4 combat-log feature is unverified.
- **SavedVariables parser:** Handle `-- [n]` comments and `\124` escapes, cap file size, require a stable mtime before reading, and reject unbalanced tables. Derive snapshot age from the file mtime.
- **Privacy:** Have the addon record `ChatFrame1:GetRect()` so the chat frame can be cropped deterministically, instead of just warning about it.

## Milestones
- The order is sound.
- M1 acceptance should be concrete: `WowB.exe` capture at native resolution, `/action` returns 404, a test asserts that `SendInput` is absent, and the test arena passes. Replace the input tests with advice-only equivalents.
- In M3, level-ups are snapshot diffs, not events.

## Decisions (reviewer recommendations)
1. New repo, cloned **with history** and then stripped.
2. Drop input fully, including the INPUT hotkey and `/action`. Keep STOP.
3. Test with a low-level vanilla-race character. Use Skyborne only to check advice reliability on new content.
