# Future upgrades

Status: proposed, not implemented. Last updated: 2026-10-11.

This plan records ideas for the user-command accessibility helper and its desktop companion. The current research focus is features from popular WoW addons on Wago and CurseForge that extend or complement the existing tools. The earlier desktop interface ideas remain below. All items are proposals, without delivery dates.

Current behavior and verification evidence remain in [Chat](CHAT.md), [Quest companion](QUESTS.md), and [Assistive input](ASSISTIVE_INPUT.md). This plan does not replace the existing product boundaries in [AGENTS.md](../AGENTS.md).

## Uses to support

- Prepare for a session: inspect character readiness, compare attainable upgrades, and choose a goal.
- Get help while playing: consult a quest step or ask a short follow-up without covering much of the game.
- Understand something on screen: select the relevant image area and ask a specific question.
- Remember discoveries: keep advice, sources, screenshots, and unfinished goals connected.
- Resume and review: find the last useful next step and revisit moments worth learning from.

## Existing foundation

The app already has Agent chat, Quest guide, Character status, Screen adviser, and Journal windows; topmost positioning; saved window layouts; per-window setup presets; and local journal notes. Journal can copy the latest agent reply into its editor for review and saving.

Classic and Modern Synth are selectable. Modern Synth has charcoal panels, cyan and violet accents, adjustable window opacity, and an option to become solid during use. Current opacity fades the whole window, including text. It is not background-only glass or blur.

The additions below extend that foundation. Content pinning is different from keeping an entire window on top. Named activity layouts are different from restoring the last layout or loading a single window's setup preset.

## WoW addon shortlist

Research checked on 2026-10-11. The five candidates below were selected for fit with the existing app, not as a ranking of the five most popular addons. Approximate CurseForge lifetime downloads provide evidence of adoption; they are not active-player counts. Wago research used indexed project and version pages where the main page required JavaScript. Listed game support is not an in-game compatibility test.

### 1. BtWQuests: quest chains and prerequisites

