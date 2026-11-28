# Companion UX improvement plan

**Status:** Implemented (Batches 1–4, `U01`–`U18`) and verified with synthetic isolated-desktop automated tests on 2026-11-23. Prepared from a code-level UX audit at baseline `cc9d46f` and revised after an Autowork `codex-astra` cross-review (`20261124-013949-cross-review`, all 3 findings `UX-01`–`UX-03` accepted and implemented with regression tests). A single-display visual check of both themes at minimum sizes and with a 20-point chat font ran on 2026-11-27 (see [Verification status](#verification-status)). Inspection on real multi-monitor and touch displays and live in-game walkthroughs have **not** been run yet. Each item below notes its type (**code-verified defect** or **design improvement**).

## Goals and guardrails

This plan focuses on making WoW Forever Helper clearer, faster, and more reliable while playing WoW on a second screen (with mouse/keyboard, touch displays, or hands-free voice).

Every batch must preserve the repository's existing product and safety rules in [AGENTS.md](../AGENTS.md):

- **Explicit consent stays intact.** Reducing clicks or making pre-send previews scannable must never auto-send chat messages, auto-run web research on restore, auto-capture the game, or replay pending requests after restart.
- **Read-only toward the game.** No new game input, keyboard hooks, memory reading, process injection, focus stealing, or automatic `/reload`.
- **Theme, opacity, and draft parity.** Every updated window and dialog must support both **Classic** and **Modern Synth** live switching, respect saved window opacity and solid-on-focus rules, stay usable at minimum window sizes, and preserve unfinished drafts across navigation and errors.
- **Hands-free voice compatibility.** Dialogs that inherit from `JournalDialog` stay registered in `OPEN_DIALOGS` and keep clear spoken widget labels compatible with [voice_commands.py](../wow_helper/voice_commands.py).
- **Isolated verification.** Routine automated UI checks run under `python -m pytest -q -p no:cacheprovider` on the isolated Windows desktop with synthetic fixtures only.

## Roadmap summary

| Batch | ID | Improvement | Type | Primary files |
| --- | --- | --- | --- | --- |
| 1. Reliability & visibility | [U01](#u01-shared-dialog-hygiene) | Shared dialog lifecycle, topmost Z-order, `Alt+F4`, `<Escape>`, and parent-monitor placement | Code-verified defect | `journal_ui.py`, `window_frame.py`, `wow_displays.py`, dialog modules |
| 1. Reliability & visibility | [U02](#u02-persistent-notices-and-plain-chat-feedback) | Stop `save_layout()` from erasing notices and route plain-chat feedback to a visible bar | Code-verified defect | `workspace.py`, `task_window.py`, `journal_ui.py` |
| 1. Reliability & visibility | [U03](#u03-live-gear-auto-reveal-and-starting-region) | Auto-switch Live gear comparison to Result on capture and remember the starting crop box | Code-verified defect + improvement | `gear_ui.py`, `live_gear.py` |
| 1. Reliability & visibility | [U04](#u04-selection-contrast-and-theme-parity) | Fix unreadable selection highlight in `ConversationPicker` and Classic primary button styling | Code-verified defect | `conversation_picker.py`, `theme.py`, `journal_ui.py` |
| 1. Reliability & visibility | [U05](#u05-smart-transcript-scrolling) | Stop forced scroll-to-bottom when reading older messages; add "Jump to latest" | Code-verified defect | `chat_window.py` |
| 2. Chat & command library | [U06](#u06-markdown-links-and-one-click-command-copy) | Render Markdown, clickable links, paragraph spacing, and 1-click command copy in chat | Design improvement | `appearance.py`, `chat_window.py`, new `markdown_text.py` |
| 2. Chat & command library | [U07](#u07-visible-reply-selection-and-direct-actions) | Highlight selected assistant replies and add right-click / inline Copy, Save, and Pin actions | Design improvement | `chat_window.py`, `appearance.py` |
| 2. Chat & command library | [U08](#u08-auto-growing-composer-search-and-waiting-state) | Auto-growing composer (2–6 lines + scroll), `Ctrl+F` transcript find, and visible wait indicator | Design improvement | `chat_window.py` |
| 2. Chat & command library | [U09](#u09-command-library-keyboard-flow-and-answer-actions) | Auto-focus search, Up/Down/double-click copy, fix `Enter` trap, and add research answer actions | Code-verified defect + improvement | `command_library_ui.py`, `command_research_ui.py` |
| 3. Navigation & pickers | [U10](#u10-complete-ctrlk-palette-and-toolbar-trigger) | Add a visible Search (`Ctrl+K`) toolbar button and index all tools and library commands | Design improvement | `workspace.py`, `search.py`, `command_library.py` |
| 3. Navigation & pickers | [U11](#u11-unified-session-picker-and-compact-model-pill) | Consolidate the 3 overlapping chat pickers into one switcher + compact model pill | Design improvement | `chat_window.py`, `conversation_picker.py`, `model_settings_ui.py`, `active_sessions_ui.py`, `window_frame.py` |
| 3. Navigation & pickers | [U12](#u12-active-mode-badges-and-compact-voice-panel) | Show persistent toolbar pills when Voice, Hands-free, or Live gear is armed; shrink Voice panel | Design improvement | `workspace.py`, `voice_ui.py`, `handsfree.py`, `gear_ui.py` |
| 3. Navigation & pickers | [U13](#u13-named-journal-picker-and-fight-analysis-clarity) | Replace raw UUID file picker in `Open journal` with a named picker; clarify fight-analysis tools | Code-verified defect + improvement | `task_window.py`, `journal_ui.py`, `fight_question.py`, `combat_coach.py` |
| 4. Activity flows & copy | [U14](#u14-master-detail-quest-guide-and-character-table) | Replace fake wrapped `Treeview` in Quest guide with master-detail view; clean up Character gear list | Design improvement | `quest_tree.py`, `task_window.py`, `activities.py` |
| 4. Activity flows & copy | [U15](#u15-scannable-pre-send-review-previews) | Put a concise summary header above raw JSON/SKILL payloads in all review dialogs | Design improvement | `activities.py`, `task_window.py`, `journal_ui.py`, `notebook_ui.py`, `chain_ui.py`, `tool_access_ui.py` |
| 4. Activity flows & copy | [U16](#u16-friendly-inputs-and-player-facing-copy) | Replace raw ISO/IANA fields with local defaults and presets; replace audit jargon and stale notices | Design improvement | `journal_ui.py`, `goal_ui.py`, `economy_notebook.py`, `model_settings_ui.py`, `chat_window.py`, `tool_access_ui.py` |
| 4. Activity flows & copy | [U17](#u17-dual-display-touch-ergonomics) | Wrap quest titles in `QuestLogDisplay` and scale touch targets inside `ActivityDeck` | Design improvement | `wow_displays.py`, `task_window.py` |
| 4. Activity flows & copy | [U18](#u18-in-app-setup-and-health-check) | Expose addon install, WoW folder selection, snapshot health check, and keybind status in the GUI | Design improvement | `workspace.py`, `task_window.py`, `wtf.py`, `check.py`, new `setup_health_ui.py` |

---

## Batch 1 — Reliability, focus, and visibility fixes

This batch resolves concrete bugs verified in code that break second-screen play, leak dialog/hotkey state, or hide important feedback.

### U01. Shared dialog hygiene

**Observed problems:**
- [JournalDialog](../wow_helper/journal_ui.py) (base class for 16 dialogs: `BookmarkDialog`, `SaveAdviceDialog`, `ResumeDialog`, `FollowupDialog`, `PinAdviceDialog`, `GoalDialog`, `ChecklistDialog`, `GearDialog`, `VoiceDialog`, `HandsFreeDialog`, `ChainDialog`, `ToolAccessDialog`, `DiscussionNotebook`, `FightQuestion`, `CombatNotebook`, `RouteNotebook`, `AddonNotebook`, `EconomyNotebook`) does not set `transient()`, does not inherit `-topmost` from its owner, does not register `WM_DELETE_WINDOW` on the base class, does not bind `<Escape>`, and places itself with size-only `"650x720"`.
- Because `CompanionWindow` defaults to `topmost=True` ([workspace.py](../wow_helper/workspace.py)), non-topmost child dialogs can get buried behind their own parent window.
- On multi-monitor setups, size-only geometry (`JournalDialog`, `SearchDialog`, `SetupDialog`, `RequestDialog`, `ConversationPicker`, `SavedDraftDialog`, `ModelSettingsDialog`, `CommandResearchDialog`, `ActivityDialog`, `ActivityReview`, `UsageDialog`, `show_display_setup`) lets Windows spawn dialogs on the primary monitor (over WoW) instead of beside the companion window.
- Subclasses that omit `WM_DELETE_WINDOW` (`VoiceDialog`, `GearDialog`, `HandsFreeDialog`, `BookmarkDialog`, `SaveAdviceDialog`, `ResumeDialog`, `PinAdviceDialog`, `ChecklistDialog`) skip `close()` when closed with `Alt+F4` or from the taskbar, leaving stale singleton references that fail with `TclError` on reopen and leaking active microphone streams (`VoiceDialog`) or global hotkeys (`GearDialog`).
- [show_display_setup](../wow_helper/wow_displays.py) omits `WindowFrame`, `transient()`, and `-topmost`, and labels monitors only by resolution (`Screen 1 · 1920 × 1080`) with no position hint when multiple monitors share a resolution.
- `Journal.Treeview` in [journal_ui.py](../wow_helper/journal_ui.py) configures colors once at creation and does not refresh on live theme changes; `SetupDialog._file_picker` ([task_window.py](../wow_helper/task_window.py)) and `GearDialog.canvas` ([gear_ui.py](../wow_helper/gear_ui.py)) hardcode single-theme colors.

**Planned changes:**
- Add one shared helper (in [window_frame.py](../wow_helper/window_frame.py) or a small dialog helper used by `JournalDialog` and standalone dialogs) that:
  1. Sets `transient(parent_toplevel)` and mirrors the parent's `-topmost` attribute.
  2. Registers `WM_DELETE_WINDOW` to call `close()` and binds `<Escape>` to `close()`.
  3. Computes parent-relative bounds (`parent.x + 24`, `parent.y + 24`, clamped via `window_bounds(..., display_workareas(...))`) so every dialog opens on the companion's monitor and never off-screen.
- Apply the helper to `JournalDialog`, `SetupDialog`, `RequestDialog`, `SearchDialog`, `ConversationPicker`, `SavedDraftDialog`, `ModelSettingsDialog`, `CommandResearchDialog`, `ActivityDialog`, `ActivityReview`, `UsageDialog`, `InterfaceDialog`, `ImageMarkupDialog`, and `show_display_setup`.
- Upgrade `show_display_setup` to use `WindowFrame` and append monitor position labels (`Primary`, `Left`, `Right`, `Above`, `Below`) derived from work-area coordinates.
- Register `_companion_theme_refresh` on `Journal.Treeview` and replace remaining hardcoded widget colors with `palette(root)` tokens.

**Acceptance checks:**
- Closing `VoiceDialog`, `GearDialog`, `HandsFreeDialog`, `ResumeDialog`, `BookmarkDialog`, and `PinAdviceDialog` via `WM_DELETE_WINDOW` calls `close()`, releases fake mic/hotkey resources, clears manager/view singleton references, and allows clean reopening.
- Dialogs opened from a topmost companion window on a secondary monitor (`x < 0` or `x >= primary_width`) inherit `-topmost` and land inside that monitor's work area.
- Pressing `<Escape>` closes each dialog cleanly without leaving dangling callbacks or losing unsaved drafts in the parent chat.
- Switching between Classic and Modern Synth updates open `ResumeDialog`, `ChecklistDialog`, `ToolAccessDialog`, `SetupDialog`, and `GearDialog` widgets cleanly.

---

### U02. Persistent notices and plain-chat feedback

**Observed problems:**
- `WindowManager.save_layout()` in [workspace.py](../wow_helper/workspace.py) executes `window.set_notice("")` for all windows on every successful save (500ms after almost any UI event). That immediately erases notices written by [handsfree.py](../wow_helper/handsfree.py) (`connect`), [voice_ui.py](../wow_helper/voice_ui.py) (dictation status), [pinned_advice.py](../wow_helper/pinned_advice.py), and preset/display errors.
- In plain Agent chat windows (`kind == "chat"`), `TaskWindow` does not create `self.book` or call `_build_panel()`, so `self.activity_notice` is never mounted in any label ([task_window.py](../wow_helper/task_window.py)). Actions callable from plain chat (`Tools → Edit reviewed image…`, `Bookmark this moment…` save confirmation, `show_goals` errors, `send_prepared` status) write to `self.activity_notice` and fail or confirm silently.

**Planned changes:**
- Track layout-save / shortcut-availability banners separately from general window notices in `CompanionWindow`, so a routine `save_layout()` clears only its own save-failure banner and never wipes unrelated window notices.
- Add a single `notify(message)` helper on `TaskWindow` that updates `self.activity_notice` when an activity panel is present and falls back to `self.status` when `kind == "chat"`.
- Disable (or omit) `Edit reviewed image…` in `Tools` when `self.kind != "screen"`.

**Acceptance checks:**
- Connecting hands-free voice or delivering a voice dictation notice stays visible after `save_layout()` runs.
- Saving a bookmark or triggering an error in a plain `Agent chat` window displays visible feedback in `status`.
- `Tools → Edit reviewed image…` is disabled outside `Screen adviser` windows.

---

### U03. Live gear auto-reveal and starting region

**Observed problems:**
- In [gear_ui.py](../wow_helper/gear_ui.py), `review_region()` selects the `Review region` tab, and neither `enable()` nor `poll()` switches to the `Result` tab when `Ctrl+Alt+F9` captures or completes. Because both `self.progress` and `self.output` live inside the `Result` tab, a player glancing over from WoW sees only the old setup preview.
- Closing and reopening `GearDialog` discards `self.region`, requiring the player to re-drag the tooltip rectangle from scratch every session even at the same WoW resolution.
- The initial notice says `"Voice stays input-only."`, which is outdated now that hands-free `"compare"` can trigger an armed live gear comparison.

**Planned changes:**
- Switch `self.book` to `self.result` when a new comparison request starts in `poll()` (and mirror key state transitions in the top `self.notice` banner).
- Persist the last reviewed region bounds per edition and capture dimensions in local state under `.runtime/chat/`. When a fresh preview with matching dimensions loads, pre-draw that rectangle as an editable starting box. Mandatory fresh preview, human review (`Review region`), and explicit `Enable shortcut` approval remain unchanged.
- Update the outdated notice copy to accurately describe `Ctrl+Alt+F9` and hands-free `"compare"`.

**Acceptance checks:**
- Triggering a fake `Ctrl+Alt+F9` capture while `Review region` is selected automatically displays the `Result` tab with progress and final comparison text.
- Reopening `GearDialog` and capturing a preview of the same dimensions pre-populates the previous rectangle without auto-enabling the shortcut or skipping review.

---

### U04. Selection contrast and theme parity

**Observed problems:**
- [ConversationPicker](../wow_helper/conversation_picker.py) creates `tk.Listbox(..., fg=colors.TEXT, selectbackground=colors.ACCENT)` without `selectforeground`, putting `#eee2c8` on `#ffda55` (Classic, ~1.1:1 contrast) and `#edf3ff` on `#80e5ed` (Modern, ~1.2:1 contrast).
- `Primary.TButton` is styled in Modern Synth ([theme.py](../wow_helper/theme.py)) but has no distinct configuration in Classic, leaving primary actions visually identical to secondary buttons in Classic.

**Planned changes:**
- Set `ConversationPicker` listbox selection colors to `selectbackground=colors.SELECT` and `selectforeground=colors.ACCENT` (Classic) / `colors.TEXT` (Modern), matching `Treeview` and `QuestLogDisplay`, and hook `_companion_theme_refresh`.
- Configure a clear `Primary.TButton` style in Classic (for example, brighter gold/brass border or bold display label) while keeping the Classic leather aesthetic.

**Acceptance checks:**
- Selected rows in `ConversationPicker` maintain >= 4.5:1 text-to-background contrast in both Classic and Modern Synth, including after live theme switches.

---

### U05. Smart transcript scrolling

**Observed problems:**
- [chat_window.py](../wow_helper/chat_window.py) binds `<Configure>` and `<Map>` directly to `_queue_scroll_to_bottom` and calls `_queue_scroll_to_bottom()` on every `_show()` redraw. Reading earlier advice while a new reply arrives, switching tabs, or resizing the window yanks the scroll position back to the bottom.

**Planned changes:**
- Track whether the transcript is pinned to the bottom (`_at_bottom`, updated when `yview()[1] >= 0.98`) before redraws and on user scroll events.
- When `_at_bottom` is `False`, capture a **content anchor** before any redraw, resize, or font change: map the topmost visible transcript index (`@0,0`) to `(message_id, char_offset)` plus its line/pixel viewport offset (never a fractional `yview()` ratio, which drifts whenever new text is appended or lines re-wrap). After redraw or reflow, restore that exact anchored passage (falling back cleanly to the nearest surviving message if history was trimmed).
- Always scroll to bottom right after the player sends a message or clicks a new compact **"New replies ↓"** / **"Jump to latest ↓"** bar shown only when scrolled up.

**Acceptance checks:**
- Scrolling up to a specific passage in a long synthetic transcript keeps that exact passage visible after appending a long reply, changing window width, changing chat font size, or switching tabs, and shows the jump button.
- Clicking the jump button or sending a message returns to the bottom.

---

## Batch 2 — Chat readability, composer, and command library ergonomics

This batch improves the surfaces players read and interact with most often during active play.

### U06. Markdown, links, and one-click command copy

**Problem:** [chat_window.py](../wow_helper/chat_window.py) and [appearance.py](../wow_helper/appearance.py) render assistant replies as raw plain text with zero paragraph spacing (`spacing1=0, spacing2=0, spacing3=0`), unrendered `**bold**` / `###` / backticks, unclickable URLs, and no quick way to copy `/console`, `/run`, `/dump`, `/way`, or macro snippets into WoW chat.

**Planned changes:**
- Add a small, pure, bounded Markdown-to-segments parser (e.g., `wow_helper/markdown_text.py`) handling headings, bold, italic, bullet/numbered lists, inline code, fenced code blocks, and validated `http://` / `https://` links (both `[label](url)` and bare URLs). Never execute or interpret markup as commands.
- Render segments into `self.transcript` with `tk.Text` tags respecting `self.appearance` font/size/colors, adding readable paragraph spacing (`spacing1`/`spacing3`) and subtle turn headers (e.g., **You** vs **Codex / Claude** with timestamp when available).
- Make validated URLs clickable (`hand2` cursor, underlined accent color; single click opens the default browser via `webbrowser.open`, matching `quest_tree.py` precedent).
- Attach compact inline **Copy** buttons (or clickable copy tags) to fenced code blocks and detected WoW slash-command snippets (`/console ...`, `/dump ...`, `/run ...`, `/way ...`, `/jrm`, `/aajs ...`), copying to the clipboard and showing `"Copied to clipboard"` in `status`.
- Preserve `selected_advice()` range mapping so `Save selected reply to Journal…` and `Pin selected reply to Play…` still capture the exact canonical `message.text` (or selected plain-text excerpt) without leaking UI button glyphs.

**Acceptance checks:**
- Synthetic replies containing headings, bold text, fenced `/console` commands, and `https://example.com/guide` URLs render with distinct tags, copy cleanly via the inline Copy control, open the validated URL on click, and still save/pin cleanly with original source text intact.
- Non-HTTP schemes (`javascript:`, `file:`) are rendered as plain text, never clickable links.

---

### U07. Visible reply selection and direct actions

**Problem:** Clicking an assistant reply sets `self.selected_reply_id` ([chat_window.py](../wow_helper/chat_window.py)) with no visual highlight, and `Save to Journal` / `Pin to Play` are hidden behind `Settings → Conversation` or unadvertised `Ctrl+J` / `Ctrl+P` shortcuts.

**Planned changes:**
- Highlight the active `selected_reply_id` range in `self.transcript` with a subtle tinted background tag so the user can see which reply will be saved or pinned.
- Add a right-click context menu on `self.transcript` offering **Copy selection**, **Copy reply**, **Save reply to Journal…**, **Pin reply to Play…**, and **Open link** / **Copy link** when clicked over a link.
- Optionally show compact, low-noise inline action links (`Copy · Save · Pin`) beneath each assistant reply (or on the currently selected reply) so discovery does not depend on right-clicking or memorizing shortcuts.

**Acceptance checks:**
- Clicking an assistant reply highlights that reply; opening the context menu or clicking inline Save/Pin targets the exact clicked reply and preserves drafts.

---

### U08. Auto-growing composer, search, and waiting state

**Problem:**
- `self.editor` is fixed at `height=2` with no scrollbar ([chat_window.py](../wow_helper/chat_window.py)), hiding text when dictating or typing multi-line questions.
- Waiting for an agent reply only updates an 8pt subtitle label (`Waiting for response · 12s`), easy to miss on a second monitor.
- Long conversations have no in-transcript find (`Ctrl+F`).

**Planned changes:**
- Auto-size `self.editor` between 2 and 6 visual lines as content changes, attaching a vertical `ttk.Scrollbar` automatically when text exceeds 6 lines.
- Add a compact `BusyBar` (reusing `theme.BusyBar`) above the composer whenever `response_waits` or an in-flight `send`/`start` job is active for the current session, paired with a clearer status strip (`Waiting for Codex · 12s`).
- Add a toggleable inline `Ctrl+F` find bar inside `ChatWindow` (`Next`, `Previous`, match counter, `<Escape>` closes and returns focus to transcript/composer).

**Acceptance checks:**
- Multi-line input grows the composer up to 6 lines without clipping the Send button at `440×580` minimum size, and shrinks back after sending.
- Waiting bar appears during an active wait and stops when the response completes or fails.
- `Ctrl+F` highlights matches in synthetic history without modifying transcript state or triggering scroll-to-bottom.

---

### U09. Command library keyboard flow and answer actions

**Observed problems:**
- [CommandLibraryDialog](../wow_helper/command_library_ui.py) never calls `self.entry.focus_set()` on open, does not support `<Up>`/`<Down>` navigation from the search box, and has no double-click-to-copy on rows.
- Pressing `<Return>` in the search box opens `CommandResearchDialog` even when local library commands match—surprising players who type a keyword, see the command highlighted, and press `Enter` expecting to copy it.
- [CommandResearchDialog](../wow_helper/command_research_ui.py) shows no busy bar or elapsed timer while waiting for an agent answer, and once an answer arrives it offers only `View chat`—no quick **Copy answer**, detected-command **Copy**, or **Save to Journal…**.

**Planned changes:**
- Focus `self.entry` when `CommandLibraryDialog` opens; bind `<Up>`/`<Down>` in `self.entry` to step through `self.results` (matching `SearchDialog`), and bind `<Double-1>` on `self.results` to copy the command.
- Change `<Return>` in `CommandLibraryDialog`:
  - When local matches exist: copy the selected command (and clearly confirm in `self.notice`, noting `Ctrl+Enter searches online`).
  - When zero local matches exist: open `Search online…` with the typed query.
  - Bind `<Control-Return>` (plus the existing **Search online…** button) to open `Search online…` at any time.
- Add `BusyBar` + elapsed timer to `CommandResearchDialog` while waiting, and enable **Copy answer**, **Copy command** (when a single/first slash command is present in the reply), and **Save to Journal…** once the answer arrives.

**Acceptance checks:**
- Opening `CommandLibraryDialog` focuses the search box immediately; typing `"flicker"` + `Enter` copies `/console ResampleSharpness -1` without opening the online search dialog; typing an unmatched term + `Enter` opens `CommandResearchDialog` prefilled.
- `Ctrl+Enter` always opens `CommandResearchDialog` even when local matches exist.
- Receiving a simulated research reply stops the busy bar and enables Copy / Save actions.

---

## Batch 3 — Navigation, unified session picker, and active-mode indicators

This batch addresses feature sprawl behind the single cog menu, untangles overlapping chat/session selectors, and makes background modes visible during play.

### U10. Complete `Ctrl+K` palette and toolbar trigger

**Problem:** ~30 actions sit inside four nested cascades under one 14×14px cog icon ([workspace.py](../wow_helper/workspace.py), [task_window.py](../wow_helper/task_window.py)), with no visible Search button in the toolbar. Meanwhile, [SETTINGS_ACTIONS](../wow_helper/search.py) omits several frequently used features.

**Planned changes:**
- Add a compact visible **Search** (`Ctrl+K`) button in the companion toolbar beside the Settings cog.
- Add all missing tools and preferences to `SETTINGS_ACTIONS` in [search.py](../wow_helper/search.py): **Live gear comparison**, **Post-fight coaching**, **Voice input (Keypad -)**, **Hands-free voice (Lugos Voice)**, **WoW companion displays**, **Model & usage**, **Bookmark this moment**, **Pin selected reply to Play**, and **WoW setup & health** (once U18 lands).
- Index individual entries from [command_library.py](../wow_helper/command_library.py) directly in `search_index()` as `"library"` rows so typing `"flicker"` or `"farclip"` in `Ctrl+K` previews the command and lets the user **Copy command** or open it in Command library in one step.

**Acceptance checks:**
- Every companion tool and preference reachable from the Settings menu is also findable and openable via `Ctrl+K`.
- Typing a command library keyword in `Ctrl+K` previews the command and copies it without sending any agent request.

---

### U11. Unified session picker and compact model pill

**Problem:**
- In an unconnected chat window, four controls in the top ~90px compete to select a chat through three separate flows: the squeezed toolbar combobox (`Use an existing chat…`), the `Start a new chat` / `Change chat` button → `ConversationPicker`, and the route bar's `Find active sessions` button → `ModelSettingsDialog` opened to a single `Advanced` tab under the window title **"Change model"** ([chat_window.py](../wow_helper/chat_window.py), [model_settings_ui.py](../wow_helper/model_settings_ui.py), [active_sessions_ui.py](../wow_helper/active_sessions_ui.py)).
- At minimum width (`440px`), the toolbar combobox is squeezed to ~140px, truncating session titles to ~18 characters.
- In `ModelSettingsDialog`, external Codex chats show three disabled effort radio buttons on `Next message` without explaining why until the user clicks `Choose a different model` and gets redirected to `Advanced`.
- Dragging a maximized companion window's titlebar in [window_frame.py](../wow_helper/window_frame.py) does nothing (`if self.root.state() != "normal": return`), unlike standard Windows apps.

**Planned changes:**
- Replace the cramped toolbar combobox + `Start a new chat` button with one clean **Session switcher** button/pill displaying the active chat title + provider (or `Choose or start a chat…`) with generous width, opening one unified `ConversationPicker`.
- Fold `ActiveSessions`'s live auto-refreshing discovery directly into `ConversationPicker` with clear sections/filters (**Start new: Codex / Claude**, **Active open sessions**, **Companion chats**), eliminating the redundant session picker buried inside `Change model → Advanced`.
- Bind picker selection, highlight restoration across live refreshes, and final attachment confirmation strictly to stable `(provider, session_id)` keys—never row index or display title—using a monotonically increasing discovery generation to discard stale async results. Re-verify the chosen `(provider, session_id)` on confirmation; if a selected session disappears during discovery or before confirmation, keep the picker open with a clear notice and disable confirmation rather than silently attaching a different row.
- Keep the route bar as a single clean **Model & effort** strip (`Next: Codex · Low effort` + **Model…** button) that opens `ModelSettingsDialog` solely for model, effort, and usage (disabled or redirected cleanly when no session is selected, never mislabeled `"Change model"` when hunting for sessions).
- On `ModelSettingsDialog → Next message`, display a short inline note with an inline **Enable override…** toggle/link when attached to an external Codex chat so disabled presets are self-explanatory. Add an explicit unsaved-changes hint or **Save & close** button.
- Update `WindowFrame.begin()` / `drag()` so dragging a zoomed titlebar restores `normal` state anchored cleanly under the pointer.

**Acceptance checks:**
- Opening a fresh chat shows one clear primary path to start or attach a session; active Codex/Claude sessions auto-discover inside that picker and preserve drafts when switching.
- Refreshing discovery between selection and confirmation, reordering rows, duplicate session titles, stale out-of-order discovery results, and closing the picker mid-discovery never attach the wrong session or raise callback errors; a disappeared selected session disables confirmation and displays a clear notice.
- At `440px` minimum width, the active session name and model summary remain legible without clipping toolbar buttons.
- Hands-free voice commands (`switch to …`, `new Codex chat`, `new Claude chat`) continue working against the updated controls.

---

### U12. Active-mode badges and compact voice panel

**Problem:**
- When **Hands-free voice**, **Push-to-talk (Keypad -)**, or **Live gear comparison (Ctrl+Alt+F9)** is active, the main chat window has no persistent visual indicator showing that a background listener/hotkey is armed.
- Keeping push-to-talk dictation enabled requires keeping a full `650×720` [VoiceDialog](../wow_helper/voice_ui.py) open the entire time (closing it disables voice).

**Planned changes:**
- Add a lightweight status-pill strip in `CompanionWindow` (visible only when one or more modes are active) showing clickable badges such as `● Hands-free`, `● Mic (Keypad -)`, or `● Live gear (Ctrl+Alt+F9)`. Clicking a badge focuses its control panel; badges stay immune to routine `save_layout()` refreshes.
- Give `VoiceDialog` its own compact default geometry (e.g., `420×270`, minimum `360×230`) with a collapsible **Last transcript** drawer, freeing second-screen space while keeping the explicit-enable / close-disables safety model intact.
- Give `HandsFreeDialog` a cleaner tabbed or toggleable **What you can say** quick-reference sheet formatted as short grouped examples instead of a wall of prose.

**Acceptance checks:**
- Arming any of the three modes displays its badge on the bound window; disarming or closing removes the badge immediately.
- `VoiceDialog` fits cleanly at `360×230` without clipping `Enable`, `Hold to talk`, or `Disable / cancel`.

---

### U13. Named journal picker and fight-analysis clarity

**Observed problems:**
- Clicking `Open journal` in [task_window.py](../wow_helper/task_window.py) opens Windows File Explorer pointing at `.runtime/chat/journals/`, where files are named `<uuid>.json`—making it impossible to tell journals apart by name.
- Editing the `journal_name` field in the Journal panel does not persist the rename until a new note is added.
- Players looking to review a boss wipe encounter two similarly named dialogs in two different menus: `Ask about the last fight…` (top of cog menu, reads combat log digest) and `Tools → Post-fight coaching…` (manual notes + screenshot + attempt comparison).

**Planned changes:**
- Replace `Open journal`'s OS file dialog with a themed **Open journal** picker dialog listing journals by title, note count, and last-modified timestamp (reusing the journal enumeration pattern from `SaveAdviceDialog`), plus an explicit **Rename** action in the Journal toolbar that saves immediately.
- Either combine **Ask about the last fight** and **Post-fight coaching** into a single tabbed **Fight review** workflow (Question + optional Combat log digest + optional Screenshot + optional Compare earlier attempt), or keep them side-by-side under a single clearly labeled **Fight review** menu group with unmistakable labels (**Combat log digest…** vs. **Manual notes & screenshot…**). See [Open product decisions](#open-product-decisions).

**Acceptance checks:**
- `Open journal` displays human-readable journal titles (never raw UUIDs) and refuses unreadable files without losing drafts.
- Renaming a journal persists across restart without requiring a dummy note.

---

## Batch 4 — High-value activity flows, review clarity, and onboarding

This batch elevates the specialized WoW workflows, lowers pre-send review fatigue, and brings CLI-only setup into the desktop app.

### U14. Master-detail Quest guide and Character table

**Problem:**
- [QuestTree](../wow_helper/quest_tree.py) simulates wrapped paragraphs by splitting every line with `textwrap.wrap()` into separate `ttk.Treeview` rows—so players cannot select or copy quest details/guide steps, source links have no hover cursor or underline, and every window resize re-renders all quests.
- `guide_auto` defaults to `True` on desktop `Quest guide` ([activities.py](../wow_helper/activities.py)), so expanding a quest simply to read its objectives immediately queues AI web research (whereas `ActivityDeck` in [wow_displays.py](../wow_helper/wow_displays.py) deliberately defaults `guide_auto` to `False`).
- `Character status` ([task_window.py](../wow_helper/task_window.py)) prints equipment as unaligned plain text (`Chest: item 19019 · level 60 · durability 84%`) and appends Gear Research to the bottom of the same text box.

**Planned changes:**
- Redesign `QuestTree` as a clean `ttk.PanedWindow` master-detail view:
  - Top/left pane: scannable quest list grouped by priority (**Ready to turn in**, **Current zone**, **In progress**, **Nearby pickups**), showing level, title, zone, and guide status badge.
  - Bottom/right pane: selectable, copyable rich text (`tk.Text` reusing U06 formatting) showing objectives, progress, AI guide steps, caveats, clickable source links, and an explicit **Research this quest** / **Retry guide** button.
- Format **Character status** with a readable equipment list/table (highlighting low durability clearly, showing item name when exported by the addon with item ID as secondary detail) and place **Gear research** in a dedicated split pane or sub-tab so refreshing character status doesn't push research out of sight.

**Acceptance checks:**
- Players can select and copy quest objectives and guide steps, click underlined source links with `hand2` cursor, and expand/select quests without unintended scroll jumps or resize thrashing.
- `Quest chat`, `Pin selected quest step to Play…`, `Research selected quest chain…`, and `Ctrl+K` quest jump continue targeting the selected quest accurately.

---

### U15. Scannable pre-send review previews

**Problem:** Pre-send review screens (`RequestDialog`, `FollowupDialog`, `DiscussionNotebook`, `ChainDialog`, `ToolAccessDialog`, `SaveAdviceDialog`) dump raw `json.dumps(..., indent=2)` and full `SKILL.md` system instructions inline ([activities.py](../wow_helper/activities.py), [chain_ui.py](../wow_helper/chain_ui.py), [tool_access_ui.py](../wow_helper/tool_access_ui.py)). Pages of boilerplate induce review fatigue, undermining the safety value of explicit review.

**Planned changes:**
- Introduce a shared `ReviewSummary` presentation for pre-send review dialogs, derived directly from the single frozen prepared request and bound destination object (never from live mutable form widgets, so the summary cannot diverge from what is dispatched):
  - **Overview tab (default):** Structured human-readable summary card showing **Destination chat**, **Model & effort**, **Game edition**, **Your question / task**, **Included items** (e.g., `14 quests snapshot (3m old) · 1 built-in skill · 0 local files · ~2.4 KB`), and **Privacy / gaps** in crisp bullet points.
  - **Full payload tab:** The exact verbatim text/JSON/SKILL bundle that will be sent, unchanged and fully inspectable.
- Keep the exact reviewed payload and destination frozen at prepare time so editing any input, attachment selection, or target conversation immediately invalidates the review and disables Send (both button and hands-free spoken Send) until prepared again.

**Acceptance checks:**
- Every review dialog shows the exact destination, edition, attachments, and privacy notes above the fold without scrolling, derived from the same frozen prepared request shown verbatim on the **Full payload** tab.
- Neither button Send nor hands-free spoken Send can dispatch an unprepared or invalidated review.
- Editing form inputs, changing attachment selections, or switching the destination session invalidates the review and requires re-preparation before Send re-enables.
- Dispatched payload and destination match the frozen reviewed request identically.

---

### U16. Friendly inputs and player-facing copy

**Problem:**
- Several dialogs ask players to hand-type developer formats: `IANA time zone (for example America/New_York)` and `Reset time (HH:MM, 24-hour)` in [goal_ui.py](../wow_helper/goal_ui.py); `Image capture time (optional ISO 8601 with time zone)` in [journal_ui.py](../wow_helper/journal_ui.py); `Period start/end (ISO timestamp with timezone)` and a `"Not checked"` / `"Checked"` combobox instead of a checkbox in [economy_notebook.py](../wow_helper/economy_notebook.py).
- Notices across dialogs use audit-spec phrasing and internal jargon (`starts its CLI`, `idle thread`, `advertised model`), and [tool_access_ui.py](../wow_helper/tool_access_ui.py) still repeats `"Provider connection, native conversation binding, and runtime authorization remain unverified"` even though synthetic live authorization checks passed for both providers (see [README.md](../README.md)).

**Planned changes:**
- In `GoalDialog → Repeat`: prefill the host's local IANA time zone when detectable (using `tzlocal`/Python zoneinfo fallback or Windows timezone mapping), offer a quick preset picker for common NA/EU WoW daily & weekly reset times, and validate clearly inline.
- In `EconomyNotebook`: replace the `"Not checked"` / `"Checked"` combobox with a standard `ttk.Checkbutton`, and add quick-fill helpers (`Today`, `Last 7 days`, `Use local time`) that format valid timezone-aware timestamps automatically.
- In `BookmarkDialog`: add a `"Now (local)"` helper or simple local date/time input for optional image capture time while still accepting ISO 8601.
- Do a focused plain-language pass over user-facing notices and labels (`chat_window.py`, `model_settings_ui.py`, `journal_ui.py`, `gear_ui.py`, `tool_access_ui.py`, `chain_ui.py`) to keep every accuracy/privacy truth intact in shorter, clearer player language and remove stale unverified disclaimers.

**Acceptance checks:**
- Setting a weekly recurring goal or confirming an economy import requires no manual ISO-8601 or IANA typing in the common local case, while still validating custom overrides strictly.
- Existing tests checking safety semantics pass; updated copy accurately reflects verified vs. unverified boundaries.

---

### U17. Dual-display touch ergonomics

**Problem:** In [wow_displays.py](../wow_helper/wow_displays.py), `ActivityDeck` starts with large 2×2 touch cards, then drops the player into standard desktop `TaskWindow` views with 8–10pt controls; `QuestLogDisplay` uses a single-line `tk.Listbox` at 17pt that clips long quest titles off the right edge.

**Planned changes:**
- Replace `QuestLogDisplay`'s clipping single-line `Listbox` with a wrapped touch-friendly list (or scrollable button/card rows with clear spacing and >= 44px row height) plus clear visual grouping between Turn-in, Active, and Pickup quests.
- Pass a `touch=True` display mode into `TaskWindow` instances hosted inside `ActivityDeck` to apply larger touch button padding, larger tab hit targets, and comfortable text sizes without altering normal desktop windows.

**Acceptance checks:**
- Long quest titles wrap cleanly at 1280×800 and narrower touch widths without horizontal clipping.
- `ActivityDeck` preserves per-activity state, `Return to Dias`, and `Swap screens` behavior with larger touch targets.

---

### U18. In-app setup and health check

**Problem:** Essential first-run and troubleshooting utilities (`install-addon`, `check-snapshot`, `--wow-root`, and assistive keybind `bind` / `enable` / `stop` / `status`) exist only as CLI subcommands in [__main__.py](../wow_helper/__main__.py), even though the GUI directs players to install the addon and `/reload`.

**Planned changes:**
- Add a lightweight **WoW setup & health…** dialog (reachable from `Settings → Preferences`, `Ctrl+K`, and an inline **Setup & install addon…** button shown in `Quest guide` / `Character status` empty states when no snapshot exists).
- Inside the dialog, expose existing local backend routines with explicit confirmation:
  1. **WoW install folder:** display detected/configured install roots (without printing paths to logs/tests) and allow picking `--wow-root` via folder picker.
  2. **Companion addon:** show install status per detected edition (`_forever_`, `_classic_`, `_classic_era_`, `_retail_`) and run `wtf.install_addon(...)` on an explicit button click, with the clear follow-up instruction (`/reload` in game).
  3. **Snapshot check:** run `check.report(...)` and display readable pass/warn checks.
  4. **Assistive keybind status:** show read-only enabled/stub/mapping state from `Assistant.status()` with an explicit **Stop assistive input** safety button (keep keybind registration explicit and clearly separated from advice features).

**Acceptance checks:**
- Fresh `Quest guide` / `Character status` with no snapshot offers a one-click path to `WoW setup & health…`.
- Addon installation and snapshot check run off the Tk event loop, never touch game input, and handle missing folders gracefully.

---

## Product decisions applied

The three reversible product choices from the plan were resolved conservatively to stay backward-compatible with existing workflows and tests while adding explicit user controls:

1. **Desktop `Quest guide` default for `Guide on expand` (U14):** Kept desktop `guide_auto=True` by default (`ActivityDeck` stays `guide_auto=False`) and added an explicit **Research quest** / **Retry guide** button inside the new master-detail detail pane so players can turn off `Guide on expand` and trigger guides on demand.
2. **Fight-analysis dialogs (U13):** Kept both **Ask about the last fight** (combat log digest) and **Post-fight coaching** (manual notes, attempt comparisons, and screenshots) as distinct tools with clearer descriptions and direct cross-link buttons between them that preserve drafts.
3. **Hands-free voice chat fallback (U12):** Kept direct-to-chat as the default and added an opt-in **Commands only** checkbox in `HandsFreeDialog`, with a hint line below it: chat then needs "ask the agent …" or "tell the agent …". (Until 2026-11-27 the whole explanation was the checkbox label, which was cut off at the dialog's minimum width.)

## Cross-review dispositions (`20261124-013949-cross-review`)

Reviewed by `codex-astra` (`gpt-6-astra`, `high`, 2026-11-23). All three findings were accepted, folded into the implementation, and covered by synthetic regression tests:

| Finding | Section | Disposition | Implemented change & regression test |
| --- | --- | --- | --- |
| `UX-01` | [U05](#u05-smart-transcript-scrolling) | Accepted & implemented | Content-anchored scroll restoration (`(message_id, char_offset, y_offset)`) with `Jump to latest` button; verified in `tests/test_ux_batch1.py` and `tests/test_chat_window.py`. |
| `UX-02` | [U11](#u11-unified-session-picker-and-compact-model-pill) | Accepted & implemented | `ConversationPicker` live discovery bound to `(provider, session_id)` with generation tracking, duplicate-title reordering, disappeared-session refusal, and cancel-safe close; verified in `tests/test_ux_batch3.py`. |
| `UX-03` | [U15](#u15-scannable-pre-send-review-previews) | Accepted & implemented | Shared `Overview` + `Full payload` review notebook derived from the frozen prepared request across `RequestDialog`, `FollowupDialog`, `DiscussionNotebook`, `ChainDialog`, and `ToolAccessDialog`; button and hands-free spoken `Send` refusal on unprepared/invalidated reviews verified in `tests/test_ux_batch4.py`. |

## Verification status

- **Automated synthetic verification (isolated Windows desktop):**
  - Batch 1–4 regression suites added in `tests/test_ux_batch1.py`, `tests/test_ux_batch2.py`, `tests/test_ux_batch3.py`, and `tests/test_ux_batch4.py`, plus updated behavior assertions in `tests/test_chat_window.py` (smart scrolling) and `tests/test_active_session_search.py` (Command library `Enter` copy vs `Ctrl+Enter` web search).
  - Full pytest suite (`python -m pytest -q -p no:cacheprovider`, including `tests/test_no_input.py`, `tests/test_handsfree.py`, and `tests/test_voice_browser.py`) and public-repo `scripts/leakcheck.sh origin/main...HEAD` run before landing.
- **Single-display visual check (2026-11-27, synthetic test desktop):**
  - Method: every UI test file (30 files) ran on the isolated test desktop twice, once with **Classic** and once with **Modern Synth** forced. Each window was captured when it opened, at the end of its test and before it closed. A second pass forced every window to its minimum size (`440×580`, compact Play `340×300`, dialog minimums) with a 20-point chat font and logged any control drawn smaller than it requested. The captures were reviewed by eye on contact sheets. They ran at the test desktop's default Tk scaling on one synthetic display, and stayed outside the repository because test surfaces show local paths.
  - Fixed, each with a regression test that failed first:
    - Classic left unstyled ttk frames, labels, tree headings, entry bevels and the waiting bar on clam's stock grey and white (Change model's active sessions, Provider usage, Command library, Activity history, Search companion, the saved-draft label, `BusyBar`): `tests/test_ux_batch1.py::test_u04_plain_ttk_frames_labels_and_tree_headings_use_the_theme`.
    - Button rows ran past the right edge at the 440 px minimum: Screen adviser (Setup hidden, Ask agent cut), the Quest guide's **WoW setup & addon…** prompt, Journal's **Resume session**, the Personal goal presets and Ask about the last fight's combat-log buttons. They now wrap onto another line (`wow_helper/flow_row.py`; presets also in `tests/test_ux_batch4.py::test_u16_goal_presets_stay_fully_visible_at_minimum_size`).
    - Labels beside buttons pushed the buttons out: Post-fight coaching's **Ask with combat log…**, setup health's **Choose folder…** and **Auto-detect**, and **Stop assistive input**. The label wraps now. Fixed-width notes overflowed in Voice input, the Window setup **Capabilities** tab, Post-fight coaching's **Earlier attempt** tab and Live gear comparison's **Result** tab; they wrap to the window now, and so does Live gear's **Review region** note, which had the same fixed width. Hands-free's **Commands only** label was cut off, so its explanation moved to a hint line.
    - Dialog bodies taller than their minimum pressed buttons and fields flat: Change model's **Choose a different model** and effort note, the Post-fight coaching and Ask about the last fight fields, Bookmark this moment's options and time fields (with a 20-point font, the context checkbox), Voice input's **Enable** button, WoW companion displays' touch buttons, setup health's **Copy report** and report text, and the window chooser's **Open saved preset…**. Text areas now pack last so they shrink first. Fixed forms got taller minimums: Change model `430×575`, Personal goal `440×520`, Post-fight coaching `440×580`, Ask about the last fight `440×540`, Voice input `360×350`, Hands-free voice `440×540`, WoW companion displays `460×400`, WoW setup & addon health `460×580`. The chooser's spacing was tightened instead.
    - At the 440 px minimum in Classic, Tk squeezed Session economy analysis's five tabs by 2 px each and cut their labels. The dialog's minimum width is 460 px now.
    - `tests/test_minimum_size_fit.py` opens 22 surfaces at their minimum size in Classic (scaling 1.33) and Modern Synth (1.67), with the default and a 20-point chat font, visits every tab, and fails on any button, checkbox, label, entry or combobox drawn smaller than it requests or past its row, and on any notebook tab drawn narrower than it is in a wide window. The 20-point font now also reaches the windows a surface opens; before, the Quest guide, Character, Journal, Screen adviser and chooser cases ran at the default font. Forcing each theme also ran the whole file (88 surface cases and 6 preview checks) with Classic at 1.67 and Modern at 1.33; 94 of 94 passed in each run.
  - The check first left seven issues alone. On Matt's go-ahead they were fixed afterwards, each with a regression test that failed first:
    - The Chat appearance preview kept a fixed height and cut its second message at 20 points. The dialog's minimum height now grows with the font, up to the screen height, so both messages stay whole (`WindowFrame.fit_text`; `tests/test_minimum_size_fit.py::test_chat_appearance_preview_shows_every_line_as_the_font_grows`).
    - Review **Overview** text used the chat font, so at 20 points the Overview needed scrolling. The Overview now keeps the chat font family at no more than the default 11 points, so U15's "without scrolling" holds at any chat font size. **Full payload** keeps the chat font (`tests/test_ux_batch4.py::test_u15_review_overview_fits_without_scrolling_at_a_large_chat_font`).
    - The **Saved draft** preview used Tk's fixed-width font. It now uses the message box's font and colors (`tests/test_agent_picker_ui.py::test_saved_draft_preview_reads_like_the_message_box`).
    - After a failed snapshot read, the Quest guide list still said "Loading the saved quest snapshot", and at 20 points the Quest column cut that row. Loading, failed and empty states now read in the detail pane, which wraps, and a failed refresh keeps quests that were already read (`tests/test_ux_batch4.py::test_u14_quest_guide_states_read_in_the_detail_pane`).
    - Very old saves were counted in minutes ("Saved 29930290 minutes ago · stale"), the Quest guide notice counted seconds and Tool access counted fractional minutes. Ages now read in whole minutes, hours or days on the companion display, the restored-report and Quest guide notices, Tool access and the snapshot warnings (`quests.age_span`; `tests/test_quests.py::test_snapshot_ages_move_to_hours_and_days`, `tests/test_wow_displays.py::test_age_label_marks_stale_snapshots`).
    - Classic notebook tabs and tab pages kept clam's light grey outline. They use the gold edge now (`tests/test_ux_batch1.py::test_u04_notebook_tab_outlines_use_the_theme_edge`).
    - At minimum size with a 20-point font, Resume session and Goals and wishlist showed one line of the selected entry. (The first note blamed the saved-advice list, but the list kept its five rows; the reading pane under the buttons was what shrank.) The pane now keeps three lines of its font, and the minimum height rises to make room (`tests/test_minimum_size_fit.py::test_saved_advice_reading_pane_keeps_three_lines_at_minimum_size`).
  - Observed and left unfixed:
    - At the minimum width with a 20-point font, the Quest guide's **Quest** column cuts long quest titles and group headings (264 px of text in a 173 px cell on the synthetic snapshot). The detail pane shows the selected quest's full title.
- **Not yet verified (requires operator live walkthrough):**
  - **Classic** and **Modern Synth** on real multi-monitor and touch (Dias) displays, and at Windows display scaling above 100% on real hardware.
  - Live in-game WoW session walkthrough (real addon install/snapshot check, live gear tooltip capture, and live Lugos Voice turns).
