# WoW Forever Helper

**A Windows accessibility helper for explicit player commands, with floating agent chat windows and a read-only quest companion.**

## What works now

The first component maps a request such as **“cast teleport to Orgrimmar on my mage”** to one configured action-bar keybind. It supports `SHIFT+7`, `SHIFT+F4`, and other single key chords. You choose the spell and issue each command; the helper sends the mapped key once.

The CLI previews by default. Live delivery requires enabling input, explicitly executing a fresh request, and having WoW in the foreground. Request IDs prevent a repeated delivery from casting twice. `stop` disables further input. Delivery confirmation means the key was sent, not that the spell succeeded.

## Try it

For **interactive chat with an open agent session**, install the optional chat dependency in a local environment and open the window:

```console
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[chat]"
.venv/Scripts/python -m wow_helper chat
```

The companion starts with one chat window. Its compact top row holds **+ New**, the session selector, refresh, and the **⚙** menu. Press **Enter** or **Send ↵** beside the message box to send; **Shift+Enter** adds a line. **⚙ → Chat appearance…** previews and saves this window's colors, font, and text size. **+ New** opens another window at the same size with a chooser; select **Open agent chat** and connect it to a different session. Classic-inspired leather buttons with a muted red tint, brass trim, and dark panels include a matching Windows title bar. Drag that bar to move a window, or an edge or the bottom-right grip to resize it. Windows can stay above WoW, and their positions, sizes, session choices, drafts, and recent conversations return on the next helper launch. **Hide all windows**, **Restart companion**, and **Quit companion** preserve the whole set. For Claude, use **⚙ → Connect selected Claude session…** once in the existing terminal. See [interactive chat](docs/CHAT.md) for appearance settings, retention controls, and delivery states.

The chat windows are a separate desktop application. The **WoW Companion** addon still only exports data; it does not display a chatbox inside WoW. Launch the desktop companion separately and use WoW in windowed or windowed fullscreen mode.

On Windows, **Ctrl+Alt+H** brings the companion windows back while you play. **Menu → Hide all windows** preserves the whole set; closing the last window also leaves the helper running for the shortcut. **Menu → Quit companion (stops shortcut)** fully exits. Run the launch command again to show an already-running companion or start it after a full quit. To load updated code, use **Menu → Restart companion (load updates)** or `python -m wow_helper chat --restart`. If the running version predates restart support, quit it from its menu once and launch again. If the shortcut is unavailable, the last window exits normally; `chat --hotkey F10` selects **Ctrl+Alt+F10** instead.

Use Python 3.11 or newer from the repository root. Commands other than chat need only the standard library. This example assumes you first assigned the actual spell to `Shift+F4` in WoW:

```console
python -m wow_helper bind teleport-orgrimmar --key SHIFT+F4
python -m wow_helper request "cast teleport to Orgrimmar on my mage"
python -m wow_helper status
```

No character yet? `python -m wow_helper stub on` runs every check and logs the key press instead of sending it.

A read-only **quest companion** lists the quests in your log and suggests an order: turn-ins first, then quests in your current zone, then quests you are close to finishing, plus the quests the game lists to pick up on your current map. A small addon copies the quest log into SavedVariables on `/reload`; `python -m wow_helper install-addon` installs it and `python -m wow_helper quests --text` reads it. `python -m wow_helper character --text` reports gold, rested XP, gear durability, and bag space from the same snapshot. After the first `/reload`, `python -m wow_helper check-snapshot --text` reports which of the helper's assumptions the game client confirmed, without printing names or paths. See [quest companion](docs/QUESTS.md). It is advice only and never sends input.

See [assistive input setup](docs/ASSISTIVE_INPUT.md) for execution, voice-adapter integration, and limitations. The helper does not set your in-game bindings or verify your character. The phrase “on my mage” identifies your intended action, not a character-selection feature.

Use `--flavor _classic_beta_` with `quests` or `character` to read that edition's newest snapshot. If none exists, the report is refused. Without this option, the newest snapshot across editions is used.

## Status

The command parser, local binding store, replay protection, Windows keyboard boundary, and CLI are implemented. Automated tests use fake input delivery; the Windows native structure layout and API initialization are checked on Windows. Actual in-game casting and end-to-end speech delivery have **not** been verified. This repository installs no microphone listener; the operator's separate voice listener calls the CLI contract in [assistive input setup](docs/ASSISTIVE_INPUT.md).

Independent desktop chat windows, the new-window chooser, saved layouts, cached conversations and drafts, session pickers, the Codex queue adapter, and the Claude polling inbox are implemented. Synthetic Windows checks cover independent sends, restoration, unavailable sessions, interrupted delivery without replay, monitor recovery, and save failures. A chat and chooser were visually checked at 620 × 700 on 2026-10-10. Live session discovery and transcript reading were previously checked with Codex CLI 0.162.1 and Claude Code 2.1.296; a live user-message/reply round trip remains unverified. Chat does not send game input. The other window types shown as planned in the chooser are not implemented.

The quest companion's parser, advice order, and CLI are tested against synthetic data. On 2026-10-10, addon 0.4.0 produced a real Classic Forever beta snapshot on Windows: all 13 snapshot checks passed, and the quest and character reports returned successfully. Available-quest coverage and accuracy against the in-game display still need checking; see [verification details](docs/QUESTS.md#what-has-been-verified). Connecting these reports to chat, the screenshot/advice panel, and the character journal remain planned. The earlier [plan](docs/PLAN.md) and [M1 breakdown](docs/M1_TASKS.md) are retained as historical context; their blanket input-removal requirement was superseded by the operator's assistive-input request.

Run tests with `python -m pytest -q -p no:cacheprovider`. CI runs on Windows and Linux; neither job sends live keys.

## For contributors

Read [AGENTS.md](AGENTS.md) first. This repository is public and has strict rules about what must never be committed: account names, character names, screenshots, logs, and local paths.

## License

MIT. See [LICENSE](LICENSE).
