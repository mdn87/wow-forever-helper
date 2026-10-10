# Interactive agent chat

Open a second-screen workspace connected to agent sessions you already have open. Each chat panel has its own session picker, conversation, composer, and connection. Choose a session, type a message, and press **Send message** or **Ctrl+Enter**. Enter inserts a new line. Each panel keeps separate unsent drafts for the sessions you visit while that panel is open.

## Setup

Use Python 3.11 or newer with Tk, plus an installed and signed-in agent CLI. In a local virtual environment on Windows:

```console
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[chat]"
.venv/Scripts/python -m wow_helper chat
```

On Linux, use `.venv/bin/python` and a Python installation with Tk and a graphical desktop. The non-chat helper commands remain standard-library only. Chat uses the existing CLI login; there is no separate API key or model configuration.

## Arrange multiple chats

On first launch, the workspace opens two empty chat panels. Select one agent session in the first panel and a different session in the second. A busy connection in one panel does not block the other panel.

- **New chat** adds a panel, up to eight. Each added panel starts without a selected session.
- Drag a panel's title bar to move it. Drag its **Resize** handle at the lower-right corner to change its size. Minimum sizes keep the composer and send control usable.
- **Tile chats** arranges the panels without overlap. The workspace scrolls when the panels need more room than the window provides.
- **Panels** brings a covered or scrolled-away chat into view.
- **Close** removes only that panel and its helper connection. The agent session keeps running, and other panels retain their drafts and connections. A send already in progress may still finish; closing a panel does not cancel or retry it.

These are panels inside the companion workspace. Move the whole workspace between monitors using its normal desktop title bar. Chat is the only panel type currently implemented.

Panel positions, sizes, session choices, and the workspace size save automatically under ignored `.runtime/chat/workspace.json`. Restoring a layout never sends a message. A saved session that is unavailable remains disconnected; the helper never substitutes another session. Refresh that panel after reopening the original session, or explicitly choose a different one. Drafts and transcript text are not saved in the layout and are lost when their panel closes.

## Codex

Open your Codex session normally, then select it in the window. The adapter requires a CLI with `codex queue`, `codex app-server proxy`, and the app-server item-history methods. Codex CLI 0.162.1 was checked locally.

The picker reads the local daemon's loaded threads, including desktop sessions. Background child agents are excluded. A loaded session may remain available briefly after its terminal closes; **loaded** means the daemon still holds it, not that a terminal window is visible.

**Queued** means `codex queue` confirmed receipt. It does not confirm that the agent has read or answered the message. The window reads the latest 100 conversation items every three seconds and displays human and agent text. Tool results, reasoning, and images are omitted. This is refreshed text history, not token-by-token streaming.

Opening the window or selecting a session does not start, resume, fork, or interrupt a thread. The connection uses the existing local daemon through a WebSocket over the CLI proxy. The helper opens no network listener. The implementation follows the [Codex app-server read and history methods](https://learn.chatgpt.com/docs/app-server); the installed CLI's help documents `queue` and `proxy`.

## Claude Code

The picker reads Claude's local interactive-session registry and checks whether the recorded process is still running. Claude Code 2.1.296 was checked locally. Session registry and transcript formats can change between releases. Set `CLAUDE_CONFIG_DIR` if you use a non-default Claude configuration directory.

1. Select the already-open Claude session.
2. Click **Connect Claude…**, copy the instructions, and paste them into that same session.
3. Send messages from the window. Claude polls the local inbox, reads one request, replies in its existing session, and acknowledges the request before taking another.

**Waiting for Claude to poll** means the message is saved locally. The helper cannot wake an arbitrary Claude terminal automatically. Claude must follow the connection instructions; a busy or stopped session will not read the inbox until it polls again. Ask Claude to stop polling when finished. Closing the window does not stop the CLI or cancel saved messages.

The bridge commands are `chat-poll --session <selected-session>` and `chat-ack --session <selected-session> --request-id <received-id>`. The window supplies the actual connection instructions. Polling waits up to 25 seconds by default, with a maximum of 50. It prints only delivery status; the message stays in the session's private `incoming.json` file until acknowledged. A second poll cannot overwrite an unacknowledged request. If a poll returns `awaiting_ack`, finish the current message before polling for another.

## Delivery and privacy

Refresh the session list after opening or closing a terminal. The helper checks that the selected session is still available before sending. A delivery failure keeps the draft visible. An uncertain result is never retried automatically: check the original terminal before sending again.

Every send has a durable local receipt. Reusing a receipt cannot send the same request twice, including after a helper restart. A crash during Claude's claim step can leave a request marked claimed without a usable incoming file; inspect the selected session's private inbox before manually recovering it. Pending receipts and Claude requests are not automatically deleted or replayed.

Chat text is data passed as one native CLI argument, never a shell command. The selected agent retains its own permissions and may use its existing tools in response. Approval prompts and tool activity remain in that agent's terminal. This window has no connection to assistive key delivery, and conversation is not authorization for game input.

Session names, message history, and connection instructions are private and visible locally. Provider transcripts are read in place; the helper does not copy them into the repository. Layout settings, delivery receipts, and the Claude inbox live under ignored `.runtime/chat/`. They may contain private messages, session identifiers, and machine details. Do not publish them, copied connection instructions, or real-session screenshots. No message text or provider error output is printed to helper logs.

## Verification

On Windows, synthetic tests cover discovery, session isolation, text filtering, safe command arguments, disconnected sessions, uncertain delivery, duplicate refusal after restart, Claude polling and acknowledgment, concurrent polling, draft retention, stale replies, and composer layout. The multi-panel checks also cover concurrent sends to different sessions, closing one panel while another remains usable, title-bar dragging, minimum-size resizing, tiling and scrolling, layout restoration, unavailable saved sessions, malformed settings, and layout write failures. A synthetic two-panel workspace was visually inspected at 1380 × 820 on 2026-10-10; the automated checks also exercise 420 × 460 panels inside a 900 × 640 workspace.

Read-only discovery and transcript reading were also checked against the installed Codex CLI 0.162.1 and Claude Code 2.1.296. On 2026-10-10, separate connections read nonempty histories concurrently from two different live sessions, one Codex and one Claude. No live message was sent to an agent during those checks. A live human-message/reply round trip remains unverified, and none of these checks sent game input or verified in-game behavior.
