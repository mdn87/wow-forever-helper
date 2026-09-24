# WoW Forever Helper

**A planned, advice-only second-screen companion for *World of Warcraft: Forever* on Windows.**

## What it would do

You press a button on a small window on your second monitor. The helper takes a screenshot of the game and, once the optional addon exists, reads the snapshot that addon saved of your character at your last `/reload` or logout. It then explains what is going on and suggests what to do next: which quest to pick up, what a talent does, whether you are ready for a dungeon.

Think of it as a friend reading a guide over your shoulder. **It never clicks, presses keys, moves your character, or reads the game's memory.** That is a hard rule, enforced by automated tests, not a setting.

## Status

**Planning only. There is no program to download yet.** The plan is in [docs/PLAN.md](docs/PLAN.md) and the first slice of work in [docs/M1_TASKS.md](docs/M1_TASKS.md).

Two honest caveats:

- Blizzard's rules on third-party programs are broad. We believe a passive screenshot-and-advice tool is in the spirit of "reading a guide", but there is no official ruling, and using any third-party tool with an online game is at your own risk. See the plan's risk section.
- The AI behind the advice is an existing Codex conversation on your PC. Advice about brand-new Forever content will be worse than advice about classic-era content.

## For contributors

Read [AGENTS.md](AGENTS.md) first. This repository is public and has strict rules about what must never be committed: account names, character names, screenshots, logs, and local paths.
