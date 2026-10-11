# Interactive agent chat

Open floating companion windows connected to agent sessions you already have open. A new installation starts with one chat window. Each chat has its own session picker, conversation, composer, and connection. Choose a session, type a message, and press **Enter** or **Send ↵** beside the message box. **Shift+Enter** inserts a new line; **Ctrl+Enter** also sends. The compact toolbar holds **+ New**, the session picker, **↻** (refresh sessions), and the **⚙** menu. References to **Menu** below mean this cog button.

Choose **⚙ → Chat appearance…** to change this window's background, text and speaker-label colors, font, and size (8–36 points). The preview updates as you choose; **Save** applies the changes to the conversation and message box. **Cancel** leaves the window unchanged. **Restore defaults** previews the original colors and font; press **Save** to keep them. Each window remembers its own appearance across launches, even with chat retention disabled. Appearance changes preserve the current draft and conversation.

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

- **+ New** or **Menu → New window** opens an independent window at the current window's size, slightly offset. Its chooser offers **Open agent chat** and lists planned window types: quest overview, character status, screenshot advice, and character journal. Only Chat is available today. The new chat starts without a selected session or copied draft.
- On Windows, the matching Classic-inspired title bar replaces the standard caption. Drag it to move the window, double-click it to maximize or restore, and use its minimize, maximize, and close buttons normally. Drag a native edge or the bottom-right grip to resize. Each window can live on a different monitor. Up to eight windows can be open.
- **Menu → Keep above other windows** pins that window above ordinary desktop windows. It is enabled initially, and new windows inherit the source window's setting. The implementation uses [Tk's desktop window manager](https://www.tcl-lang.org/man/tcl8.6/TkCmd/wm.htm#M11). Exclusive fullscreen behavior has not been verified.
- **Menu → Windows** lists every open companion window and brings the chosen one back into view. **Menu → Bring all windows to this screen** recovers the layout onto the current monitor.
- Closing a window removes it from the saved set. With the Windows shortcut active, closing the last window hides it and keeps its draft, conversation, and helper process running. **Menu → Quit companion (stops shortcut)** fully exits while preserving every open window. Without an available shortcut, closing the last window exits and preserves that final window for next launch.

A slow session in one window does not block another window. Removing a chat window or quitting the companion closes its helper connection; the agent keeps running. Hiding a window keeps its connection open. A send already in progress may still finish, and closing a window neither cancels nor retries it.

The buttons use original brown leather with a muted red tint, surrounded by gold bevels. A dark leather title bar and worn brass trim frame the warm gray panels. The openly licensed Marcellus typeface gives titles and buttons a similar serif style; Windows loads it privately for the helper process. [Asset sources, license, and generation prompts](../wow_helper/assets/README.md) are included. No Blizzard images or fonts are bundled. The chooser and Claude connection dialog share the theme. The Windows frame change applies only to windows owned by the helper process and preserves native resizing, minimize, maximize, and taskbar behavior. Other platforms retain their native desktop caption in addition to the themed header; use their native maximize control.

The application background and panel backgrounds match. On Windows, dragging the title bar moves the native window without resizing its client area, avoiding the extra layout work caused by Tk recalculating the removed caption. This reduces sources of drag flicker; it is not a guarantee against all compositor or display tearing.

## Reopen while playing

Launch the desktop companion once, then press **Ctrl+Alt+H** to show its windows from WoW or another application. **Menu → Hide all windows** hides the whole set without removing windows or drafts. The shortcut shows existing windows rather than creating duplicates, sending messages, or pressing game keys. Closing the final window also hides it while the shortcut is active. The footer shows the active shortcut.

This uses a [registered Windows hotkey](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey), with repeat suppression and a message queue owned by the helper. It does not use a keyboard hook or an addon slash command. No game reload is needed. Use windowed or windowed fullscreen WoW; exclusive fullscreen behavior remains unverified.

If another application owns the shortcut, the footer reports that it is unavailable and hiding is disabled. Quit the companion normally and launch with `python -m wow_helper chat --hotkey F10` for **Ctrl+Alt+F10**. The default is **Ctrl+Alt+H** on each launch. Other platforms retain normal last-window exit behavior.

Launching `chat` again reveals an already-running companion through a local Windows event; it does not reload updated code. The existing process keeps its own windows, drafts, and layout lock. **Quit companion (stops shortcut)** releases the event and shortcut and fully exits; after that, launch the application again to restore the windows. Use **Hide all windows** when you want the shortcut to remain available. This feature does not install a Windows startup entry or keep a launcher running after a full quit.

To load updates on Windows, choose **Menu → Restart companion (load updates)** or run `python -m wow_helper chat --restart`. Restart asks the existing app to save and exit normally, then restores its windows and drafts in a fresh process. The menu preserves the active shortcut; with the command, include `--hotkey F10` if you use that alternative. No agent messages are resent. A failed save leaves the existing windows open; a restart request times out instead of forcing an exit. If the running copy predates restart support, use its **Quit companion** menu once, then launch again. No WoW reload or restart is needed.

## Restore windows and conversations

Each window has a stable identity. Its type, normal position and size, selected session, pin setting, and chat retention setting save automatically to ignored `.runtime/chat/windows.json`. The helper restores them the next time you launch it. A monitor that is no longer present causes its windows to return to an available screen. A second helper process cannot overwrite an already-open manager's state. Failed saves are reported in the window; hiding or quitting keeps the windows open when saving fails, so you can retry.

**Menu → Remember draft and recent chat** is enabled initially. It saves the current session's unsent draft and a bounded snapshot of recent human and agent messages: up to 100 messages within 200,000 characters. Long individual messages are shortened in the saved preview and marked. Drafts are retained up to 32,000 characters; sending still has the existing 6,000-character limit. Only the selected conversation in each window is persisted; drafts for other sessions visited in that same window last until it closes.

A restored conversation is marked **Saved history** until the provider returns fresh history. When the saved session is unavailable, the cached conversation and draft remain visible with sending disabled. Refresh after reopening the original session, or explicitly select another session. The helper never substitutes a different session, starts an agent, or sends a saved draft automatically. Interrupted sends restore an unconfirmed delivery note; check the original terminal before sending again.

Turning off **Remember draft and recent chat** removes that window's cached text from the next saved layout while retaining the session choice. The conversation already visible remains usable. Provider transcripts and existing delivery receipts have their own lifetimes.

The earlier single-workspace layout remains in `.runtime/chat/workspace.json` and is not imported automatically. This window manager starts with one chat when it has no saved windows. It remembers helper launches; it does not start automatically with WoW.

## Codex

Open your Codex session normally, then select it in the window. The adapter requires a CLI with `codex queue`, `codex app-server proxy`, and the app-server item-history methods. Codex CLI 0.162.1 was checked locally.

The picker reads the local daemon's loaded threads, including desktop sessions. Background child agents are excluded. A loaded session may remain available briefly after its terminal closes; **loaded** means the daemon still holds it, not that a terminal window is visible.

**Queued** means `codex queue` confirmed receipt. It does not confirm that the agent has read or answered the message. The window reads the latest 100 conversation items every three seconds and displays human and agent text. Tool results, reasoning, and images are omitted. This is refreshed text history, not token-by-token streaming.

History checks do not capture screenshots. They leave typing, **Send**, and refresh available. If a history read is already running, one explicit send or session refresh can wait behind it on the same connection. A second send is disabled until that request finishes. Unchanged history does not rewrite the saved layout. Large Codex responses use native strict UTF-8 decoding without the library's duplicate byte-by-byte Python check; [websocket-client documents that performance option](https://github.com/websocket-client/websocket-client#performance).

Conversations open at the bottom, including restored chat history and session changes. New messages, updates to a reply, and queued outgoing messages automatically scroll to the latest text. Resizing or reopening a window also keeps the end visible above the message box. You can scroll up to read earlier messages between updates; an unchanged history check leaves that position alone.

Opening the window or selecting a session does not start, resume, fork, or interrupt a thread. The connection uses the existing local daemon through a WebSocket over the CLI proxy. The helper opens no network listener. The implementation follows the [Codex app-server read and history methods](https://learn.chatgpt.com/docs/app-server); the installed CLI's help documents `queue` and `proxy`.

## Claude Code

The picker reads Claude's local interactive-session registry and checks whether the recorded process is still running. Claude Code 2.1.296 was checked locally. Session registry and transcript formats can change between releases. Set `CLAUDE_CONFIG_DIR` if you use a non-default Claude configuration directory.

1. Select the already-open Claude session.
2. Choose **Menu → Connect selected Claude session…**, copy the instructions, and paste them into that same session.
3. Send messages from the window. Claude polls the local inbox, reads one request, replies in its existing session, and acknowledges the request before taking another.

**Waiting for Claude to poll** means the message is saved locally. The helper cannot wake an arbitrary Claude terminal automatically. Claude must follow the connection instructions; a busy or stopped session will not read the inbox until it polls again. Ask Claude to stop polling when finished. Closing the window does not stop the CLI or cancel saved messages.

The bridge commands are `chat-poll --session <selected-session>` and `chat-ack --session <selected-session> --request-id <received-id>`. The window supplies the actual connection instructions. Polling waits up to 25 seconds by default, with a maximum of 50. It prints only delivery status; the message stays in the session's private `incoming.json` file until acknowledged. A second poll cannot overwrite an unacknowledged request. If a poll returns `awaiting_ack`, finish the current message before polling for another.

## Delivery and privacy

Refresh the session list after opening or closing a terminal. The helper checks that the selected session is still available before sending. A delivery failure keeps the draft visible. An uncertain result is never retried automatically: check the original terminal before sending again.

Every send has a durable local receipt. Reusing a receipt cannot send the same request twice, including after a helper restart. A crash during Claude's claim step can leave a request marked claimed without a usable incoming file; inspect the selected session's private inbox before manually recovering it. Pending receipts and Claude requests are not automatically deleted or replayed.

Chat text is data passed as one native CLI argument, never a shell command. The selected agent retains its own permissions and may use its existing tools in response. Approval prompts and tool activity remain in that agent's terminal. This window has no connection to assistive key delivery, and conversation is not authorization for game input.

Session names, message history, and connection instructions are private and visible locally. Provider transcripts are read in place. When chat retention is enabled, a bounded text snapshot and draft are stored in the local window layout. Layout settings, cached text, delivery receipts, and the Claude inbox live under ignored `.runtime/chat/`. They may contain private messages, session identifiers, and machine details. Do not publish them, copied connection instructions, or real-session screenshots. No message text or provider error output is printed to helper logs.

## Verification

On 2026-10-10, synthetic Windows checks exercised one-window startup, creating a same-size window with a chooser, independent concurrent sends, window closure, quit/restart restoration, cached history with an unavailable session, draft retention, interrupted sends without replay, pin settings, minimum-size controls, window recovery, malformed layouts, duplicate identities, write failures, and exclusive layout access. Read-only monitor enumeration uses [Windows monitor work areas](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaymonitors); synthetic geometry checks cover negative coordinates and removed monitors. Before the theme update, a chat and a new-window chooser were visually inspected at 620 × 700, and minimum chat controls were checked at 440 × 540. These are checks of the desktop companion, not an in-game addon interface.

The Classic-inspired theme was separately checked on Windows on 2026-10-10. Synthetic interactions cover dragging the custom title, resizing with the corner grip, minimum dimensions, close behavior, caption replacement with native sizing controls retained, minimize/reveal, maximize/restore, pin changes, and restoration of the normal window size. The themed chat and chooser were visually inspected at 620 × 700, and chat at the new 440 × 580 minimum. The options menu and Claude connection dialog were also visually inspected. The frame uses [Windows window-style changes](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowlongptrw) on the helper's own windows without installing a window hook.

The compact-toolbar and history-refresh update passed all 184 tests on Windows on 2026-10-10. New checks cover sending and refreshing during a slow history read, duplicate-send prevention, draft preservation, unchanged-history saves, large WebSocket messages with valid and invalid UTF-8, and toolbar fit and Claude menu access at 620 × 700 and 440 × 580. A read-only live Codex timing probe reduced history reads from roughly 0.6–0.9 seconds to 9–17 milliseconds; its maximum GUI heartbeat interval fell from 232 to 36 milliseconds. The synthetic compact chat, chooser, and menu were visually inspected. These timings describe that local probe, not a latency guarantee for every session.

The reopen-shortcut update passed all 193 tests on Windows on 2026-10-10. Synthetic checks cover hide/reveal with two independent drafts, last-window hiding, full quit and restart, shortcut conflicts, failed saves, and duplicate-launch signaling. Native Windows checks verified hotkey registration and release, plus named-event delivery from a separate process to reveal two hidden windows. The restored synthetic chat was visually inspected at 620 × 700 with its draft intact. These checks did not generate keystrokes; a physical shortcut press while WoW is foreground remains unverified.

The conversation-scroll update passed all 200 tests on Windows on 2026-10-10. New synthetic checks cover following new and growing replies after scrolling up, queued outgoing messages, unchanged refreshes, session changes, restored offline history, resize/reopen behavior, and cancellation of a scheduled scroll when closing. Assertions check the final line's actual position in the viewport because [Tk calculates wrapped-line heights asynchronously](https://www.tcl-lang.org/man/tcl8.6/TkCmd/text.htm). Synthetic chats were visually inspected at 620 × 700 and 440 × 580 after a new response arrived; both showed the latest text above the message box with the unsent draft intact.

The explicit-restart update passed all 210 tests on Windows on 2026-10-10. Checks cover separate reveal/restart requests, waiting for the saved-layout lock, older versions, timeout, save and launch failures, duplicate restart clicks, and retention of two windows with independent drafts. A native process check invoked the restart menu, confirmed that the old process exited, and observed a fresh process restoring the same two windows and drafts with Ctrl+Alt+F10 registered again. The revised menu labels were visually inspected. No live agent message or game input was sent.

The appearance and Enter-to-send update passed 222 tests on Windows on 2026-10-10. Two keypad-specific cases were skipped because Windows Tk generates keycode 0 for synthetic `KP_Enter` events; ordinary Enter, Ctrl+Enter, and Shift+Enter were exercised through Tk events. Checks cover duplicate-send prevention, failed-send draft retention, independent appearance settings across restart with chat retention off, malformed saved settings, preview/cancel/reset, and controls fitting at minimum size with 36-point text. Synthetic dark and light chat windows and the appearance dialog were visually inspected. No live agent message or game input was sent.

Read-only discovery and transcript reading were also checked against the installed Codex CLI 0.162.1 and Claude Code 2.1.296. On 2026-10-10, separate connections read nonempty histories concurrently from two different live sessions, one Codex and one Claude. No live message was sent to an agent during those checks. A live human-message/reply round trip remains unverified, and none of these checks sent game input or verified in-game behavior.
