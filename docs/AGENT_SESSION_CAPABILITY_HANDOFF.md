# Planning handoff: typed agent capabilities and browser links

**Status:** Research and planning handoff, updated 2026-10-17 after the Autowork review. The [implementation plan](AGENT_SESSION_CAPABILITY_PLAN.md) contains the current decisions, four milestones, acceptance checks, and dispositions of all 18 review findings. This document and the plan propose future behavior; no feature code has changed or been verified by implementation.

## Goal

Give a newly created agent session startup instructions and a small, type-appropriate set of approved capabilities for the player's request. Use the existing window/session types as the basis for defaults, since the earlier type-based capability work was not completed. Follow the linked plan for the selected first increment.

## Confirmed product choice

For the initial browser-related scope, opening a link should use the player's normal operating-system default browser. The player may place that browser on a second monitor and watch the page. The companion should not launch a managed/isolated browser for this first step.

Opening a URL in the default browser is distinct from letting the agent inspect, navigate, click, type, or otherwise control that browser. Do not imply that a visible tab is agent-controlled. Live browser control and desktop computer use need separate planning and explicit capability decisions.

## Current implementation evidence

- `wow_helper/activities.py` defines the current types: `chat`, `quests`, `character`, `screen`, and `journal`. It also defines type-specific opening requests, skills, and profile settings. Profiles already carry optional user instructions, but not an explicit tool-capability manifest.
- `wow_helper/task_window.py` prepares the startup context and opening request when it creates a new session. The prepared startup is attached to the first request; subsequent turns resume the provider conversation.
- `wow_helper/agent_sessions.py` launches providers through fixed CLI arguments. Codex currently runs with web search and a read-only sandbox. Claude's tool and allowed-tool lists are explicitly limited to `Read,Glob,Grep,WebSearch,WebFetch`. Neither CLI invocation currently exposes a companion tool that opens the player's default browser.
- `wow_helper/quest_tree.py` already calls Python's `webbrowser.open()` for a selected quest link. This is a local precedent for opening a URL in the default browser, but it does not let an agent operate the browser or guarantee which monitor/browser window will receive the page.
- `docs/UPGRADE_IMPLEMENTATION_PLAN.md` F18 proposes optional local, read-only agent tools for selected normalized records. It specifically calls for per-session publication and provider capability checks. It does not cover browser launching, browser control, or add-on installation.

## Research findings

1. A prompt can guide an agent to use an available tool, but it cannot add a tool that the application/provider has not exposed. Tool discovery/registration and execution permissions must be implemented by the host integration.
2. Tool integration is provider-specific. OpenAI documentation describes function tools and MCP as ways to expose application capabilities. The existing app, however, invokes provider CLIs directly and constrains their command-line tools; planning must confirm how a local, app-owned tool is passed to each supported provider and how unsupported provider configurations are reported.
3. The OpenAI-hosted computer-use browser is remote. It can send screenshots/activity to an app, but it is not a local browser window the player can move onto a second monitor. A local visible browser driver is a different architecture and is outside the confirmed initial choice.
4. OpenAI's computer-use guidance says tool permissions and confirmations should be enforced by application/runtime code, not prompt text alone; page content is untrusted and cannot authorize actions. It recommends keeping consequential actions behind explicit, action-time approval.
5. Installing or running a newly downloaded add-on is a separate, consequential action. A future add-on-manager workflow should stop before installation and require the player to approve the exact add-on and source. Finding a listing or opening its page must not count as approval to install it.

## Selected first increment

The implementation plan resolves the initial planning questions as follows:

