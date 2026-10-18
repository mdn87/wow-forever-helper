# Typed agent sessions and normal-browser links: implementation plan

**Status:** Proposed implementation. Prepared and revised 2026-10-17 from [the research handoff](AGENT_SESSION_CAPABILITY_HANDOFF.md), incorporating an Autowork review of the earlier plan. No feature code has been changed and no live provider/browser integration has been verified in this planning pass. The review dispositions below distinguish accepted gaps from corrected assumptions.

## Outcome and selected approach

A player creates a typed companion chat, receives the appropriate startup instructions and approved capabilities, and asks, for example, “Find a guide for this quest and open it.” The agent researches the request and returns an answer plus a structured browser-opening request. The companion validates that request and sends the URL to the player's normal default browser. The player can keep that browser on a second monitor.

Use the existing CLI structured-output support for the first browser action. Both provider adapters already accept an output schema and extract structured results. This avoids introducing a tool server solely to launch one URL. Browser opening happens once the answer finishes; it is an app action requested by the model, not a provider-native browser tool. The agent cannot inspect the tab or use the launch result to continue browsing within that turn.

Actual provider tools, such as web research and preparation-file reading, remain a separate part of session setup. A local MCP tool becomes useful later if the agent needs multiple application actions and their results during a turn. The first increment needs no API-key migration, managed browser, browser extension, or computer-use integration.

The confirmed product decision is the normal browser. The defaults, protocol, permission UI, and milestones below are planning recommendations.

## Existing code and integration points

| Area | Current behavior and planned touchpoint |
| --- | --- |
| [activities.py](../wow_helper/activities.py) | Five types, opening requests, skills, preparation files, and standing instructions already exist. Extend their configuration with capability preferences. |
| [task_window.py](../wow_helper/task_window.py) | `create_session` builds startup context; `SetupDialog` edits profiles; presets import/export profile data. Preserve the actual window type even when preparation is disabled. |
| [quest_chat.py](../wow_helper/quest_chat.py) | A quest conversation prepares a `chat` packet with quest instructions. Its new session should explicitly retain the `quests` capability profile. |
| [chat.py](../wow_helper/chat.py) | `ChatService` distinguishes managed chats from attached external sessions. Pass new session policy through the managed path only. |
| [agent_sessions.py](../wow_helper/agent_sessions.py) | Stores startup text and durable requests, resumes CLIs, parses structured responses, and provides history. Add policy snapshots, reply decoding, and browser-action receipts. |
| [guidance.py](../wow_helper/guidance.py) | Quest and gear research use their own schema and background queue. These jobs must retain that protocol and have no browser-launch grant. |
| [chat_window.py](../wow_helper/chat_window.py) | Displays live/history text and polls receipts. Display answers and action status without executing actions from rendering or history reads. |
| [quest_tree.py](../wow_helper/quest_tree.py) | Already opens selected guide links through `webbrowser.open`. Use this as a launcher precedent; preserve the existing player-click path and its accepted links in this increment. |

Add small `capabilities.py` and `browser_links.py` modules for policy/response validation and browser dispatch respectively. Keep the policy registry limited to the capabilities actually implemented.

## Session policy and defaults

Keep three concepts distinct: the type's suggested capabilities, the player's locally saved approvals, and the capabilities supported by the selected provider. A prompt, imported preset, report, skill file, or webpage cannot grant an application action.

Suggested defaults for newly created windows:

| Type | Startup role | Built-in web research | Automatic browser opening |
| --- | --- | --- | --- |
| Agent chat | Follow the player's task | On | Off until enabled locally |
| Quest guide, including Quest chat | Edition-specific next steps with sources | On | Off; offer the setting prominently |
| Character status | Readiness and gear explanations | On | Off; offer the setting prominently |
| Screen adviser | Explain the selected image | Off; player can enable | Off until enabled locally |
| Journal | Summarize notes and next goals | Off; player can enable | Off until enabled locally |

