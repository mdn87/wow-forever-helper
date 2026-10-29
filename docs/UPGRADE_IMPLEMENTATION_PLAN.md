# Companion upgrade implementation plan

Status: F01–F06, F08, F12, F13, F16, and F17 delivered. Updated: 2026-10-29. Original baseline: `c5fa294`.

This is the build sequence for the ideas in [Future upgrades](FUTURE_UPGRADES.md), incorporating the checked [Fable review](FUTURE_UPGRADES_REVIEW.md). It supersedes the competing priority lists in that research document. All ten addon ideas and the earlier interface ideas are retained. Current behavior remains documented in [Chat](CHAT.md), [Quests](QUESTS.md), and [Assistive input](ASSISTIVE_INPUT.md).

The product outcome is a continuing conversation that can use selected game evidence, explain choices, remember what the player decided, and revisit the result. Each feature below must complete a useful part of that workflow. Addon inspiration does not imply a dependency on that addon or verified Forever compatibility.

**Operator-selected sequence F13, F16, F17, and F06 is delivered.** F01–F03 are also implemented as recorded below. F04 personal goals and wishlist is also delivered. F12 activity history with persistent manual state and action history is also delivered. F05 repeatable activity checklists is also delivered. F07 now has a selected on-demand live interaction; implementation starts with client capture and extraction proof. Other ideas remain parked. Complete, verify, and land one feature before moving to the next. The Requires column identifies actual dependencies. No dates or delivery estimates are assumed.

## Build sequence