1. **Use CLI structured replies for the app action.** An eligible managed interactive turn returns readable `answer` text and one nullable `browser_request`. The companion validates and dispatches after completion. This needs no new MCP server and gives the model no browser-control feedback loop. Manual source links remain available.
2. **Keep browser permission Off by default for every type.** Local window approval can grant it to new chats; presets cannot. Preserve actual type identity even when preparation is disabled, including the `quests` identity of Quest chats.
3. **Separate the session snapshot from revocation.** Store an immutable capability ceiling and mutable local authorization. Clearing window approval invalidates existing grants through an approval generation; turning it back on applies only to new chats. Per-chat stop also revokes before an attempt is claimed. Missing authorization denies dispatch. Viewing the session in another window does not change its grant origin.
4. **Preserve existing research behavior on migration.** Both current provider commands already enable web research. Existing windows retain that behavior; newly created windows use the plan's type defaults. Label the setting **Built-in web research tools** and disclose that the user's CLI configuration may provide additional network tools. It is not an offline/security-isolation switch.
5. **Limit structured-output overhead to eligible requests.** Ordinary chats retain readable live output. Browser-protocol turns show app-owned progress, then the final decoded answer. Revocation or unsupported schema handling narrows subsequent turns to text. Advice-only wording remains for ungranted and background requests; only eligible requests receive wording allowing the app action.
6. **Detect provider support and fall back explicitly.** Use bounded version/help probes, exact argument checks, and implementation-time synthetic live verification. The previously inspected versions are evidence, not invented minimum versions. Missing support means manual links only; runtime schema failure never triggers an automatic resend. One shared Claude built-in list supplies its availability and permission arguments.
7. **Make launch attempts durable and recoverable.** Recheck grants under a shared policy lock; exclusively create and sync the attempt marker before launching. Use a five-second helper-process bound and separate receipts. Startup/session-load reconciliation marks ownerless incomplete attempts `unknown`; it never replays them. A timeout cannot undo delivery already handed to the OS.
8. **Display the destination accurately.** Parse and normalize model-requested HTTP/HTTPS URLs, use the same ASCII hostname for launch and display, enforce the bounds, and reject credentials and invalid forms. The receipt's primary label is the validated destination; a model title is sanitized secondary text. Preserve the existing player-clicked quest-link path rather than applying the new stricter policy to it.
9. **Make outcome and retry wording explicit.** A successful call means **Sent link to browser**, not verified page loading/visibility. A failed attempt offers a manual retry; an unknown outcome warns that a page may already be open and another opening may duplicate it. Each manual click is a new player action; no receipt or ordinary follow-up authorizes automatic retry.
10. **Keep the selected normal-browser behavior while hidden.** Approval text explains that the browser may take focus away from the game, including full screen. The app does not move windows or restore focus. Windows is the initial automatic-opening target; macOS/Linux automatic opening remains disabled/unverified until separately checked. Keep manual links available.

Browser reading/navigation, clicks/typing, native computer use, and add-on installation remain separate future capabilities. Add-on discovery may later open a public listing; no manager has been selected. Installation still requires approval of the exact add-on/source. F18's published-record tools remain separately sequenced. Preserve all current game-input restrictions.

## Next-agent handoff and acceptance

Read [AGENT_SESSION_CAPABILITY_PLAN.md](AGENT_SESSION_CAPABILITY_PLAN.md) as the authoritative implementation proposal. Its milestones cover session policy, provider/protocol integration, durable launch dispatch, then settings/receipts. The review-disposition table accounts for every finding and records the research-migration correction. Do not treat review completion as evidence that the feature works.

During implementation, demonstrate:

- A guide request in a new and resumed eligible chat reaches the normal browser once per automatic attempt, with a usable manual URL.
- Window/per-chat revocation before claim prevents opening, and restoring the app cannot replay an attempt. Interrupted attempts become `unknown` without disturbing a live worker.
- Ungranted chats retain readable live text, structured chats hide protocol JSON, and background research/attached external sessions cannot enter the dispatcher.
- Research settings match their enforced built-in scope; unsupported providers retain explicit manual-link fallback without automatic model resends.
- Existing saved windows retain current research behavior, existing quest links still work, and portable presets grant no browser permission.
- Outcome-specific controls, canonical destination display, keyboard access, and hidden/full-screen focus wording match the plan. Record Windows browser/provider smoke-check evidence; mark other combinations unverified.

No browser action in this increment inspects page content, clicks controls, fills forms, installs an add-on, executes arbitrary scripts, or sends game input. The normal browser still loads websites in the player's usual browsing context.

## References checked 2026-10-17

- [OpenAI: Computer use integration recipes](https://developers.openai.com/api/docs/guides/tools/computer-use-integration) — application-enforced permissions, consent, untrusted page content, and confirmation at consequential actions.
- [OpenAI: Browser and desktop drivers](https://developers.openai.com/api/docs/guides/tools/computer-use-sdk-drivers) — custom browser drivers, selected methods, URL policies, and approval callbacks.
- [OpenAI: Agents API computer use](https://developers.openai.com/api/docs/guides/agents-api/tools/computer-use) — hosted browser sessions, origin approval, and optional screenshot/activity display.
- [OpenAI: MCP connections for Agents API](https://developers.openai.com/api/docs/guides/agents-api/tools/mcp) — server-published tools, per-session allowed tools, and environment-local MCP connections.
- [Playwright: Chrome extensions and headed browser](https://playwright.dev/docs/chrome-extensions) — an example of launching a visible persistent browser context; this is background research only, not the selected initial design.

