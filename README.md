# WoW Forever Helper

**A Windows accessibility helper for explicit player commands, with floating agent chat windows and a read-only quest companion.**

## What works now

The first component maps a request such as **“cast teleport to Orgrimmar on my mage”** to one configured action-bar keybind. It supports `SHIFT+7`, `SHIFT+F4`, and other single key chords. You choose the spell and issue each command; the helper sends the mapped key once.

The CLI previews by default. Live delivery requires enabling input, explicitly executing a fresh request, and having WoW in the foreground. Request IDs prevent a repeated delivery from casting twice. `stop` disables further input. Delivery confirmation means the key was sent, not that the spell succeeded.

## Try it

For **interactive chat and companion windows**, install the optional chat dependencies in a local environment and open the window:

```console
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[chat]"
.venv/Scripts/python -m wow_helper chat
```

The companion starts with one chat window. Its compact top row holds **+ New**, the session selector, **Codex +**, **Claude +**, refresh, and the **⚙** menu. Use a provider button to prepare a new conversation, or select an existing session. Press **Enter** or **Send ↵** to send; **Shift+Enter** adds a line. Sending without a selected session starts a new conversation. **⚙ → Chat appearance…** saves this window's colors, font, and text size. **+ New** opens another window at the same size with a chooser. Classic-inspired leather buttons, brass trim, and dark panels include a matching Windows title bar. Drag the bar to move, or an edge or corner grip to resize. Windows, session choices, drafts, and recent conversations return on the next launch. Existing externally launched Claude sessions use **⚙ → Connect selected Claude session…**; companion-created sessions connect directly. See [interactive chat](docs/CHAT.md).

The chat windows are a separate desktop application. The **WoW Companion** addon still only exports data; it does not display a chatbox inside WoW. Launch the desktop companion separately and use WoW in windowed or windowed fullscreen mode.

**⚙ → Interface & transparency…** switches all companion windows between **Classic** and **Modern Synth**. Modern Synth uses charcoal panels, flat controls, cyan and violet accents, and clean sans serif titles. Preview a 65–100% **Window opacity** setting, optionally make each window solid while you use it, then save. Tk fades the entire window, including text; this is translucency, not background-only blur. Settings stays solid, and Cancel restores the saved interface. Chat appearance can follow the interface colors or keep a custom palette.

