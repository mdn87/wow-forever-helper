# Interactive agent chat

Open floating companion windows connected to agent sessions you already have open. A new installation starts with one chat window. Each chat has its own session picker, conversation, composer, and connection. Choose a session, type a message, and press **Send message** or **Ctrl+Enter**. Enter inserts a new line.

These are desktop windows that can stay above WoW. Use the game in windowed or windowed fullscreen mode. The **WoW Companion** addon still exports snapshots without displaying any UI; enabling it or using `/reload` does not open the chat. Start the companion with the command below.

## Setup

Use Python 3.11 or newer with Tk, plus an installed and signed-in agent CLI. In a local virtual environment on Windows:

```console
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[chat]"
.venv/Scripts/python -m wow_helper chat
```

On Linux, use `.venv/bin/python` and a Python installation with Tk and a graphical desktop. The non-chat helper commands remain standard-library only. Chat uses the existing CLI login; there is no separate API key or model configuration.

## Create and arrange windows

- **New window** opens an independent window at the current window's size, slightly offset. Its chooser offers **Open agent chat** and lists planned window types: quest overview, character status, screenshot advice, and character journal. Only Chat is available today. The new chat starts without a selected session or copied draft.
- Drag the normal desktop title bar to move a window; drag an edge or corner to resize it. Each window can live on a different monitor. Up to eight windows can be open.
- **Options → Keep above other windows** pins that window above ordinary desktop windows. It is enabled initially, and new windows inherit the source window's setting. The implementation uses [Tk's desktop window manager](https://www.tcl-lang.org/man/tcl8.6/TkCmd/wm.htm#M11). Exclusive fullscreen behavior has not been verified.
- **Windows** lists every open companion window and brings the chosen one back into view. **Options → Bring all windows to this screen** recovers the layout onto the current monitor.
- Closing a window removes it from the saved set. Closing the last window quits and preserves that final window for next launch. **Quit companion (keep all windows)** exits while preserving every open window.

A slow session in one window does not block another window. Closing a chat closes its helper connection; the agent keeps running. A send already in progress may still finish, and closing a window neither cancels nor retries it.

## Restore windows and conversations

Each window has a stable identity. Its type, normal position and size, selected session, pin setting, and chat retention setting save automatically to ignored `.runtime/chat/windows.json`. The helper restores them the next time you launch it. A monitor that is no longer present causes its windows to return to an available screen. A second helper process cannot overwrite an already-open manager's state. Failed saves are reported in the window; quitting keeps the windows open when saving fails, so you can retry.

**Options → Remember draft and recent chat** is enabled initially. It saves the current session's unsent draft and a bounded snapshot of recent human and agent messages: up to 100 messages within 200,000 characters. Long individual messages are shortened in the saved preview and marked. Drafts are retained up to 32,000 characters; sending still has the existing 6,000-character limit. Only the selected conversation in each window is persisted; drafts for other sessions visited in that same window last until it closes.

A restored conversation is marked **Saved history** until the provider returns fresh history. When the saved session is unavailable, the cached conversation and draft remain visible with sending disabled. Refresh after reopening the original session, or explicitly select another session. The helper never substitutes a different session, starts an agent, or sends a saved draft automatically. Interrupted sends restore an unconfirmed delivery note; check the original terminal before sending again.

Turning off **Remember draft and recent chat** removes that window's cached text from the next saved layout while retaining the session choice. The conversation already visible remains usable. Provider transcripts and existing delivery receipts have their own lifetimes.

The earlier single-workspace layout remains in `.runtime/chat/workspace.json` and is not imported automatically. This window manager starts with one chat when it has no saved windows. It remembers helper launches; it does not start automatically with WoW.

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

Session names, message history, and connection instructions are private and visible locally. Provider transcripts are read in place. When chat retention is enabled, a bounded text snapshot and draft are stored in the local window layout. Layout settings, cached text, delivery receipts, and the Claude inbox live under ignored `.runtime/chat/`. They may contain private messages, session identifiers, and machine details. Do not publish them, copied connection instructions, or real-session screenshots. No message text or provider error output is printed to helper logs.

## Verification

On 2026-10-10, synthetic Windows checks exercised one-window startup, creating a same-size window with a chooser, independent concurrent sends, window closure, quit/restart restoration, cached history with an unavailable session, draft retention, interrupted sends without replay, pin settings, minimum-size controls, window recovery, malformed layouts, duplicate identities, write failures, and exclusive layout access. Read-only monitor enumeration uses [Windows monitor work areas](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaymonitors); synthetic geometry checks cover negative coordinates and removed monitors. A chat and a new-window chooser were visually inspected at 620 × 700; minimum chat controls were checked at 440 × 540. These are checks of the desktop companion, not an in-game addon interface.

Read-only discovery and transcript reading were also checked against the installed Codex CLI 0.162.1 and Claude Code 2.1.296. On 2026-10-10, separate connections read nonempty histories concurrently from two different live sessions, one Codex and one Claude. No live message was sent to an agent during those checks. A live human-message/reply round trip remains unverified, and none of these checks sent game input or verified in-game behavior.
