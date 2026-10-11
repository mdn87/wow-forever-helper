# Future upgrades: Fable review and disposition

Reviewed on 2026-10-11. Subject: [FUTURE_UPGRADES.md](FUTURE_UPGRADES.md) at commit `5f8508ebfe65075f6bae65802185f61d8221aca1`.

Roundtable ran two review perspectives, product value and technical feasibility, followed by a synthesis. All three used `claude-fable-5-1`, completed their moves, and exited successfully; Roundtable reported `converged`. The reviewers received a captured copy of the plan, current project rules, product documentation, and selected implementation files. This document records the findings retained after Codex checked their evidence and narrowed several claims. Raw review artifacts remain in ignored local storage.

Status: review complete; recommendations not applied. The upgrade plan, all ten addon ideas, and the interface ideas remain unchanged. No feature implementation or new in-game validation occurred.

## Assessment

The ideas fit a companion built around continuing agent sessions. The plan correctly distinguishes an in-game Lua API, SavedVariables or manual exports, and an external agent bridge. It also distinguishes present capabilities from proposed integrations. The most useful improvement is to choose one first increment and specify how its evidence and conversation stay connected.

Fable recommends **Linked journal and Resume session** first. That would make existing advice useful across sessions and provide reusable links for goals, checklists, and later addon analysis. This is a recommendation, not an adopted change to the roadmap. A short BugSack troubleshooting preset remains a smaller experiment in agent-assisted addon work; Journalator offers a more substantial next integration once its CSV format is verified.

## Findings to resolve before selecting implementation work

### 1. Choose one first increment

The plan prioritizes quest chains and gear comparisons at line 69, BugSack and Journalator at line 153, and Compact pinned advice in the interface sequence at lines 157-193. These can be separate tracks, but the document gives no rule for choosing between them.

Add one overall starting point with a small observable outcome. Compare proposals by usefulness to a continuing conversation, new data required, edition uncertainty, and whether a manual experiment can establish value first. A Journalator workflow still depends on a Journalator export; needing no change to our addon does not remove that dependency.

### 2. Define the saved link between advice, evidence, and conversation

The proposed links between Journal, Character status, Screen adviser, and chat are described in product terms, but their persistence and resume behavior need a shared design. Existing quest research and Quest chat can use different conversations; reopening a note cannot assume the current window has the original session selected. See [current chat behavior](CHAT.md) and [context preparation](../wow_helper/activities.py).

Retain the source conversation, request or reply reference where available, game edition, and evidence timestamp in private local metadata. Opening a saved item should remain useful when its conversation is unavailable. Continuing a conversation and sending updated context should be distinct, explicit actions. Reuse these references across goals and bookmarks without forcing every bookmark to be a goal.

### 3. Specify what imported data will be sent and retained

Items 6-10 introduce third-party text, profiles, and encounter or transaction records. The plan promises a context preview, but should also define field selection, identity minimization, and what remains in companion and provider history. The current preparation path passes selected file contents to an agent; describing that content as untrusted data does not remove sensitive values. See [preparation code](../wow_helper/activities.py) and [chat privacy and retention](CHAT.md).

Make the normalized content reviewable before sending and provide a way to omit or replace unnecessary identifiers, including the player's own identity. Keep source files and session identifiers private. This is a design recommendation for provider-bound context; [AGENTS.md](../AGENTS.md) prohibits publishing real play data but does not prohibit keeping it in private local storage. Which identifying fields each addon actually exports remains unverified.

### 4. Design bounded imports instead of assuming arbitrary text fits chat

Ordinary chat messages have a 6,000-character limit, and selected context files have a 64,000-byte limit. Larger error reports or CSV files therefore need explicit size handling; the review did not measure typical addon export sizes. See [message limit](../wow_helper/chat.py) and [context-file reader](../wow_helper/activities.py).

For BugSack, allow a small pasted report or a reviewed file within supported limits. For Journalator, validate the CSV schema and compute totals in the desktop app before providing a bounded summary to the agent. Preserve the plan's distinction between transfers, income, cash movement, and profit. Reject or explain unsupported and oversized inputs rather than silently truncating evidence.

### 5. Keep future tools within the selected context

The plan already acknowledges that a local tool API needs provider integration and capability checks. Add the missing scope rule: a tool should expose only records the user selected for that conversation. Opening a note or selecting a session must not silently publish newer game data. File bundles remain a suitable first implementation.

For future records, distinguish game capture time, file save time, and import time. Missing or user-supplied times should be labeled accordingly; an import timestamp is not proof that game state is fresh.

## Recommendations narrowed or not adopted

| Fable recommendation | Disposition after checking the plan and code |
| --- | --- |
| Treat missing snapshot history, item stats, and a Details export as newly discovered blockers. | These are implementation prerequisites already acknowledged at plan lines 42, 50, and 130. Specify them when selecting those features; their absence is not a defect in a proposed backlog. Manual repeatable checklists do not require a snapshot archive. |
| Require a particular Details transport or item-suffix export. | Keep these as investigation questions. The review did not establish an exhaustive set of transports or validate Forever item variants. The plan's explicit-input and research fallbacks remain valid. |
| Build the Activity list before a pinned reply indicator, and pinning before named layouts. | No mandatory dependency was established. Existing response tracking in [chat_window.py](../wow_helper/chat_window.py) already distinguishes response outcomes. Layouts can arrange existing full windows. |
| Treat the first five ideas as contradicting the agent-session purpose. | Their agent tasks are already mapped at plan lines 92-98. Consistent Input / Agent contribution / Completion check headings could improve scanning, but are an editorial improvement. |
| Require all goal, checklist, and bookmark ideas to use one goal record. | Share source references and continuity behavior; decide which records need distinct completion, recurrence, or timeline semantics during design. |
| Forbid game-input entries in a companion command menu. | A focused companion cannot satisfy the existing WoW-foreground delivery check. Clarify preview or preparation behavior if this feature is selected; the backlog does not currently promise dispatch from that menu. |

## Proposed first increment and acceptance checks

Save a selected reply to Journal with an optional next-time goal and private references to its conversation and evidence. Add a Resume session view that opens those saved items. The following are proposed checks, not tests executed by this review:

1. Saving from Agent chat or Quest chat preserves the selected reply and its available source metadata, with a review step before saving.
2. Restart preserves the saved content and links. An unavailable conversation leaves the note readable and explains why it cannot be resumed.
3. Opening a note or selecting Continue conversation sends no request and does not replace an unsent draft.
4. Sending a follow-up previews the chosen historical context and any explicitly refreshed context, retaining their distinct timestamps.
5. Synthetic fixtures cover unavailable sessions, missing evidence, save failures, and restart. Public artifacts contain no real session or character data.

## Limits of this review

The pass checked documentation and supplied source code. External addon listings, export schemas, typical file sizes, Forever compatibility, and simulation accuracy were not validated by the Fable reviewers. The disputed random-suffix and addon-export details remain questions for a focused integration investigation. No addons were installed, no real play data was inspected, and no app behavior tests were run for this documentation-only review.
