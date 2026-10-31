Keep the helper’s existing architecture. The most useful thing to borrow is fresh, structured game context, not another chat application. The public projects offer transport and validation code that could improve several features we already have. They do not eliminate the need to verify those features against the actual Forever client.

The initial static review was based on main commit `1f72234`. Reconciled on 2026-10-31 against `aa0d1b3`, after PR #39 merged the one-shot context-channel probe. No real game client was used for this reconciliation.

## Reconciliation after PR #39

PR #39 added the strict context packet, text cleaning, freshness tracking, clipboard and pixel-strip readers, a probe command, and an opt-in addon. The committed tests use invented packets and an invented Lua client; no real game has produced a packet, and no companion workflow consumes one. The original recommendation to build the transport is superseded by real-client qualification. See `docs/CONTEXT_CHANNEL.md` for the exact verification matrix and proposed repository rule.

Where our project actually stands
The current implementation plan records F01 through F08, F12, F13, F16, and F17 as delivered within their stated scopes. That already includes linked journals, pinned advice, layouts, goals, recurring checklists, quest-chain research, gear comparisons, addon troubleshooting, activity history, search, build discussions, and route discussions. It is considerably more than an AI chat window beside WoW.

There are three important qualifications:

The interface and conversation infrastructure are largely present. We already have persistent Codex/Claude conversations, reviewed evidence, saved decisions, voice-to-draft input, and companion windows on the two displays. Those display windows sit over Dias; that is not the same thing as completing native Dias integration.

Several “delivered” features deliberately stop short of their full integrations. Build tutoring accepts a bounded Retail profile or manual notes; it does not establish accurate Forever simulations. Route discussion accepts images or text; it does not decode MDT strings. Quest-chain research is not a verified quest-chain database. These are useful workflows, but importing another project’s transport would not automatically complete the underlying game-data integrations.

Verification remains unfinished. The current Dias status explicitly leaves the full player-operated gear-comparison workflow, real speech accuracy, and usage-study review outstanding. Its reported test results are previous project results, not tests I ran during this review.

My assessment is that the main weakness is now getting trustworthy, current evidence into those existing workflows, rather than a shortage of workflows.
What is worth taking from the public code
LoreForever: defensive collection and compact live-state export
The most relevant files are addon/LoreForever/Context.lua and Strip.lua.

Context.lua guards API calls with pcall, accommodates missing functions, and provides a Context.Usable() check for values the client marks secret. That is worth adapting selectively. Our addon checks whether various APIs exist, but many subsequent reads are direct calls. We should distinguish “this function exists” from “this field is readable on this client, in this situation.”

Strip.lua is more specialized than a generic game-data bridge. Its current implementation constructs a 45-byte payload containing selected state such as location identifiers, level, target information, and a tracked quest. Sky.lua renders that through a star-ring pattern with error-correction bytes; older versions used a rectangular color grid. The format includes versioning, a frame counter, checksums, unknown-value markers, and explicit visibility settings. It is not a complete quest-log or inventory export.

What I would reuse: guarded reads, explicit unavailable values, versioned packets, and the separation between collecting state and presenting it for capture.

What I would not copy initially: the constellation renderer, lore-specific hashes, narration coordination, or its particular 45-byte field layout. Those solve Willo’s needs, not ours. The emitter also references companion-side Python decoder files that I did not locate publicly, so this is not a complete Python bridge we can simply drop in.
wow-ai: the clearest starting point for a small outbound codec
addon/WoWAI/Codec.lua is a compact, pure-Lua encoder with no WoW API dependencies. It packs a message identifier, payload length, payload, and Fletcher checksum into cells using three bits per cell. That makes it a practical reference for a Lua encoder paired with a Python decoder.

But I would extract only the transport ideas, not adopt its whole protocol or agent runtime.

The inspected bridge/protocol.js accepts working-directory fields and flags such as allow=... for agent permissions. Those are appropriate to that project’s purpose of talking to coding agents from inside WoW, but they should not exist in our game-context packets. Game observations must not be able to select a directory, grant tools, or become executable requests.

