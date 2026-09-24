# Contributing to WoW Forever Helper

## This repository is public

Everything here is world-readable: code, docs, commits, branch names, issues, PR descriptions, review comments, and CI logs. **Assume anything pushed is permanently leaked.** Deleting a file or rewriting history later does not remove it from forks, caches, scrapers, or issue/PR edit history.

### Never commit, paste into an issue or PR, or quote in a commit message

- **Account identifiers:** Battle.net emails or BattleTags (`Name#1234`), the numeric `WTF/Account/<ID>` folder name, `SET accountName` or any other value from a real `Config.wtf`, and authenticator or recovery details.
- **Character identity:** real character and realm names, **including the operator's own**. They are searchable on the Armory and link back to the account.
- **Real play data:** screenshots (including WoW's native `.tga` files), `WoWCombatLog.txt`, SavedVariables, `chat-cache.txt`, `layout-local.txt`, `bindings-cache.wtf`, crash dumps (`Errors/*.dmp`, `*.mdmp`), `play-sessions/`, and captures. This includes other players' names, guilds, whispers, and party or raid rosters.
- **Credentials and runtime state:** API keys, tokens, `.env` files, Codex thread IDs, Codex session transcripts (`~/.codex/sessions/*.jsonl`, which hold full prompts and screenshots), `.runtime/` descriptors, and loopback bridge secrets.
- **Machine and personal details:** local paths in any form (`C:\Users\<name>`, `C:\\Users\\…`, `/c/Users/…`, expanded `%USERPROFILE%`), machine nicknames, home network or infrastructure details, and personal email addresses in file content.
  - *Exception:* the operator's own address in the git commit **author** field is intentionally public.
- **Blizzard content:** client files, extracted or datamined data, game art, icons, sounds, or copied guide text. Link to Wowhead or Warcraft Wiki instead of copying their content.

### Output that becomes public

- Redact local paths and names from Python tracebacks and logs before pasting them into issues or PRs.
- Tests and the app must not print local paths or account folder names to stdout. CI output is public.
- CI workflows must not use `set -x`, `env`, or `printenv`, and must not echo secrets or runtime files.

### Fixtures and examples must be synthetic

- Test fixtures (SavedVariables, `Config.wtf`, `.toc`, combat-log lines, mock screenshots) live as flat files in `tests/fixtures/`. They are hand-written with obviously fake values: account `000000000`, realm `ExampleRealm`, character `Testchar`, BattleTag `Example#0000`.
- Label each fixture as synthetic in a header comment. Never "sanitize" a real file into a fixture; write one from scratch.
- Doc images (`docs/img/`) come only from a synthetic test surface or a mock-up, cropped to the app itself: no taskbar, clock, or other windows. Strip metadata before committing (`exiftool -all= file.png`).

### Before every push

1. Enable the committed hooks once per clone:

   ```bash
   git config core.hooksPath .githooks
   ```

2. The `pre-push` hook runs `scripts/leakcheck.sh` over every commit being pushed. To check manually:

   ```bash
   scripts/leakcheck.sh origin/main...HEAD
   ```

3. Investigate every hit. Bypass with `git push --no-verify` only after confirming each hit is a false positive.
4. GitHub secret scanning and push protection are enabled, but they catch provider tokens, not BattleTags, thread IDs, or paths. The leak check is the control for those.
5. Add ignore rules to `.gitignore` before writing code that produces new local data.

### If something sensitive is committed

- **Not pushed yet:** amend or reset the local commit before pushing.
- **Already pushed:** stop and tell the operator. Rotate what can be rotated: tokens, keys, and passwords.
  - BattleTags, account IDs, and character names **cannot be rotated**. Once pushed, they stay leaked, which is why the pre-push check matters.
  - Rewriting pushed history is a permanent-loss operation that needs the operator's explicit go-ahead. Afterward, ask GitHub Support to purge cached views. Issue and PR edit history stays visible regardless.

## Product rules that the public nature makes stricter

- **No game input, automation, or game-memory code.** Do not add input simulation, key or mouse injection, window messaging to the game, memory reading, process injection, hooks, overlays, or network interception, even disabled or behind a flag. A public repo is a public record. See `docs/PLAN.md` §2 and the ToS blocker in `docs/PLAN_REVIEW.md`.
  - `tests/test_no_input.py` enforces a denylist over Python source and the addon's Lua. Do not weaken it to make a change pass.
- Do not describe the project as a bot, automation, or a way around game restrictions. It is an advice-only second-screen companion.
- Parse SavedVariables with a restricted parser. Never execute Lua from disk.

## Documentation

- Keep current behavior, proposed work, and verified behavior separate. Nothing in `docs/PLAN.md` is implemented yet.
- State exactly what was tested and on what. Do not relabel old results as new checks.
