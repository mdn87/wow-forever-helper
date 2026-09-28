# WoW Forever Helper

**A Windows accessibility helper for explicit player commands, with a second-screen advice companion planned.**

## What works now

The first component maps a request such as **“cast teleport to Orgrimmar on my mage”** to one configured action-bar keybind. It supports `SHIFT+7`, `SHIFT+F4`, and other single key chords. You choose the spell and issue each command; the helper sends the mapped key once.

The CLI previews by default. Live delivery requires enabling input, explicitly executing a fresh request, and having WoW in the foreground. Request IDs prevent a repeated delivery from casting twice. `stop` disables further input. Delivery confirmation means the key was sent, not that the spell succeeded.

## Try it

Use Python 3.11 or newer from the repository root; runtime dependencies are all standard-library modules. This example assumes you first assigned the actual spell to `Shift+F4` in WoW:

```console
python -m wow_helper bind teleport-orgrimmar --key SHIFT+F4
python -m wow_helper request "cast teleport to Orgrimmar on my mage"
python -m wow_helper status
```

No character yet? `python -m wow_helper stub on` runs every check and logs the key press instead of sending it.

A read-only **quest companion** lists the quests in your log and suggests an order: turn-ins first, then quests in your current zone, then quests you are close to finishing, plus the quests the game lists to pick up on your current map. A small addon copies the quest log into SavedVariables on `/reload`; `python -m wow_helper install-addon` installs it and `python -m wow_helper quests --text` reads it. `python -m wow_helper character --text` reports gold, rested XP, gear durability, and bag space from the same snapshot. See [quest companion](docs/QUESTS.md). It is advice only and never sends input.

See [assistive input setup](docs/ASSISTIVE_INPUT.md) for execution, voice-adapter integration, and limitations. The helper does not set your in-game bindings or verify your character. The phrase “on my mage” identifies your intended action, not a character-selection feature.

## Status

The command parser, local binding store, replay protection, Windows keyboard boundary, and CLI are implemented. Automated tests use fake input delivery; the Windows native structure layout and API initialization are checked on Windows. Actual in-game casting and end-to-end speech delivery have **not** been verified. This repository installs no microphone listener; the operator's separate voice listener calls the CLI contract in [assistive input setup](docs/ASSISTIVE_INPUT.md).

The quest companion's parser, advice order, and CLI are tested against synthetic data; the addon has not yet been loaded in a game client. The screenshot/advice panel and character journal remain planned. The earlier [plan](docs/PLAN.md) and [M1 breakdown](docs/M1_TASKS.md) are retained as historical context; their blanket input-removal requirement was superseded by the operator's assistive-input request.

Run tests with `python -m pytest -q -p no:cacheprovider`. CI runs on Windows and Linux; neither job sends live keys.

## For contributors

Read [AGENTS.md](AGENTS.md) first. This repository is public and has strict rules about what must never be committed: account names, character names, screenshots, logs, and local paths.

## License

MIT. See [LICENSE](LICENSE).