There is also a small implementation detail worth catching before reuse: Codec.lua declares a maximum payload size, but Encode() itself does not enforce that limit. That is not proof the surrounding application lacks checks, but our adapter should enforce limits at both its encoder and decoder boundaries rather than treating a constant as validation.

What I would reuse: the simple codec, deterministic decoding, session-aware duplicate handling, and cross-language test cases.

What I would leave behind: its Node application, coding-agent orchestration, permission flags, and inbound game-chat machinery.
NeverQuestAlone: the strongest reference for evidence quality
NeverQuestAlone builds on wow-ai, so these are not two entirely independent demonstrations of the transport. Its more useful contribution for us is how it prepares and qualifies game data before using it.

Two inspected files are especially relevant:

bridge/app/companion.mjs distinguishes a complete quest list from a partial one, tracks state sequence numbers, warns when a request refers to newer state than the bridge has, and avoids interpreting zeroed logout values as genuine losses. This is directly applicable to our quest reports and future inventory/economy comparisons.

bridge/byok/runtime/sanitize.mjs separates typed user text from game-derived strings, strips game formatting and hidden control characters, bounds fields, and checks for accidentally included credentials. Those are useful defensive patterns, although sanitization alone is not a complete defense against malicious instructions embedded in data.

What I would reuse: completeness metadata, stale-state warnings, bounded fields, privacy filtering, and explicit treatment of imported text as evidence rather than instructions.

What I would not replace: our current provider sessions, journal, or approval model with its separate application.
The architectural change I would make
1. Fix identity and freshness before adding more automatic observations
The existing WoWCompanionDB snapshot still has no character identity or opaque character token. A separate probe packet now carries a salted opaque `who.ref`, but it is not associated with saved profiles or used by feature workflows. The SavedVariables snapshot includes class, level, location, quests, equipped items, and bag-space totals. It updates in memory during play; the game writes it to disk on reload or logout. Its savedAt value is assigned when the snapshot is constructed, not by desktop-side confirmation that a fresh export just occurred.

That means a new file read is not necessarily new game evidence, and matching edition/class/level is not a reliable character association.

I would introduce a small shared context record containing:
- A private, opaque character/profile token, separate from a session token.
- Client edition/build, schema version, and state sequence.
- Observation and receipt times, with their meanings kept separate.
- Source type, completeness, and unavailable fields.
This does not require a database rewrite. It is a common contract for the existing snapshots, future pixel packets, and later combat summaries.

The distinction matters operationally: an incomplete quest list must not imply that missing quests were abandoned, and a snapshot from another character must not silently update the current character’s goals. The existing upgrade plan already calls for explicit profile association before cross-session inventory or economy comparisons.
2. Qualify the one-way context probe already merged

PR #39 implements the probe as a separate, one-shot path: an opt-in addon draws a packet, and the helper reads one clipboard, image, or fresh-window capture on request. It does not send replies, integrate with a companion feature, or run a desktop capture loop. The documented acceptance checks cover real Retail and Forever clients, display settings, copy behavior, freshness, secret values, and incomplete fields.

The parser and addon agree on invented packets, and the strip reader rejects damaged frames. That does not establish that either transport works in a real client. Run the documented client checks before deciding whether to integrate any packet fields into the existing companion workflows. A checksum verifies transmission integrity, not authenticity: another addon can still fabricate data.

The proposed rule in `docs/CONTEXT_CHANNEL.md` still needs operator approval before it is added to `AGENTS.md`. Keep the current explicit capture boundary; do not add polling, automatic requests, or game input.
3. Use that channel to improve existing features
Once the transport is proven, the most valuable applications are current quest context, selected-item facts, and inventory preparation.

There is a particularly useful opportunity in gear comparison. live_gear.py currently performs image extraction, validates the resulting facts, calculates differences in code, and then asks for an explanation. The arithmetic is already separated from the model.