Keep selected preparation readers available as required by existing file/image handling. Do not describe this as access limited to published records: that stronger isolation is future F18 work.

In Window setup, add **Capabilities** with **Built-in web research tools** and **Allow agent chats from this window to open web links**. Explain beside the research setting: **Controls the built-in research tools configured by this companion. Your CLI configuration may provide additional network tools.** This setting is not an offline mode or complete tool isolation. No additional ambient tools should be enabled by this change.

Saving the browser setting is the local approval. Its description must say: **Requested links can open when a reply finishes, even while the companion is hidden. Your browser may take focus away from the game, including in full screen. Turning this off stops unclaimed openings for chats created from this window; turning it back on applies to new chats.** Keep dispatch while hidden as the selected behavior; do not add foreground detection, monitor movement, or focus restoration. Do not ask again for each ordinary guide link covered by this approval. Imported/shared presets may carry suggestions but never enable browser permission; local approvals are excluded from portable profile exports.

Separate the immutable session manifest from mutable authorization:

- The manifest records the actual type, prompt/policy version, requested capabilities, capability ceiling at creation, origin window ID, browser approval generation, and permitted reply protocols. Creation can include only locally approved and provider-supported features. Changing type/research defaults affects future chats; widening capabilities requires a new chat.
- Private app-owned capability state stores each window's current browser approval and monotonically increasing generation, plus per-session revocation flags. Turning window approval off durably advances its generation, invalidating all older grants. Turning it on does not revive old sessions. **Stop browser openings for this chat** durably revokes that session; re-enabling requires a new chat. Missing or unreadable authorization records deny dispatch. Origin identity stays fixed when a session is viewed elsewhere; Quest chats inherit their creating Quest window's approval.
- Before claiming an action, require the manifest's browser capability, current origin-window approval, matching approval generation, no session revocation, and current provider/platform support. Also require a successful interactive managed request, its browser reply protocol, matching app-owned session/request identity, no cancellation, and no prior attempt marker. Prompt text never substitutes for any of these conditions.

Window revocation, session revocation, and action claiming use the same short-lived capability-state lock, so revocation committed before a claim wins. Use the existing `LayoutLock` primitive for a private capability-state file and bounded acquisition; failed persistence is an error, not a successful settings change. Do not hold the lock during a provider or browser call. The manifest itself never needs rewriting to revoke permission.

### Migration and session creation

Existing saved windows without capability fields preserve today's built-in web research behavior: **On for both providers**, including Screen adviser and Journal. `agent_sessions.command` currently passes Codex `--search` and Claude `WebSearch,WebFetch` unconditionally. Do not apply the new-window defaults during restoration or invent a previous research-off state. Persist the migrated setting once; browser approval starts Off. Legacy sessions without a manifest retain their current text/CLI behavior and gain no browser permission. Imported presets cannot create or restore local grants.

Repeated creation with the same creation ID and identical provider/policy returns the existing session. Conflicting reuse raises a player-visible **This creation request already belongs to a different session setup. Start a new chat.** error, leaving the existing session/manifest unchanged and creating no session or grant.

Attached external sessions keep their existing provider permissions and receive no new app dispatcher. Background research retains its distinct research purpose/schema and no browser grant. Selected preparation readers remain available; the current sandbox/tool lists do not confine every inherited plugin, hook, MCP tool, or network operation. Published-record isolation remains future F18 work.

## Provider and reply contract

Use the existing CLI logins and fixed argument arrays; prompts and URLs never become shell command strings. Startup instructions are prepended to the first user request; they do not create a privileged system prompt or grant tools. Generate the capability description separately from optional preparation, using the manifest narrowed by current authorization/support. Turning off preparation must not remove that description.