The chooser also opens **Quest guide**, **Character status**, **Screen adviser**, and **Journal**. New report windows refresh automatically. Expand a quest to request web-backed directions at **Obvious**, **Easy**, or **Complicated** depth. Character status offers **Find better gear** by slot and build. Screen adviser supports manual capture, clipboard **Paste**, and image import. **Setup** configures startup preparation, skills, context files, standing instructions, and opening requests. **Ask agent** prepares and sends, creating a session if necessary; use the cog menu to preview first. Restoring windows never replays requests. Named presets and journal notes remain local. See [window types and setup](docs/CHAT.md#reports-images-and-journals).

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

All five chooser window types, saved layouts, new Codex/Claude conversations, existing-session connections, startup preparation, quest research and gear research are implemented. Synthetic Windows checks cover delivery, restoration, queue limits, failures, journals, images and minimum window sizes. Live checks on 2026-10-11 verified new CLI conversations, resumed replies, preparation-bundle reading, synthetic image inspection and structured web-search output for both providers. Actual beta quest routes and upgrade recommendations still require validation against the game. Chat and report windows do not send game input. The recording logger remains a [reviewed proposal](docs/CHAT.md#proposed-recording-backed-journal).

The quest companion's parser, advice order, and CLI are tested against synthetic data. On 2026-10-10, addon 0.4.0 produced a real Classic Forever beta snapshot on Windows: all 13 snapshot checks passed, and the quest and character reports returned successfully. Available-quest coverage and accuracy against the in-game display still need checking; see [verification details](docs/QUESTS.md#what-has-been-verified). Reports can now be prepared for an agent request; native game-window capture and continuous recording-backed journaling still need further work and verification as described in [Chat](docs/CHAT.md). The earlier [plan](docs/PLAN.md) and [M1 breakdown](docs/M1_TASKS.md) are retained as historical context; their blanket input-removal requirement was superseded by the operator's assistive-input request.

**Linked journal and Resume session** now saves reviewed chat replies with their original evidence and optional next steps. Use **Save selected reply to Journal…** in the chat menu, then **Resume session** in Journal to reopen the conversation without sending anything. Follow-ups require preview and explicit Send. See [saving and resuming advice](docs/CHAT.md#save-advice-and-resume-its-conversation).

**Compact pinned advice** keeps a reviewed objective and next step in a small Play card. Pin a selected chat reply, saved Journal note, or quest step; Expand shows the saved advice and evidence, and Open source returns to its conversation without sending. Cards keep their content and separate Play/Desk sizes after restart. See [pinned advice](docs/CHAT.md#compact-pinned-advice).

**Quest chains and prerequisites** researches one selected chain, separates sourced claims from saved progress, and sends reviewed updates to its Quest chat. See [quest-chain discussion](docs/CHAT.md#quest-chains-and-prerequisites).

**Dungeon route walkthrough** reviews a chosen route image or readable notes, then keeps preparation and later run review in the same conversation. See [route discussion](docs/CHAT.md#dungeon-route-walkthrough); MDT string decoding remains unsupported.

**Build tutor and experiments** imports a bounded Retail SimulationCraft profile or manual build notes, previews a discussion, and saves comparison questions with evidence in Journal. See [build tutoring](docs/CHAT.md#build-tutor-and-experiment-notebook).

**Search companion** opens with **Ctrl+K** inside a companion window. Find saved notes and next steps, known quests and conversations, layouts, and settings without sending requests.

**Saved activity layouts** let you name arrangements such as Leveling and Review from **Settings → Activity layouts…**. Preview a restore before applying it; matching windows keep their current conversations and drafts, and other open windows remain accessible. See [saved activity layouts](docs/CHAT.md#saved-activity-layouts).

**Two WoW displays** are available from **Settings → WoW companion displays…**. Choose one screen for the saved quest log and another for large Quest help, Gear check, Screen adviser, and Journal / Resume cards. Tap a card to expand its workflow; **Activity cards** returns to the grid and **Resume** reopens the last activity. Each workflow keeps its own state across switching and restart. **Return to Dias** hides the pair while keeping their state. These are helper windows placed over the selected displays; DBM remains deferred. See [quest and activity displays](docs/CHAT.md#quest-and-activity-displays).

The [upgrade implementation plan](docs/UPGRADE_IMPLEMENTATION_PLAN.md) tracks delivered F01–F06, F08, F12, F13, F16, and F17. Personal goals and wishlist include reviewed research on how to accomplish a goal, saved suggestions, player decisions, and manual progress; repeatable Today / This week checklists add explicit reset rules, manual completion and undo, and reviewed planning requests. See [checklist setup](docs/CHAT.md#repeatable-activity-checklists). The [Dias integration proposal](docs/DIAS_INTEGRATION_PLAN.md) starts with a temporary quest-and-advice view on the companion touch display and separates healer preparation from live boss-timer research. The original addon research and interface ideas remain in [Future upgrades](docs/FUTURE_UPGRADES.md), with the checked [Fable review](docs/FUTURE_UPGRADES_REVIEW.md) alongside them. The remaining upgrades are planned.

Run tests with `python -m pytest -q -p no:cacheprovider`. CI runs on Windows and Linux; neither job sends live keys.

On Windows, UI tests use a separate, non-visible desktop by default, so test
windows cannot flash over your work or take its keyboard focus. Isolation failure
stops the UI tests instead of opening windows on your desktop. For deliberate
visual inspection, add `--visible-ui` to the pytest command; this opens and closes
real test windows on your current desktop. Linux UI tests still require a display
(for example, Xvfb), and skip when none is available.

## For contributors

Read [AGENTS.md](AGENTS.md) first. This repository is public and has strict rules about what must never be committed: account names, character names, screenshots, logs, and local paths.

## License

MIT. See [LICENSE](LICENSE).