For item fields the actual client exposes reliably, a structured addon export could feed an adapter into that same comparison logic and avoid the image-extraction stage. Screenshot extraction would remain the fallback for unsupported or missing details.

That could reduce latency and transcription errors without discarding F07. It still requires validation of exact item variants, effects, and equipped-slot ambiguity. An item ID alone is not enough to declare an upgrade.
4. Defer the return channel into WoW
wow-ai’s inbound mechanism uses a pool of 200 load-on-demand addons, plus sound-file readiness signals and fallback polling. Its documentation describes caching behavior, finite slot consumption, and reload-related recovery.

That is substantial infrastructure to acquire primarily for displaying answers inside the game.

Because our helper already has companion windows, pinned advice, and dedicated displays, I would not take on that dependency now. It should remain an optional later experiment, not a prerequisite for fresh context or better advice.
What remains, and how I would prioritize it
These are the seven remaining feature IDs in the implementation plan. The priorities below are my recommendation, not changes already made to the roadmap.
Remaining feature	Recommended treatment
F14: Inventory preparation	Highest-value follow-on to identity and context work. Start with verified bag item IDs/counts and explicit snapshot comparisons. Current bag-space totals are not inventory contents.
F10: Screenshot markup	A bounded, useful improvement: crop, mask, and annotate the exact image being submitted. It also improves privacy before adding more capture features.
F11: Session bookmarks	Follow F10 with a timestamped note, optional reviewed image, and frozen context. Keep it useful without recording.
F15: Post-fight coaching	Run the combat-log feasibility check first. Do not build the full analyzer system before proving the available data.
F18: Local read-only agent tools	Begin narrowly with access to explicitly published, conversation-scoped records. Avoid building a broad live-game tool service prematurely.
F09: Economy analysis	Keep behind a verified Journalator export schema and character association. Deterministic totals first; interpretation second.
F19: Recording-linked review	Keep last. It introduces storage, retention, capture lifecycle, recovery, and privacy work that the earlier features do not need.


The combat-log proposal deserves a separate proof step
Draft PR37 proposes a local pull store, built-in analyses, declarative analyzer specifications, and a reviewed “ask a question, preview an analyzer, enable it” workflow. It explicitly states that none of this is implemented and that no real Forever combat log has yet been checked.

I would preserve that direction, but limit the next work to proving which events and fields exist, how quickly they reach disk, whether pulls can be segmented reliably, and whether death summaries can be explained from the available evidence.

That work is independent of the pixel channel. Neither should block the other’s feasibility assessment.

The proposal also contains a statement that addons cannot display live results because they cannot read ordinary files or open sockets. The external projects show why that wording needs qualification: they attempt a separate load-on-demand transport. That does not establish its reliability or approval, but it means “not available through ordinary addon I/O” is more accurate than “impossible.”
The next implementation scope I would choose

First, close out the recorded real-use observations: run the full gear-comparison flow, assess actual speech accuracy, and review the expired usage study. Keep those outcomes distinct from the existing synthetic checks. The study observations and heartbeat target still need to be located.

Next, qualify the merged context probe on real clients using the checks in `docs/CONTEXT_CHANNEL.md`. Do not claim the channel as usable by the companion until client behavior, field availability, and identity handling are verified. The probe currently reports build, character class and level, location, and one selected quest; it does not export bag contents or inventory.

After those checks, choose a specific feature from the implementation plan. F09, F10, F11, F14, and F15 remain queued; F18 and F19 remain later extensions. No companion integration or new provider runtime has been selected.

Borrow code selectively with the applicable notices preserved. LoreForever explicitly separates MIT code from its lore text, restricted narration/artwork, and Blizzard-owned game text. Our repository also prohibits committing copied game assets and guide content, so the initial reuse should be code and protocol patterns, not its content library.

The success criterion is straightforward: a player-requested question can use current, correctly associated game evidence without a reload, while remaining inside the helper’s existing review and safety boundaries. That would improve the work already completed rather than starting a competing implementation beside it.
