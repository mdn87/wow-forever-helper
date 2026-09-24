# Contributing to WoW Forever Helper

## This repository is public

Everything here is world-readable: code, docs, commits, branch names, issues, PR descriptions, and review comments. **Assume anything pushed is permanently leaked.** Deleting a file or rewriting history later does not remove it from forks, caches, or scrapers.

### Never commit, paste into an issue or PR, or quote in a commit message

- **Account identifiers:** Battle.net emails or BattleTags, the numeric `WTF/Account/<ID>` folder name, `SET accountName` or any other value from a real `Config.wtf`, and authenticator or recovery details.
- **Real play data:** screenshots, `WoWCombatLog.txt`, SavedVariables files, chat logs, `play-sessions/`, or captures. This includes other players' names, guilds, whispers, and party or raid rosters.
- **Credentials and runtime state:** API keys, tokens, `.env` files, Codex thread IDs, `.runtime/` descriptors, and loopback bridge secrets.
- **Machine and personal details:** absolute user paths such as `C:\Users\<name>\...`, machine nicknames, home network or infrastructure details, and personal email addresses.
- **Blizzard content:** client files, extracted or datamined data, game art, icons, sounds, or copied guide text. Link to Wowhead or Warcraft Wiki instead of copying their content.

### Fixtures and examples must be synthetic

- Test fixtures (SavedVariables, `Config.wtf`, `.toc`, combat-log lines) are hand-written and use obviously fake values: account `000000000`, realm `ExampleRealm`, character `Testchar`.
- Label each fixture as synthetic in a header comment. Never "sanitize" a real file into a fixture; write one from scratch.
- Doc screenshots are allowed only from a synthetic test surface or a mock-up, never from a live client with chat, names, or UI that identifies an account.

### Before every push

1. Review `git diff --cached`, not just the file list.
2. Run a quick leak check and investigate every hit:

   ```bash
   git diff --cached | grep -inE 'accountName|@[a-z0-9-]+\.[a-z]{2,}|C:\\Users\\|WTF/Account/[0-9]|thread[_-]?id|token|secret|api[_-]?key'
   ```

3. Keep new ignore rules in `.gitignore` ahead of any code that produces new local data.

### If something sensitive is committed

- **Not pushed yet:** amend or reset the local commit before pushing.
- **Already pushed:** stop and tell the operator. Treat the value as compromised: rotate the credential, or change the account detail where possible. Rewriting pushed history is a permanent-loss operation and needs the operator's explicit go-ahead. A rewrite is cleanup, not containment.

## Product rules that the public nature makes stricter

- **No game input or automation code.** Do not add `SendInput`, input simulation, key or mouse injection, memory reading, process injection, overlay hooks, or network interception, even disabled or behind a flag. A public repo is a public record. See `docs/PLAN.md` §2 and the ToS blocker in `docs/PLAN_REVIEW.md`.
- Do not describe the project as a bot, automation, or a way around game restrictions. It is an advice-only second-screen companion.
- Parse SavedVariables with a restricted parser. Never execute Lua from disk.

## Documentation

- Keep current behavior, proposed work, and verified behavior separate. Nothing in `docs/PLAN.md` is implemented yet.
- State exactly what was tested and on what. Do not relabel old results as new checks.