| Order | Feature and first deliverable | Requires | Original idea | State |
| --- | --- | --- | --- | --- |
| [F01](#f01-linked-journal-and-resume-session) | Save advice with its conversation and evidence; resume from Journal. | Existing chat and Journal | Linked journal / Resume session | Delivered |
| [F02](#f02-compact-pinned-advice) | Pin selected advice in a compact Play view. | F01 source references | Compact pinned advice / Play and Desk views | Delivered |
| [F03](#f03-saved-activity-layouts) | Save and restore named arrangements of companion windows. | Existing window manager | Saved activity layouts | Delivered |
| [F04](#f04-personal-goals-and-wishlist) | Track selected goals and their researched next steps. | F01 | Addon 4: ALL THE THINGS | Delivered: manual goals and reviewed research |
| [F05](#f05-repeatable-activity-checklists) | Today and This week lists with manual completion and explicit repeat rules. | F04 | Addon 5: SavedInstances | Delivered: manual recurrence and reviewed planning |
| [F06](#f06-quest-chains-and-prerequisites) | Research one selected chain and continue discussing it in Quest chat. | F01 | Addon 1: BtWQuests | Delivered: selected-chain research, not an addon database |
| [F07](#f07-explainable-gear-comparisons) | Compare visible item tooltips on an explicit player request, without reload. | F01; live capture and extraction proof | Addon 2: Pawn; Raidbots comparison pattern | Selected interaction; live implementation unverified |
| [F08](#f08-addon-troubleshooting) | Review an error import and keep diagnosis and retries in one conversation. | F01; builds the shared import layer | Addon 6: BugSack | Delivered: pasted or imported error text; no automatic addon discovery |
| [F09](#f09-session-economy-analysis) | Import a supported Journalator CSV and discuss deterministic totals. | F08 import layer, F01 | Addon 7: Journalator | Queued; export schema unverified |
| [F10](#f10-screenshot-markup) | Crop, annotate, and mask a selected image before sending it. | Existing Screen adviser | Screenshot markup | Queued |
| [F11](#f11-session-bookmarks) | Save a manual timestamped note with optional reviewed image and context. | F01; F10 for edited images | Session bookmarks | Queued |
| [F12](#f12-activity-list) | Collect request outcomes and open the relevant conversation. | Existing response tracking | Activity list | Delivered: quiet outcomes, persistent manual state, reviewed retries |
| [F13](#f13-search-and-command-menu) | Find saved content and companion actions with Ctrl+K. | F01; expands with future F04/F12 records | Search and command menu | Delivered |
| [F14](#f14-inventory-preparation) | Export bag contents and explain supplies or changes between selected snapshots. | F08 evidence/import conventions; addon field validation | Addon 3: Baganator | Queued; client fields unverified |
| [F15](#f15-post-fight-coaching) | Review one supported encounter summary and compare a later attempt. | F08 import layer, F01 | Addon 8: Details! | Queued; transport and fields unverified |
| [F16](#f16-build-tutor-and-experiment-notebook) | Explain a supported character profile and an optional existing simulation report. | Bounded profile import; full F07 inspection remains separate | Addon 9: SimulationCraft | Delivered: Retail static subset and manual notes; simulation accuracy unverified |
| [F17](#f17-dungeon-route-walkthrough) | Discuss a selected route; decode supported route strings only after validation. | F01; existing bounded image import | Addon 10: Mythic Dungeon Tools | Delivered: manual image/text discussion; MDT decoder unsupported |
| [F18](#f18-local-read-only-agent-tools) | Let a configured agent read only context published to its conversation. | Stable records from F08 and at least one importer | Optional addon-to-agent tool interface | Later extension |
| [F19](#f19-recording-linked-review) | Add recording evidence in measured stages, beginning with lifecycle and recovery. | F11; existing recording proposal | Recording-backed Journal | Later extension |

When a listed external capability is unavailable, record exactly which adapter remains unverified and continue with the next independent feature. A screenshot or typed discussion can be delivered separately, but must not be counted as completing an addon integration.

## Shared implementation decisions

- **Conversation selection:** use the existing provider plus session identity. Save the source message ID and request ID when genuinely available; do not infer a request ID from reply text. Attached sessions retain their permissions; companion-created sessions retain their current read-only configuration.
- **Evidence:** saved advice keeps the evidence it used. Opening a note, restoring a layout, or continuing a conversation does not refresh or send context. For the new follow-up flows, Refresh reads local data and Send submits the reviewed selection. Recheck the selected session when sending a prepared request, as the current request dialog does.
- **Freshness and identity:** record edition, source, capture time when known, file save time, import time, and missing fields separately. Missing time means unknown, not fresh. An edition is not a character identity. Cross-session inventory or economy comparisons require an explicit local profile association; never infer that two newest snapshots belong to the same character.
- **Storage:** extend the existing private JSON storage under ignored `.runtime/chat/`. Keep note text usable without a provider transcript or image. Use versioned records, bounded reads and writes, existing atomic replacement and locking, and recoverable failure behavior. Do not rewrite existing journals merely by opening them. No database conversion or bulk data migration is part of this plan.
- **Privacy and imports:** new import flows preview the content actually sent and allow unnecessary identifiers to be omitted or replaced. Provider history has its own lifetime. Keep private originals out of public artifacts; use hand-written synthetic fixtures. Treat addon text, CSV, profiles, routes, and agent replies as data, never executable instructions.
- **Interface:** use Classic and Modern Synth consistently, retain keyboard access and visible focus, preserve drafts, and reuse opacity and solid-on-focus behavior. Compact windows need their own tested size constraints; do not reduce every window's minimum size. No Activity list dependency is required for pinned advice or layouts.
- **Game input:** all new features are companion advice, preparation, or navigation. Preserve [AGENTS.md](../AGENTS.md) and the current explicit one-chord input contract. No addon import or agent reply authorizes game input. A focused companion menu cannot satisfy WoW's foreground delivery requirement.

## F01. Linked journal and Resume session

**Outcome:** from an answer in Agent chat or Quest chat, choose **Save to Journal**, review the selected text and its source, optionally add a Next time item, and save. Journal's **Resume session** view shows saved next steps and opens the original conversation without sending a request.

**First scope:** saved replies, source links, optional one-off next-time items, and explicit follow-up preparation. Recurrence belongs to F05; broader wishlist metadata belongs to F04. An explicit journal save remains durable even when Remember draft and recent chat is off; explain that these are separate controls.

### Record and compatibility contract

Keep the existing journal name and entries. Introduce a format version for newly saved data while reading today's unversioned format. A linked entry adds optional fields to the current note:

| Field | Meaning |
| --- | --- |
| `id`, `at`, `text` | Existing durable note identity, save time, and user-reviewed text. |
| `source` | Provider, session ID, message ID, and request ID when known. These are private local references, not display labels or file paths. |
| `evidence` | The selected context excerpt, edition, known timestamps, source URLs, optional quest ID or equipment slot, optional app-owned image reference, and explicit gaps. Capture once; do not silently replace it with newer reports. |
| `next_time` | An optional user-written next step and manual open/done state; no inferred completion. |

Validate all metadata and count it toward the existing two-megabyte journal limit. Bound each saved evidence payload to 64,000 UTF-8 bytes and require a smaller reviewed selection if it exceeds that limit. Keep the existing 8,000-character note limit and 500,000-character journal text limit. If an answer is longer, require the user to select an excerpt; never silently save a shortened answer as complete. Old entries without IDs receive stable local identities in memory and retain them on a later explicit save. The new reader must refuse unsupported versions or damaged files without overwriting them.

### Implementation batches

1. **Journal storage and source references.** Introduce a focused `wow_helper/journal.py` service, with `ActivityService` delegating existing journal operations so callers keep working. Add backward-compatible loading and linked-entry saving. Repeated saves with the same note ID and identical content/metadata are idempotent; conflicting repeats fail with the draft preserved. Serialize updates from multiple windows with the existing lock and atomic write behavior.
2. **Save selected advice.** Add Save to Journal to `ChatWindow` and its Quest chat subclass. Capture the selected assistant message when the save dialog opens. Derive evidence from its associated preparation/receipt or the conversation's frozen quest context, never from an unrelated currently displayed report. Mark unavailable associations as unknown; add a bounded local association at request preparation where needed. Freeze that selection if a later reply arrives or the active tab changes. Select an existing journal or create one; never overwrite the target Journal window's unsaved editor text. Keep the existing Copy latest reply action usable.
3. **Resume view and navigation.** Extend Journal in `TaskWindow` to list saved advice and open Next time items. Add a window-manager operation that reuses an already open conversation when possible, including a matching Quest chat. Otherwise open a normal chat bound to the saved session. Opening must use the restore/bind path, not session creation or the Quest chat opening request. At the eight-window limit, explain the limit and retain the note and drafts.
4. **Explicit follow-up.** Prepare a request from the selected note and historical evidence. Offer an explicit local refresh for compatible report data, showing old and new times separately. Preview the exact selected bundle and target conversation, then require Send. Session changes invalidate the preview; unknown context stays unknown. An unavailable original session leaves the note readable, with any new conversation creation explicit.
5. **Verification and documentation.** Exercise the checks below, inspect synthetic Windows views, update current behavior in `docs/CHAT.md`, and record the completed commit and test evidence here. Land the feature before starting F02.

**Files to extend:** [activities.py](../wow_helper/activities.py), [chat_window.py](../wow_helper/chat_window.py), [task_window.py](../wow_helper/task_window.py), [workspace.py](../wow_helper/workspace.py), [quest_chat.py](../wow_helper/quest_chat.py), and [window_state.py](../wow_helper/window_state.py). Add `journal.py`; only change [agent_sessions.py](../wow_helper/agent_sessions.py) if an existing receipt cannot supply required metadata. Do not expand provider permissions for this feature.

**Acceptance checks:**

- A reviewed reply from general chat and Quest chat saves once with the correct source; changing tabs or receiving another reply during the save cannot change it.
- Legacy notes remain readable and unchanged on disk after opening. Concurrent saves, failed writes, conflicting duplicate IDs, corrupt metadata, unknown versions, and Unicode size limits cannot lose existing notes or the draft.
- Restart preserves saved content and links with chat retention both on and off. Missing sessions, messages, and images explain the gap without making the note unreadable or substituting another session.
- Opening Resume session, marking a next-time item done, and Continue conversation create no agent request, no startup prompt, and no game input. Existing drafts survive navigation and the window-limit case.
- A follow-up sends exactly the reviewed historical/current context to the selected session. Double-clicks, delivery uncertainty, and restart do not duplicate the send.
- Cover storage in `tests/test_activities.py` and a new `tests/test_journal.py`; cover UI/navigation in `tests/test_chat_window.py` and `tests/test_workspace.py`; retain provider receipt and no-input regression coverage. Use synthetic Windows visual checks for both themes, large text, minimum sizes, and missing-source states.

## F02. Compact pinned advice

**Deliver:** Pin to Play creates a compact companion card from selected advice or a quest step. Show the objective, next step, source time, and response state; Expand returns to its source conversation or readable saved content. These are two presentations of the same saved selection.

**Build:** reuse F01 references and current response tracking; add per-mode geometry and persistence in `workspace.py` and `window_state.py`. Reuse theme and interface settings. A new reply must not replace the pinned selection without an explicit update.

**Accept:** pin/expand/restart preserve content and drafts; unavailable sources remain readable; restoration sends nothing; keyboard controls and text stay usable at the compact minimum size and supported opacity settings. An Activity list is not required.

## F03. Saved activity layouts

**Deliver:** save named Leveling, Preparation, and Review arrangements of the companion's own windows. Restore types, bounds, pin state, and view settings while keeping current conversations and drafts safe.

**Build:** extend `WindowManager` and versioned window state. Reuse windows where compatible; keep unsaved work accessible when an arrangement would omit it. Define a preview of changes when the eight-window limit prevents a full restore. Include compact cards if available, without making pinning a prerequisite.

**Accept:** repeated restore is idempotent; missing monitors recover onto an available screen; a failed layout save keeps the current arrangement; no restore launches research, capture, session-opening prompts, or game input. Verify drafts in omitted and reused windows.

## F04. Personal goals and wishlist

**Deliver:** add selected items, mounts, recipes, quests, or free-text goals with a source, researched requirements, a next step, and manual progress. Ask the chosen session to refine a goal, then save the reviewed result.

**Build:** extend F01 next-time records with goal-specific fields and links from Journal, quest research, and gear comparisons. Share source references with notes; bookmarks remain separate timestamped records. Use manual ownership and completion initially.

**Accept:** goals survive restart, preserve evidence and edition, distinguish user decisions from agent suggestions, and can reopen their conversation without sending. Missing evidence cannot be shown as verified ownership or completion. No ALL THE THINGS installation or comprehensive collection database is required.

**Delivered:** version-one Journal entries can carry a bounded goal, requirements, reviewed suggestions with their source and evidence, player constraints and decisions, manual status and progress, and a next step. Goals are searchable and reopen without sending. Explicit research reuses the selected conversation and the existing follow-up preview; saving a reply can update an existing goal without overwriting its original evidence or player decision. No collection database, automatic completion, or addon integration is included; F05 adds recurrence separately. See [current usage](CHAT.md#personal-goals-and-wishlist).

## F05. Repeatable activity checklists

**Deliver:** Today and This week lists for selected recurring goals, with manual completion and explicit repeat rules. Ask the session to suggest a plan for the player's available time and priorities.

**Build:** add a recurrence evaluator and completion history separate from goal definitions. Store the user-chosen time zone and reset rule; do not guess a game's regional reset from the computer clock. Reopening the app computes the current period without rewriting historical completion.

**Accept:** daily/weekly boundaries, daylight-saving transitions, missed periods, undo, restart, and clock changes behave deterministically. Manual completion is labeled. Automatic lockout or cooldown observation remains a separately unverified extension; this increment needs no SavedInstances integration or snapshot archive.

**Delivered:** per-goal Daily/Weekly rules with explicit IANA time zones, reset times and weekdays; Today/This week lists scoped to a journal; separate bounded completion/undo history; reviewed time-and-priority planning in the selected conversation. Existing goals and history remain intact on failed or conflicting saves. See [current checklist behavior](CHAT.md#repeatable-activity-checklists).

## F06. Quest chains and prerequisites

**Deliver:** select a quest, explicitly research its prerequisites and next steps, and discuss the result in its Quest chat. Show observed completion separately from sourced or uncertain dependencies.

**Build:** extend `guidance.py`, `quest_tree.py`, and `quest_chat.py`; reuse existing research queue/cache behavior and completed quest IDs. Store the selected chain and sources with the conversation. Reconcile a newer snapshot only after explicit preparation and Send.

**Accept:** edition-specific sources, missing prerequisites, incomplete evidence, ambiguous or cyclic relationships, stale snapshots, and a research failure all have explicit states. Reopening or refreshing does not silently add context to the chat. This researches selected chains; it does not copy BtWQuests databases.

## F07. Explainable gear comparisons

**Deliver:** compare an equipped item with one player-selected candidate or quest reward, for the stated build and goal, while the player remains in the game. Preserve the comparison and assumptions for a follow-up after new evidence arrives.

**Operator-selected interaction (2026-10-29):** on demand. The player hovers an item, shows the game's equipped-item comparison tooltip when needed, then presses a companion shortcut or explicitly says "compare this." One request captures the current tooltip evidence without changing game focus, moving the pointer, pressing a game key, or reloading the UI. Continuous hover monitoring is not selected. This replaces the earlier proposal to make manual candidate entry and saved equipment snapshots the primary interaction.

**First-use setup:** choose the game edition, a tooltip capture region within its window, build/role and comparison goal, and a destination conversation with image-reading support. Preview the region and approve what a comparison request sends. After this explicit setup, a compare command authorizes one bounded capture and request to that destination. Changed destinations or capture regions require a new preview. The existing voice listener is a separate component; expose an explicit command contract, and verify its connection before claiming voice support. Do not install an always-listening service.

**Data path:** capture the chosen region of the actual WoW window at request time, retaining capture time and the frozen image. Reuse the existing image-capable conversation path to extract candidate and equipped item names, visible variants, slot, stats, units and effects into bounded structured fields. Treat all image text as evidence, never instructions. Validate field types, ranges, units and item association before calculating stat differences in code. Show the extracted evidence with the result; unreadable or ambiguous fields remain unknown. Model confidence alone does not establish accuracy. A screenshot reader is not a maintained item-name library or a live connection to Blizzard's online API.

**Comparison behavior:** both items must be visible or independently identified with current evidence. If the equipped tooltip is absent, ask the player to show it and request another capture; never silently substitute the last SavedVariables equipment snapshot as current. Distinguish both ring/trinket slots and weapon combinations. Use edition-specific web research only to explain mechanics or acquisition, preserving links and separating it from observed tooltip facts. Missing client-specific data, effects or stats prevents an asserted numerical upgrade percentage. Saved character reports may supply clearly dated background context, not proof of currently equipped gear.

**Response behavior:** the screenshot is taken at invocation; the agent's explanation arrives later in the companion without taking focus. Display capture age, progress, failures and the evidence used. Measure capture, extraction and explanation latency separately; "live" does not promise an instant model response. Bound outstanding requests, retain durable request IDs, and require another explicit request after failure or uncertainty. Opening, restoring, or changing a tooltip never triggers capture or analysis by itself. Save reviewed results through F01.

**No reload dependency:** automatic or periodic `/reload` is not the data transport. This session does not establish that reload is harmless on the selected beta build or with installed addons. Any separately requested assistive reload command would remain an explicit one-shot action under the existing input contract; it would not make SavedVariables a continuous live feed.

**Implementation order:** first prove capture without focus loss and extraction against a real tooltip pair on the selected client. Then implement the bounded command/shortcut route, structured extraction and deterministic comparison, followed by conversation display and Journal saving. Keep existing Character status/Find better gear as a separate snapshot-based workflow. Do not call F07 delivered on the strength of a manual-entry form or synthetic screenshots alone.

**Accept:** real client evidence confirms capture without reload or focus loss, readable tooltip extraction, the correct equipped-item association, and measured request latency. Synthetic checks cover missing/occluded tooltips, unreadable values, resolution/DPI changes, stale frames, item variants, edition mismatches, absent image support, changed target conversations, duplicate requests, failed sends and restart without replay. Stat deltas use only validated values; missing facts and unsupported effects remain explicit. No equip action, game input, process memory reading, injection, network interception or unattended play is introduced.

**Evidence so far:** the repository already has explicit single-window image capture and image-request preparation. Pillow documents HWND-based window capture in [ImageGrab](https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html). Those capabilities do not prove GPU-rendered tooltip readability on this client. No WoW process was available during this interaction review, so actual tooltip capture, extraction accuracy, latency and the voice-command connection remain unverified. No runtime behavior changed in this design update.

## F08. Addon troubleshooting

**Deliver:** import or paste a selected error, describe the triggering action and versions, preview it, and open a troubleshooting conversation. Save hypotheses, attempted steps, and the result of the player's next retry.

**Build:** add a bundled troubleshooting skill and the first shared desktop import module. Keep provider permissions unchanged. The import record contains a format version, source kind/version, optional local profile, edition, distinct timestamps, coverage, warnings, normalized payload, and private reference to any retained original. Keep this module separate from Lua execution and chat transport.

**Import contract:** small pasted text may use the existing chat limit; larger text uses bounded file preparation. Preserve the existing 64,000-byte context-file cap for this first adapter. Check bytes before parsing, validate UTF-8 and structure, and reject unsupported or oversized content with an explanation. Preview normalized text, omitted fields, and identity replacements. No content is sent or searched until the explicit request. Treat quoted instructions inside errors as untrusted data.

**Accept:** malformed and oversized input, repeated imports, missing versions, redaction edits, session changes, and failed sends preserve the source and draft. The agent can compare two user-supplied attempts without claiming a fix from a stack trace alone. A small pasted-error workflow needs no automatic addon discovery or game-side exporter change.

## F09. Session economy analysis

**Deliver:** select a Journalator CSV and reporting period, inspect normalized rows and calculated totals, then ask the continuing session to explain spending and progress toward a goal.

**Build:** first verify a documented export version and its columns against author-maintained source; record supported schema/edition in the adapter. Add explicit byte, row, field-length, and date-range bounds in that implementation. Calculate integer-copper totals on the desktop and expose a bounded summary plus selected rows. Require an explicit profile association for cross-session comparisons.

**Accept:** synthetic exports cover quoting, encoding, unknown columns/categories, invalid amounts/dates, duplicate and overlapping imports, transfers, refunds, missing periods, and conflicting identities. Show unresolved categories and coverage; do not silently drop rows or double-count overlapping data. Distinguish net cash movement from profit and omit per-hour claims without duration evidence. Treat unsupported CSV formats as unavailable, not zero activity.

## F10. Screenshot markup

**Deliver:** crop, magnify, add an arrow, or mask selected regions before asking Screen adviser a question. Preview the exact derived image that will be sent.

**Build:** extend `screen_capture.py` and the screen task panel using the existing image dependencies. Keep the original separate from the derived image, strip metadata, flatten solid privacy masks into pixels, and bind the prepared request to that specific result. Retain the existing single-window capture boundary.

**Accept:** resize/crop coordinates and undo are correct; masked pixels cannot reappear through scaling or metadata; limits, cancel, missing files, and save failures preserve the original. Editing or restoring an image sends no request. Tests use synthetic images only.

## F11. Session bookmarks

**Deliver:** Bookmark this moment saves a manual timestamp and note with optional selected evidence or image. Reopen it in Journal and explicitly ask the original or chosen conversation about it.

**Build:** add bookmark records linked through F01 references. Request a screenshot only when explicitly selected, and show its preview before saving or sending. Keep event time, image capture time, and any manual time correction distinct.

**Accept:** note-only bookmarks work offline; missing images or conversations leave the note readable; restart preserves links; bookmarking does not start recording or agent analysis. A later video link belongs to F19 and must retain alignment uncertainty.

## F12. Activity list

**Deliver:** a quiet list of Reply received/complete, Research finished, and Request failed entries that open their source conversation or report.

**Build:** consume existing request receipts, `ResponseWait`, and guidance state. Key entries by request and event identity, preserving the difference between an attached provider's visible reply and a managed turn's completion. Persist bounded read/dismissed state without storing another full transcript.

**Accept:** progress cannot appear as completion; repeated polls and restart do not create duplicate notices; dismissed events stay dismissed; unavailable sources have a useful fallback. Opening an item neither retries nor resends its request. Retry remains explicit.

**Selected scope:** persistent manual state with history (the fourth shared pattern from the follow-up review). Store bounded read, dismiss, restore, and retry-request actions alongside outcome references. Add a quiet Settings list and search results. Retry opens a review step and requires explicit Send retry; conversation drafts are preserved. No automatic notifications or request replay.

## F13. Search and command menu

**Deliver:** Ctrl+K inside the companion finds notes, goals, quests, conversations, layouts, and companion settings/actions, with enough context to distinguish results.

**Build:** index app-owned records and currently known session metadata; do not crawl arbitrary provider transcripts or game folders. Dispatch only registered companion actions. Keep game-input-related entries limited to information or preparation under the existing contract.

**Accept:** keyboard navigation, duplicate labels, missing sources, Unicode search, index updates, and restart work. A search or navigation result never sends an agent request, captures an image, changes focus to WoW, or dispatches a game key implicitly.

## F14. Inventory preparation

**Deliver:** show selected bag contents, categories, quantities, and a goal-specific supplies discussion; compare two explicitly retained snapshots for the same local profile.

**Build:** verify available container/item fields on the selected client before extending `WoWCompanion.lua`, `character.py`, the restricted parser contract, and `check.py`. Export item IDs, quantities, supported classifications, and field availability; exclude banks until separately supported. Retain bounded versioned snapshots with edition, profile, capture time, save time, and coverage. Explain retention before collecting history; do not silently purge user data.

**Accept:** missing item-cache data, partial bags, unknown classifications, full storage, repeat imports, identity/edition mismatch, and stale captures cannot produce invented contents or misleading changes. New source fields appear in `check-snapshot`; synthetic tests and actual client checks are recorded separately. Buying, selling, and item use remain player decisions.

## F15. Post-fight coaching

**Deliver:** select one encounter, ask the agent to explain supported observations and agree on one improvement, then compare a later user-selected attempt.

**Build:** investigate Details' supported export path and selected-client fields before choosing an adapter. Prefer the smallest bounded summary that answers the question. If only screenshots and typed summaries are available, label that delivered workflow separately and leave the structured adapter unverified. Reuse F08 normalization and identity controls; preserve encounter coverage and timestamps.

**Accept:** partial or unsupported fields, duplicate encounters, actor replacements, version differences, and failed imports are explicit. Every coaching claim cites the available evidence; aggregate totals cannot establish an exact cause of death. No live combat control, automatic diagnosis loop, or game input is added.

## F16. Build tutor and experiment notebook

**Deliver:** import a supported SimulationCraft profile, state the player's role and preferences, discuss how the build works, and save a comparison question with an optional existing report.

**Build:** validate a profile grammar and edition before parsing bounded data. Link item discussions to F07 and experiments to Journal. Treat imported reports as evidence with engine/version provenance. Explain unsupported fields instead of interpreting profile text as commands.

**Accept:** malformed profiles, missing talents/items, inconsistent editions, unavailable sources, and unsupported engine results cannot produce invented numerical gains. Export readability and simulation accuracy are separate checks. Running simulations or uploading profiles to a service is outside this increment.

## F17. Dungeon route walkthrough

**Deliver:** select a route image or supported export, state dungeon, edition, and role, then hold a preparation conversation and later review the run in the same session.

**Build:** start with the existing image/text path. Before an MDT string adapter, verify format, compression/serialization, limits, and edition support; implement a bounded decoder that cannot execute content. Keep image-based Forever discussion clearly separate from verified MDT support. Do not bundle addon map artwork.

**Accept:** unsupported versions, oversized or deeply nested/compressed input, missing pulls, uncertain mechanics, and edition mismatches have clear outcomes. Use sources for additional mechanic claims. No live position tracking or automatic route execution is implied. Mark the decoder separately if only the manual discussion is delivered.

## F18. Local read-only agent tools

**Deliver:** optionally let a configured provider request selected normalized records by their opaque IDs while continuing a conversation. File preparation remains available.

**Build:** choose an interface only after actual importers establish the required record shapes. Define a per-session publication list and authentication, bounded responses, provider capability checks, and explicit removal from future access. Tools expose published records only, never arbitrary filesystem reads, fresh game queries, or input commands. Integrate each provider separately and report unsupported configurations honestly.

**Accept:** unpublished, cross-session, removed, malformed, and oversized requests are denied; stale records report their actual age; local refresh alone does not republish data. Removing access cannot erase information already in provider history. Run meaningful authorization and data-isolation tests before claiming support.

## F19. Recording-linked review

**Deliver in stages:** follow the [existing recording-backed Journal proposal](CHAT.md#proposed-recording-backed-journal), preserving manual bookmarks from F11.

1. Implement the versioned log, lifecycle controller, fake capture/clock/writer, storage accounting, and crash recovery; measure recording growth/finalization without decoding an active file.
2. After measurements, add explicit capture start/pause/stop with one worker, bounded queues, recorded gaps, and responsive stop behavior.
3. Link finalized video and bookmarks with measured timing uncertainty; preserve external originals.
4. Add optional, separately enabled agent summaries and audio transcription only after lifecycle, privacy, resource budgets, and provider support are established.

**Accept:** late captures after stop, unavailable sources, user pause, disk reserve exhaustion, process crashes, unfinished recordings, uncertain alignment, and failed analysis never cause replay, silent data loss, or an unbounded queue. Confirm the bulk-data destination before writing outside the project. This feature is not complete when only stage 1 is done; record each stage's delivered and unverified behavior.

## Completing each feature

Work in coherent batches within the selected feature. Resolve necessary implementation details against current code, then add behavior tests for meaningful success and failure paths. Do not dispatch another full review of unchanged code or add a framework for speculative later features.

Before landing a feature:

1. Run its targeted tests and the relevant existing regressions. Run the full suite once with `.venv/Scripts/python -m pytest -q -p no:cacheprovider`, then inspect the complete diff. Current CI runs Windows and Linux; record skips and failures accurately.
2. For UI work, inspect synthetic Windows views in both themes, including the affected minimum size, keyboard behavior, restart, and draft preservation. Keep any committed visual fixtures synthetic and cropped to the app.
3. For new provider paths, verify synthetic requests against each claimed provider. For new addon fields, extend synthetic parser/check coverage and perform a separately recorded client check when available. A mocked or documented API is not runtime evidence.
4. Update current-behavior docs only for delivered behavior. Record the feature's commit, tests, and any unverified integration in the table below. Use the existing leak checks and git landing rules.
5. Move to the next queued feature. If an external capability remains unavailable, record the precise limitation and the delivered fallback, then continue independent work without claiming the adapter is complete.

## Delivery record

F01–F06, F08, F12, F13, F16, and F17 are delivered. Other ideas remain parked until selected. Checks below describe only the delivered scope.

| Feature | Delivered scope / commit | Verification | Remaining work |
| --- | --- | --- | --- |
| F01 | Versioned linked notes, frozen reply/evidence selection, manual Next time items, source-session navigation, and reviewed text follow-ups. Feature commit `75d8570`, merged in PR #16. | Windows: 315 passed, 2 existing skips; subsequent managed-quest metadata fix: 7 journal tests passed. Synthetic Classic/Modern dialogs inspected at 440 × 480, plus 18-point Save text. | Existing provider transport reused; no fresh live-provider round trip. Image references retained; follow-up is explicitly text-only. Real game evidence remains outside these synthetic checks. |
| F02 | Frozen advice cards from chat, Quest chat, Journal, or a selected quest; separate Play/Desk sizes and explicit source navigation. Feature commit `809774d`, merged in PR #18; Windows and Linux CI passed. | Windows: 324 passed, 2 existing keypad-event skips. Synthetic Classic/Modern Play at 340 × 300, Desk at 440 × 580, review at 440 × 480, and 24-point text at 65% opacity inspected. | Existing source navigation reused; no fresh live-provider round trip or game check. Missing sources and times remain unknown. |
| F03 | Named arrangements with save/replace, restore previews, compatible-window reuse, card modes, and rollback on failed workspace saves. Feature commit `804cfa7`. | Windows: 346 passed, 2 existing keypad-event skips. Eighteen new checks cover storage, limits, drafts, retention, restart, monitor recovery, rollback, and no new requests. Classic/Modern dialogs inspected at 480 × 540 on a hidden desktop. | Existing provider transport reused; no new live-provider or in-game check. Dias integration remains a separate workstream. |

| F04 | Personal goals and wishlist; reviewed research in the chosen session, saved suggestions, decisions and manual progress, Journal links and search. | Windows full suite: 429 passed, 2 existing keypad-event skips. Both themes inspected at 440 × 480 with enlarged text. | Actual acquisition routes, ownership and game outcomes are unverified. Recurrence is delivered separately in F05. |
| F05 | Feature commit `c809d51`. Explicit Daily/Weekly rules, journal-scoped Today/This week lists, separate completion/undo history, and reviewed time-and-priority planning in the selected chat. | Windows Python 3.14 full suite: 504 passed, 2 existing skips; final 26 recurrence/UI checks passed after journal-navigation and failed-refresh fixes. Both themes inspected at 440 × 480 (Repeat/preview) and 480 × 560 (checklist) on a hidden desktop. | Real game resets, lockouts/cooldowns, SavedInstances integration, and live planning replies unverified. Existing provider transport reused. |
| F12 | Quiet outcome list, bounded read/dismiss/restore/retry history, source navigation, search, and explicit retry review preserving drafts. | Windows Python 3.11 full suite: 447 passed, 2 existing keypad-event skips. Final targeted checks: 16 passed, including added research retry coverage. Both themes inspected at 480 × 480; retry review at 480 × 420 with 18-point text. | Outcomes are recorded as observed, not reconstructed from all provider history. Pending tracking follows chat retention. No new live-provider or in-game check. |
| F13 | `d216458` / PR 20. Ctrl+K searches bounded app-owned notes, next steps, quests, known sessions, windows, cards, layouts, and registered actions. | Windows: 363 passed, 2 existing keypad-event skips after merging the two-display feature. Both themes inspected at 480 × 540; keyboard draft preservation, Unicode, missing sources, limits, and restart covered. | Wishlist search is delivered with F04; activity-history records are included in F12. Navigation reuses existing transport without requests. |

| F16 | `8141c6a` / PR 22. Static Retail profile import, manual notes, reviewed requests, and linked experiment notes. | Windows: 378 passed, 2 existing skips; final retention regression and 20 related checks passed. Both themes inspected at 440 × 480. | Simulation accuracy, live provider responses for this flow, and full item inspection unverified. |

| F17 | `6d30fb0` / PR 23. Manual image/text route preparation and later review in one conversation, linked notes, and safe imports. | Windows: 391 passed, 2 existing skips. Both themes inspected at 440 × 480; restart, both provider selections, and missing images covered. | MDT decoding and actual dungeon mechanics remain unverified; no live tracking or route execution. |

| F06 | `f74dd17`. Selected-chain research, sourced relationships, snapshot observations, and explicit Quest chat updates. | Windows: 410 passed, 2 existing skips. Both themes inspected at 440 × 480. Live synthetic chain schema passed for Codex and Claude. | Actual quest-chain accuracy needs edition-specific evidence; no addon database is bundled. |
| F08 | `c545ca8`. Shared bounded text import module, Addon troubleshooting notebook with locals omission and identity replacement, single reviewed send, Journal evidence, retry review bound to the original conversation, and a bundled skill. | Windows: 480 passed, 2 existing skips. Both themes inspected at 440 × 480. Synthetic Codex and Claude selections only; no live provider request. | Real BugSack exports and addon-specific diagnosis quality are unverified. No automatic addon discovery or game-side exporter. |

Add one row as each feature begins; keep the build-sequence state in sync. A feature is complete only when its selected deliverable and acceptance checks are satisfied, with any broader integration limitation stated explicitly.

F16 delivers bounded static Retail profile reading, explicit review/send, optional report provenance, and linked experiment notes. Classic Forever uses manual notes. Simulation execution, numerical accuracy, and full item inspection are not claimed.