Pass the selected capability wording into `run_turn` and `ActivityService.request_message`; do not replace their shared advice-only wording unconditionally. Retain each existing advice-only sentence verbatim when browser opening is absent, including background research, legacy and ungranted typed sessions. Only an eligible browser-protocol request gets wording allowing it to request one app-dispatched URL. Both branches preserve the game restrictions. On resumed typed turns, supply a compact current capability reminder and the app-authored prior receipt wording defined below, without replaying the opening task or preparation bundle. Past receipts never authorize a new opening.

Map web research to each provider explicitly:

- Codex: retain read-only/never-ask behavior. Set the documented top-level `web_search` mode explicitly to live or disabled according to the session, avoiding a contradictory unconditional `--search` when disabled. For interactive chats, add `--output-schema` only for browser-protocol turns, new or resumed; preserve the separate background research schema. [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
- Claude: retain print/stream-JSON and the existing noninteractive permission mode. Derive one ordered built-in list: `Read,Glob,Grep` plus `WebSearch,WebFetch` only when research is enabled. Supply that same list to both `--tools` and `--allowedTools`. `--tools` controls built-in availability; `--allowedTools` permits listed tools without prompting and is not an availability restriction. The first flag does not filter MCP tools. For interactive chats, add `--json-schema` only for browser-protocol turns, new or resumed; preserve the separate background research schema. [Claude CLI reference](https://code.claude.com/docs/en/cli-reference).

### Protocol selection and live display

Record the actual reply protocol on every request. New interactive sessions without effective browser permission use `text_v1`, keeping the existing incremental readable-output behavior and omitting the chat schema. Eligible sessions may use `chat_browser_v1`; revocation or a provider-support failure narrows later requests to `text_v1`. A request already running with the schema retains that decoding contract, but its dispatch still faces the current grant recheck. Research schemas and attached external sessions never enter this selection.

For `chat_browser_v1`, deliberately show app-owned progress such as **Preparing answer and link…**, then the complete validated answer; do not promise incremental answer text for this version. Never display partial protocol JSON or attempt partial-JSON extraction. State this tradeoff in the browser setting's help. Restored history displays decoded answers and receipts. If a resumed text-only turn repeats an old envelope, it may be decoded for readable display, but cannot trigger an action.

Use this final-response shape only for `chat_browser_v1`:

```json
{
  "answer": "The guide covers the prerequisite and route. I am requesting that the companion open its page.",
  "browser_request": {
    "url": "https://example.com/guide",
    "title": "Example quest guide"
  }
}
```

`browser_request` is null when no opening is needed. Require exactly these properties and types, including exactly `url` and `title` in a non-null request. The protocol admits at most one request by construction; arrays and extra action fields are invalid. Bound `answer` by `agent_sessions.MAX_RESPONSE` (currently **200,000 characters**), URL at **4,096 characters**, and title at **160 characters**, in both schema and application validation. Validate the complete final object before any display truncation; never validate or dispatch a clipped URL. A schema result is a request, never approval. The model must not supply session/request identity or a grant. Ask for the source URL in the readable answer in either protocol so the player retains a manual link path.

Decode only the successful final structured result from the current managed turn. Never execute links found by scanning chat text, partial output, provider commentary, historical messages, tool output, or research results. A malformed response or failed provider turn produces no action and no automatic second model call. Preserve usable answer text where it can be decoded safely and report the response error separately; never substitute protocol JSON for an answer.

### Provider compatibility and fallback

Use capability detection rather than claiming an unproven minimum CLI version. The inspected versions were Codex 0.163.0 and Claude Code 2.1.270; these are evidence points, not a compatibility floor. Before enabling the browser protocol, run bounded local version/help probes (five seconds each, no model request). Require Codex `--output-schema` on both `exec` and `exec resume`, or Claude's `--json-schema` and required existing print/tool flags. Cache by executable identity, version, and adapter/protocol version for the app lifetime; invalidate on executable/version changes. Implementation must also verify the complete argument combination and supported provider/model/platform paths with synthetic live checks before claiming support. Flag presence alone is insufficient. [Codex noninteractive output](https://learn.chatgpt.com/docs/non-interactive-mode).

A missing/failed probe or unsupported combination disables automatic dispatch and labels the session **Manual links only — automatic opening unavailable** before sending; continue using its ordinary text path if the provider otherwise works. If the provider rejects a schema flag or schema at runtime, mark browser protocol support unavailable for that session/configuration, return the readable answer/URL if one exists, and show an error if none exists. Do not automatically resend the player's request. The next explicit turn uses `text_v1`; an upgrade/support change requires a new eligible chat to regain automatic opening. Authentication or general provider failure does not become a successful text reply or launch.

## Browser action behavior

`browser_links.py` accepts a validated web URL and uses the OS/default-browser route, following the existing `webbrowser` precedent. Request `new=2, autoraise=False`. These are hints: the browser/OS chooses tab reuse, monitor placement, and whether focus changes. Do not add window moving, focus restoration, or display automation. A successful launcher return means **Sent link to browser**, not that the page loaded or is visible. [Python webbrowser reference](https://docs.python.org/3/library/webbrowser.html).

Validate model-requested URLs by parsing them, not by a prefix check. Accept HTTP/HTTPS with a valid hostname/port; reject embedded credentials, whitespace/control/bidi-format characters, backslashes, non-web schemes, malformed forms/percent escapes, localhost, and literal private/loopback/link-local addresses. Reject percent-encoded hostnames. Normalize DNS hostnames to lowercase IDNA ASCII, validate the resulting labels and any punycode round trip, and use that same normalized URL for launch and receipt display. Apply the 4,096-character bound before and after normalization. Preserve meaningful path/query/fragment content; do not decode/re-encode it unnecessarily. ASCII/punycode display makes a Unicode lookalike inspectable; do not claim a complete mixed-script or phishing detector.

For the new action's receipt and manual button, primary destination text is the validated **scheme + ASCII host + nondefault port**; provide the complete normalized URL in keyboard-accessible detail/copy controls, not only a mouse hover. Treat `title` as an optional display label only: strip Unicode control/format characters, including bidi controls, render as plain text, and never let it replace the destination. Do not log URLs to public diagnostics.

These checks do not control redirects, DNS resolution, page behavior, or the browser's existing sign-ins. Opening the normal browser loads a website in the user's usual browsing context. The feature itself supplies no form submissions, browser reading, clicks, downloads, installations, or game input. Keep the existing player-clicked quest path and `guidance.normalize_result` source-link policy unchanged; a direct player click has its own authorization. Do not retrofit the new stricter model-request policy onto those links.

### Claim, launch, and recovery

Execute from the managed worker's successful completion path, never from UI polling. Bind the action to app-owned session/request IDs and keep attempt/receipt records separate from request heartbeat files. Use this order:

1. While holding the existing worker `run.json` lock, acquire the capability-state lock, then the session-state lock. Use this lock order wherever multiple locks are required. Recheck the full dispatch predicate above.
2. Exclusively create a per-request attempt marker with `O_CREAT | O_EXCL` (Python `open(..., "x")`), write `attempting` and its app-owned identity, flush and `fsync` before launching. Synchronize creation metadata where supported. Any existing marker, including an empty/torn one, blocks redispatch. Marker-write failure means no launch. Release policy/state locks before the external call; retain worker ownership until the attempt resolves.
3. Launch a dedicated short-lived helper process using a fixed Python module argument array, `shell=False`, and the validated URL through stdin. The helper calls `webbrowser.open`; it cannot write receipts or enqueue actions. Wait at most **five seconds**. On timeout, terminate/kill the helper with bounded cleanup, record `unknown`, and finish the chat turn. This cannot cancel a request already delivered to the OS/browser; a page may still appear later. No late helper result changes a recorded terminal outcome.
4. Atomically persist a separate terminal receipt using the existing `write_json` convention (flushed/synced temporary file and replacement). Record `launch_accepted` for a true launcher return, `failed` for false or a known failure before delivery, and `unknown` for timeout, ambiguous interruption, or inability to persist a confirmed result. Never clear the marker to retry. Store all records only with private session state and its existing retention policy.

At app startup and explicit managed-session load, run a reconciliation step before presenting persisted action status. Attempt to acquire the session's worker lock without blocking; if a live worker holds it, leave its attempt alone. With no worker owner, an attempt marker lacking a valid terminal receipt becomes durable `unknown`, including a torn marker or a process killed before its launcher started. Reconciliation never launches anything. If saving this receipt fails, show **Opening status unknown** from the conservative marker interpretation and retain the marker. History reads and UI rendering remain side-effect free. The guarantee is at most one automatic attempt per app request across normal process restarts, not exactly-once browser delivery or recovery from lost/restored storage.

Revocation/cancellation before the attempt is claimed prevents opening; display **Automatic opening stopped — use the link** without creating a launch attempt. Once claimed, delivery may already be underway; stopping cannot close a browser tab. Closing a companion window currently does not cancel an already-dispatched model turn, so it must not be presented as cancelling this action either. Session selection changes cannot redirect an action to a different session.

### Outcome and retry wording

| Outcome | Receipt and resumed-turn context | Player action |
| --- | --- | --- |
| `launch_accepted` | **Sent link to browser. Page loading and visibility are not verified.** | Keep a normal manual link; no failed-action retry label. |
| `failed` | **Could not send link to browser. No successful launch was reported.** | Offer **Try opening link again**. |
| `unknown` | **Opening status unknown. The page may already be open; opening it again may create a duplicate tab.** | Offer **Open anyway (may open duplicate)** alongside that warning. |

Each manual click is a fresh explicit player action with its own app-owned ID and double-click deduplication; it never reuses or deletes the original marker. It does not need a chat grant and does not send a new model request. A later player turn may explicitly request an opening again, but an ordinary follow-up, restored receipt, or prior `unknown`/`failed` result must not cause an automatic retry.

## Implementation milestones

### 1. Add typed session policy and startup assembly

**Files:** new `capabilities.py`; `activities.py`, `task_window.py`, `quest_chat.py`, `chat.py`, `agent_sessions.py`; relevant activity/session/workspace tests.

Implement the small capability registry, private mutable approval/revocation storage, immutable manifest, request purpose/protocol, and startup/resume instruction assembly. Keep type identity independent of optional preparation. Distinguish newly created windows from migration of saved windows. Keep old saved sessions readable and implement the stated creation-ID reuse behavior.

**Proof:** synthetic cases for all five types, Quest chat/origin-window inheritance, preparation disabled, preset import without grants, unchanged snapshots after settings changes, window approval cleared after creation, off/on without reviving old grants, session revocation, and unreadable approval state. Cover identical/conflicting creation-ID reuse with no mutation on conflict; existing-window migration must retain research On while browser approval stays Off. Cover legacy sessions and background research exclusion. No browser opening in this milestone.

### 2. Add provider mappings and the structured chat protocol

**Dependencies:** milestone 1.

**Files:** `agent_sessions.py`, `capabilities.py`, `guidance.py` call sites where purpose is assigned; `tests/test_agent_sessions.py`, `tests/test_guidance.py`.

Build per-provider research arguments, capability probes/cache, protocol selection, and final-answer decoding while retaining the existing research protocol. Keep attached external sessions on their existing path. Implement current-capability wording, the progress-only structured view, and manual-link fallback without automatic model resends.

**Proof:** synthetic new/resumed event streams for both providers; commentary preceding final JSON; partial/torn/failed output; overlong answer/URL/title; arrays/extra action fields; no grant; and existing guide schemas. Compare readable live text without the protocol against progress then final answer with it. Assert advice-only wording for ungranted/background requests and narrowly permissive wording for granted ones. Assert research On/Off command arrays and identical Claude tool lists; match the settings label to their built-in scope. Simulate missing flags, probe timeout, stale cache, schema-flag rejection, schema validation failure, and fallback on the next explicit turn, with no resend. During implementation, run synthetic new-and-resume live checks per claimed provider/model using a fake browser sink, including research disabled; confirm built-in research tools are unavailable without claiming all network access is blocked. Record exact versions and unsupported configurations.

### 3. Add validated, durable default-browser dispatch

**Dependencies:** milestones 1–2.

**Files:** new `browser_links.py`; `agent_sessions.py`, `capabilities.py`, managed startup/load hooks in `chat.py`; new focused browser-link tests and session regression cases. Preserve `quest_tree.py` and the guide source-link policy.

Implement normalized URL validation, helper-process timeout, the one-action limit, identity binding, synchronized grant recheck/claim, durable attempt/result receipts, and reconciliation. Keep model success and browser dispatch status independent so a browser error does not erase a useful answer. Keep marker and receipt writes separate from heartbeat updates.

**Proof:** mocked accepted/false/pre-delivery error/ambiguous error/blocking timeout outcomes; helper cleanup bounded with late completion unable to change `unknown`; no call when marker persistence fails. Kill the worker after marker persistence and before launcher return, then reconcile to `unknown` without replay; do not reconcile a live worker. Cover concurrent claims, revocation/claim ordering, window approval cleared mid-turn, torn markers, failed terminal-receipt writes, history/restart reads, and no launch after failed model output. Cover each outcome's manual action and fresh ID/deduplication, including the duplicate warning after `unknown` and no retry label after `launch_accepted`. Validate punycode/Unicode lookalike normalization, percent-encoded hosts, malformed percent escapes, credentials, rejected addresses/schemes, and length bounds. Add regression coverage for the existing player-clicked guide links (query/fragment, percent-encoded path, and normalized-source forms) without routing them through the stricter model policy.

### 4. Expose settings, receipts, and the manual fallback

**Dependencies:** milestones 1–3.

**Files:** `task_window.py`, `chat_window.py`, `chat.py`, the existing transcript-rendering helper if needed; `tests/test_chat_window.py` and relevant workspace tests; `docs/CHAT.md`.

Add capability settings and session revocation, with the research-scope, focus, and structured-output explanations above. Display effective session settings, progress/answer, normalized destination, and app-authored receipt. Add the defined explicit browser links/retry controls when automatic dispatch is unavailable or disabled. Rendering is side-effect free. Ensure imported presets cannot enable local approvals.

**Proof:** synthetic UI checks for wrong-session replies, switching sessions mid-turn, closing/reopening, stale cached history, keyboard access, minimum sizes, both themes, protocol-on/off display, revocation, and all outcome wording. Include a model title claiming a different domain and control/bidi characters: the normalized destination remains primary. Verify the full URL is accessible without hover.

**Platform scope:** Windows is the initial automatic-opening target, matching the current product. Perform a Windows synthetic desktop smoke check with the default browser already on a second monitor, companion visible and hidden, and a full-screen foreground test application. Record actual tab/focus behavior and the OS/browser/provider versions; do not automate WoW or promise exclusive-fullscreen safety. macOS/Linux automatic opening remains disabled/unverified in this increment; retain manual links without claiming their desktop behavior was tested. Document that support matrix in `docs/CHAT.md` during implementation. No real player records or screenshots enter fixtures/public artifacts.

## Completion, compatibility, and later work

Execute the milestones directly in order: their data contracts are shared, so parallel implementers would add coordination overhead. Do one consolidated diff/self-review after focused checks, then the relevant full project suite once before landing, following the repository's documented validation rules. Record OS/provider versions, passed checks, skips, and unavailable live integrations. Keep the feature unverified on any provider/platform combination without appropriate evidence; leave its manual link path usable.

Before claiming delivery, demonstrate the complete request from a newly created typed chat, repeat it in a resumed turn, revoke browser permission during a pending response, and reopen the app without replaying a browser action. Verify that background guide generation and an attached external session cannot enter the new dispatcher. Keep documentation of proposals separate from delivered/verified behavior.

Add-on discovery can later reuse web research and open a public listing. No manager has been selected, so native manager control and installation are outside this plan. A later MCP tool can reuse the browser action boundary if same-turn feedback becomes necessary. F18's published-record tool interface remains separately sequenced after normalized importers. Preserve all current game input restrictions.

## Evidence collected for this plan

Source inspection confirmed the integration points above. Local help reported Codex CLI 0.163.0 with `--output-schema` on both `exec` and `exec resume`, and Claude Code 2.1.270 with `--json-schema`, `--tools`, and `--allowedTools`. Official documentation was consulted for structured output, web-search configuration, the distinction between built-in and MCP tools, and default-browser launch semantics. These checks establish a plausible implementation path; they do not establish live provider or browser support. No implementation tests or live checks of the proposed feature were performed while writing this plan.

The 2026-10-17 Autowork review used Claude Opus and received only the previous plan, without repository source. This revision checked the relevant code: both providers already enable research, `MAX_RESPONSE` is 200,000 characters, session writes use `fsync` plus replacement, `LayoutLock` uses OS-released locks, and quest links have an existing player-click path. The Claude CLI and Python browser references were rechecked for flag roles and launch semantics. The review itself made a live reviewer request; that is not a feature integration check. The revised plan has not received a second external review.

## Review dispositions

All 18 findings are accounted for as planning changes; these are requirements for future implementation, not claims that the behavior now exists.

| Finding | Disposition |
| --- | --- |
| CR-001 | Accepted: immutable ceiling plus mutable window generations/session revocation; deny conditions and claim synchronization are explicit. |
| CR-002 | Accepted: exclusive synced marker, separate receipt, worker-lock-aware startup/load reconciliation to `unknown`. |
| CR-003 | Accepted: schema only for eligible requests; ordinary text stays readable live, structured replies show progress then the final answer. |
| CR-004 | Accepted through precise scope: label built-in research tools and disclose inherited configuration; no unsupported isolation claim. |
| CR-005 | Migration gap accepted; suggested research-off baseline corrected from source. Existing windows preserve research On and gain no browser approval. |
| CR-006 | Accepted: validated destination is primary; model title is sanitized plain label text. |
| CR-007 | Accepted: outcome-specific retry wording, explicit duplicate warning, fresh manual action identity, no automatic retry from receipts. |
| CR-008 | Accepted by preserving the existing quest-click/source policy; strict model-request rules stay separate. |
| CR-009 | Accepted: approval text covers hidden/full-screen focus risk; retain the normal-browser behavior and require a synthetic focus check. |
| CR-010 | Accepted: capability-selected wording; retain advice-only instructions when ungranted and for background research. |
| CR-011 | Detection/fallback gap accepted. Use capability probes and documented evidence instead of inventing a minimum version from two inspected versions. |
| CR-012 | Accepted: five-second helper-process bound, bounded cleanup, and `unknown` because delivery may outlive the helper. |
| CR-013 | Accepted: one request by schema construction; reject arrays/extra fields. |
| CR-014 | Accepted with scope adjustment: normalize/launch/display the same ASCII host, reject percent-encoded hosts, enforce bounds. No speculative mixed-script detector. |
| CR-015 | Accepted: initial Windows support gate; macOS/Linux automatic opening disabled and unverified pending separate desktop evidence. |
| CR-016 | Accepted: conflicting creation reuse surfaces an error and leaves all existing state unchanged. |
| CR-017 | Accepted: name `MAX_RESPONSE` and its current 200,000-character value; validate before truncation. |
| CR-018 | Accepted: one tool list supplies both Claude flags, with distinct availability/permission roles and required enabled/disabled checks. |