BtWQuests shows current and future quests, their connections, and prerequisite quest lines. CurseForge lists about 11.1 million downloads. [CurseForge description](https://www.curseforge.com/wow/addons/btw-quests), [Wago listing](https://addons.wago.io/addons/btwquests/versions?page=2&stability=stable).

- **Fit:** add a Quest chain view to Quest guide: completed, current, and next steps, with an explanation of why a chosen quest is unavailable and what it unlocks.
- **Data needed:** we already export completed quest IDs. We do not have a dependency graph. Start with a selected chain researched on request, retain its sources, and distinguish verified prerequisites from uncertain ones. Our existing quest ordering does not provide this view.
- **Compatibility:** the inspected listings do not establish Forever support. Edition-specific chain information needs verification, especially for beta content.

### 2. Pawn: explainable gear comparisons

Pawn evaluates items using role-specific, customizable stat weights and highlights potential upgrades. CurseForge lists about 129.4 million downloads. [CurseForge description and versions](https://www.curseforge.com/wow/addons/pawn).

- **Fit:** extend Character status and Find better gear with a side-by-side comparison of an equipped item and a selected item or quest reward. Show stat gains and losses, role suitability, requirements, sources, and uncertainty.
- **Data needed:** the current snapshot has equipped item IDs, item levels, and durability, but no full item stats, build, or bag contents. Begin with explicit item input and sourced research; richer read-only exports could follow. Exact upgrade percentages require validated weights.
- **Compatibility:** a Forever file is listed, named `2.13.17 alpha 1 (Forever)`. That is evidence of an available build, not verified accuracy for every beta item or spec.

### 3. Baganator: inventory categories and search

Baganator organizes inventory into categories or a unified view and supports detailed searches. CurseForge lists about 38.8 million downloads. [CurseForge description](https://www.curseforge.com/wow/addons/baganator), [Wago listing](https://addons.wago.io/addons/baganator/gallery?page=1).

- **Fit:** turn Character status's bag-space summary into an inventory preparation view. Group quest items, consumables, crafting materials, and user-kept items; show quantities, search results, and changes since the previous snapshot.
- **Data needed:** we currently export bag-slot totals, not item contents. Add item IDs, quantities, classification fields, and retained comparison snapshots before claiming to explain what is filling the bags. Keep item-use and selling decisions with the player.
- **Compatibility:** both listings include Forever. Our own export fields and classifications would still need checking on the selected client.

### 4. ALL THE THINGS: personal goals and missing requirements

ALL THE THINGS tracks collections and completion, with filters and acquisition information. CurseForge lists about 60.8 million downloads. [CurseForge description](https://www.curseforge.com/wow/addons/all-the-things), [Wago versions](https://addons.wago.io/addons/allthethings/versions?page=1&stability=stable).

- **Fit:** add a small personal wishlist shared by Journal, quest research, and gear research. Pin an item, mount, recipe, or quest reward, then show its source, prerequisites, current progress, and next useful step.
- **Data needed:** start with user-selected goals and reviewed research. Automatic ownership or collection completion needs additional exports; the current snapshot cannot establish everything the character owns. Scope the first version to selected goals rather than a comprehensive catalog.
- **Compatibility:** Forever is listed. Verify each goal and its requirements against the selected edition.

### 5. SavedInstances: repeatable activity checklists

SavedInstances tracks lockouts, daily and weekly completion, currencies, and profession cooldowns. CurseForge lists about 15.5 million downloads. [CurseForge description](https://www.curseforge.com/wow/addons/saved_instances).

- **Fit:** add Today and This week lists to Journal, linked to Character status and Resume session. Track chosen activities, completion, reset or expiry, and when an activity becomes available again.
- **Data needed:** a manual checklist with explicit repeat rules can come first. Automatic tracking needs lockout, completion, cooldown, and reset-time data that the companion does not currently export. Display the last checked time and distinguish manual completion from observed completion.
- **Compatibility:** the inspected upstream listing is Retail-only. The checklist pattern can inform our UI; automatic Forever tracking needs separate API and reset-behavior validation.

Prioritize the quest-chain view and gear comparisons as extensions of existing research workflows. Manual goals and repeatable checklists are smaller starting points for the Journal. Inventory analysis follows a richer bag export. These proposals borrow feature patterns; they do not include third-party addon code, databases, or executable imports.

## Interface and workflow build order

### 1. Compact pinned advice

Steam supports notes and pinned panels with adjustable opacity. Borrow the interaction pattern for ordinary companion-owned desktop windows. [Steam client update](https://store.steampowered.com/oldnews/195171).

- Add **Pin to Play** to a selected answer or quest step.
- Show the chosen content in a narrow card: current objective, next step, and a small reply indicator.
- Keep controls minimal, with an obvious action to expand back to the full report or conversation.
- Reuse the existing opacity and solid-during-use settings.
- Preserve a link to the source conversation and the snapshot date behind the advice.

Acceptance: pinning and expanding preserve the conversation and draft; the card remains readable at supported sizes and opacity settings; restoring it sends no agent request. Clearly identify advice based on an older snapshot.

### 2. Saved activity layouts

PowerToys Workspaces saves arrangements that can be restored for a particular activity. Apply this to the companion's own windows. [PowerToys Workspaces](https://learn.microsoft.com/en-gb/windows/powertoys/workspaces).

- Save named arrangements such as **Leveling**, **Dungeon preparation**, and **Review**.
- Restore the relevant window types, positions, sizes, and display settings together.
- Leveling could pair a compact quest card with chat; preparation could show character status and gear research; review could open the journal and screen adviser.
- Reuse existing windows where practical and preserve unsent drafts when switching arrangements.
- Recover gracefully when a saved monitor is missing.

Acceptance: switching arrangements does not lose drafts, duplicate requests, or leave windows inaccessible. Loading a layout does not initiate research, capture, or game input.

### 3. Linked journal and Resume session

Obsidian combines dated notes with links between related material. Use those ideas to make saved advice easier to find and act on later. [Daily notes](https://obsidian.md/help/plugins/daily-notes), [Backlinks](https://obsidian.md/help/plugins/backlinks).

- Save selected advice with its quest reference, sources, snapshot date, and optional image.
- Add a short **Next time** checklist to a session's notes.
- Offer a **Resume session** view that shows the last saved goal, unfinished checklist items, and links to the relevant material.
- Show related notes from a quest or conversation, so the connection works in both directions.
- Keep generated summaries reviewable before they become saved journal entries.

Acceptance: saved notes remain usable when a source conversation is unavailable; links survive restart; missing images are explained; revisiting a note does not silently refresh its historical context or send an agent request.

The intended flow is: **get advice → keep it visible → save what mattered → pick up next time**.

## Further interface and workflow ideas

These follow the first three upgrades. Their order should be reconsidered after trying those workflows.

| Idea | Inspiration | Proposed behavior |
| --- | --- | --- |
| Search and command menu | [Raycast Quicklinks](https://manual.raycast.com/quicklinks) makes saved destinations searchable. | Use **Ctrl+K** inside the companion to find quests, notes, open conversations, settings, and companion actions. Show useful context before opening a result. Keep game-input execution under its existing explicit request contract. |
| Screenshot markup | [ShareX Image Editor](https://getsharex.com/docs/image-editor) supports annotation, cropping, and magnification. | Crop, magnify, or add an arrow before asking a question. Offer solid masking for names or chat, applied to pixels before submission. Preview the exact image being sent. |
| Activity list | [Linear Inbox](https://linear.app/docs/inbox) gathers updates that need attention. | Show quiet **Reply ready**, **Research finished**, and **Request failed** entries. Open the relevant conversation from an entry. Distinguish progress from completion and avoid repeatedly notifying about the same update. |
| Gear comparison | [Raidbots Top Gear](https://support.raidbots.com/article/61-top-gear-sidegrades) distinguishes upgrades from effectively equivalent choices. | Present current equipment and candidates with benefits, requirements, acquisition sources, and evidence. Explain uncertainty and beta applicability. This is a comparison interface for the existing research workflow; simulated performance would require a separate validated capability. |
| Session bookmarks | [Steam Game Recording](https://help.steampowered.com/en/faqs/view/23B7-49AD-4A28-9590) uses timelines and bookmarks to revisit moments. | Start with a manual **Bookmark this moment** action for a timestamped note and optional screenshot. Later, link bookmarks to finalized recordings and provide a review timeline. |

Recording integration remains a larger, separate effort. Follow the existing [recording-backed journal proposal](CHAT.md#proposed-recording-backed-journal) for lifecycle, storage, capture, alignment, and optional analysis requirements. A manual bookmark does not imply continuous recording or automatic AI analysis.

## Interface direction

Use two presentations of the same underlying content:

- **Play view:** a narrow card for the current objective, next step, and reply indicator.
- **Desk view:** the full report, conversation, sources, and journal, with space to compare information.

Keep the Modern Synth palette consistent across both. Use accent colors for selection, focus, and status; rely on readable text and clear spacing for the rest. Controls should support keyboard use and visible focus. Preserve the Classic interface option.

## Implementation boundaries and validation

- Keep these features in ordinary desktop companion windows, using the existing window manager behavior.
- Preserve local drafts and saved content across view changes, layout switches, failures, and restart.
- Keep advice and screenshots as context. They must not trigger game actions. Preserve the current explicit assistive-input boundary.
- Keep real notes, screenshots, recordings, and account or character details in private local storage. Use synthetic content for repository fixtures and documentation images.
- Validate each implemented feature with targeted behavior tests and synthetic Windows visual checks. Record actual in-game usability checks separately; the inspiration research is not evidence that a proposed feature works in this app.
