# Hands-free voice

Run the companion by speech while both hands stay on the game. Lugos Voice listens for the wake phrase, your words, and "end turn". The companion receives each finished turn, runs it as a command when it names one, otherwise sends it to the selected chat, and Lugos Voice speaks the answer.

This page is the command reference and the test script. User-facing setup is summarized in [CHAT.md](CHAT.md#hands-free-voice-from-lugos-voice); the file protocol is in [VOICE_BRIDGE.md](VOICE_BRIDGE.md).

## Setup

1. Lugos Voice must be running a release that includes `listener/_wow_helper_bridge.py` and its `main_loop` hook (lugos-voice PRs 43 and 51).
2. In the companion window you want to drive, open **Settings → Preferences → Hands-free voice (Lugos Voice)…** and press **Connect this window**.
3. Optional: tick **Connect this window automatically when the companion starts**. The next start reconnects that window without a click. The companion opens no microphone or network port for this; Lugos Voice does the listening.
4. Choose a session in that window by voice ("switch to Raid prep", "new Codex chat") or by mouse.

Closing the panel keeps the connection. Saying "stop hands free", closing the connected window, or quitting disconnects. Lugos Voice then routes turns as it did before.

## What you can say

A whole turn must match one of these forms; anything else is a chat message. Names are matched loosely ("keep above" finds **Keep above other windows**). When two names are close, the answer is "Did you mean A or B?" and nothing runs.

| Say | Effect |
|---|---|
| "what can I say" / "help" | Speaks a short summary of these commands. |
| "open Journal", "open activity history", "Interface and transparency" | Runs a Settings menu entry or a companion command (new Agent chat, Quest guide, Character status, Screen adviser and Journal windows; Ask about the last fight; Build tutor; Dungeon route walkthrough; Addon troubleshooting; Session economy analysis; Goals and wishlist; Activity layouts; Chat appearance; Window setup). A bare entry name works when it matches exactly. |
| "turn on keep above other windows", "turn off remember draft" | Sets a menu check box. Says "already on" when nothing needs to change. |
| "press read combat log", "click prepare review" | Presses a button in the frontmost companion dialog. In a plain chat window, "press Send" and "press Claude +" work too. |
| "check include player names", "uncheck …" | Sets a check box in the dialog. |
| "choose Retail", "select Classic Forever beta" | Picks a radio button or drop-down value in the dialog. Outside a dialog, picks a chat session by title. |
| "show the digest tab" | Selects a tab in the dialog or window. |
| "type why did we wipe so fast" | Adds text to the focused dialog field, or to the dialog's first named field, or to the chat draft when no dialog is open. |
| "set question to …" | Replaces a named dialog field (for example question or digest). |
| "read it" | Reads the dialog's notice and named fields (for example Question and Digest), or the chat draft. |
| "read the reply" | Reads the selected chat's latest agent reply (up to about 1,200 characters). |
| "send" / "send it" | In a dialog, presses its Send button; Send stays unavailable until the review is prepared, and a review sends once. With no dialog, sends the chat draft. |
| "clear the draft" | Empties the chat draft. |
| "close" / "cancel" / "never mind" | Closes the frontmost companion dialog through its own Close button. |
| "switch to Raid prep", "new Codex chat", "new Claude chat" | Changes the connected window's chat session or starts one. The next message names the chat when it changed. |
| "compare" / "compare gear" | Starts one capture in an open Live gear comparison whose region was reviewed and whose shortcut is enabled. Hover the item first. |
| "cast teleport to Orgrimmar on my mage" | The existing assistive teleport command, with its usual checks: enabled state, bound key, fresh request, one use per request ID, and WoW in front. |
| "open the browser" / "close the browser" | Opens or closes the voice browser, a separate Chrome window the companion owns. It opens in the background, so the game keeps the foreground. Drag it to a side monitor once; Chrome remembers the spot. |
| "look up frostbolt", "look up Thunder Bluff on classic", "search the web for …" | Searches Wowhead, Wowhead Classic or Bing in the voice browser and says the page title. |
| "browse to wowhead dot com" | Opens a spoken address. Anything that is not an address is looked up on Wowhead. |
| "open the first result", "open result 3", "follow the link Rank 2 trainer" | Opens a result from the search page, or the page link whose text matches. |
| "read the page", then "read more" | Reads the page title and about 900 characters of its main text, then the next part. |
| "scroll down" / "scroll up" / "scroll to the top", "go back" / "forward", "what's on the browser" | Moves the voice browser's page, or says what it shows. |
| "tell the agent …" / "ask Codex …" | Sends the rest as a chat message even if it sounds like a command. |
| "stop hands free" | Disconnects. |
| anything else | Sent to the connected window's selected chat without draft review. |

## Safety rules

- Commands operate only the companion's own windows and its voice browser. Chat messages never trigger game input.
- The voice browser uses its own Chrome profile in the ignored `.runtime/voice-browser` folder and a DevTools port open only to this PC (127.0.0.1:9231). It never types into pages, signs in, downloads, or activates a window. Every browser answer checks the foreground window; if it changed, the answer says so and the companion leaves focus alone. Don't sign in to anything in that window: any program on this PC can reach that port. The teleport command is the only game input, and it keeps every existing assistive-input check.
- Turns older than a minute, repeated request IDs, malformed turns, and turns for an earlier connection are refused and answered.
- Nothing runs because of a reply, a screenshot, or chat content. There are no retries, command sequences, or repeated keys.
- Review flows still need an explicit spoken send after the review is prepared and visible.
- Push-to-talk (Keypad -) is unchanged and still fills a draft only.

## Known limits

- The voice browser can't fill forms, press page buttons other than links, or pick from menus on a page. Some sites refuse automated browsers; Wowhead and Bing answered in testing.
- File pickers (**Import…**, **Open image…**, **Open saved journal…**) are Windows dialogs and still need the mouse.
- Speech recognition can mishear names; the panel's Recent turns list shows what was heard and what happened.
- One window is connected at a time. Commands act on that window and on the frontmost companion dialog.
- Lugos Voice's own controls and aliases (for example "master status") still run first and never reach the companion.

## Test script

Each step lists what to say after the wake phrase, followed by "end turn", and the expected spoken answer. Record pass or fail in the live test runbook.

1. Connect a window with a chat session selected. Say "what can I say". Expect the summary.
2. "turn off keep above other windows". Expect "Keep above other windows off." and the window drops behind WoW. Then "turn on keep above". Expect "… on.".
3. "Where is the nearest flight master?" Expect "Sent." and the message in the chat. After the reply arrives, "read the reply". Expect the reply read aloud.
4. "new Codex chat", then "switch to" plus the first session's title. Expect "Now talking to …".
5. "ask about the last fight". Expect the dialog. "type why did we wipe so fast", "press read combat log", "press prepare review", "read it", then "send". Expect one request in the chat. A second "send" is refused.
6. "close". Expect the dialog to close.
7. Open Live gear comparison, review a region and enable it by mouse. Hover an item in game and say "compare". Expect "Comparing…" and one result.
8. With assistive input enabled and the key bound, say "cast teleport to Orgrimmar on my mage" with WoW in front. Expect the key-sent message. Spell success is not verified.
9. Say something that sounds like a command but is not one, such as "open the door". Expect "Sent." (it is a chat message).
10. Voice browser, with WoW in front: "open the browser", "look up frostbolt", "open the first result", "read the page", "read more", "scroll down", "go back". Expect each answer spoken, the Chrome window to change, and WoW to keep the keyboard the whole time (keep moving your character between turns).
11. "stop hands free". Expect the disconnect message, and later turns go back to Claude.
12. Turn on auto-connect, quit, and start the companion. Expect the window connected without a click.

## Verification

Synthetic tests in `tests/test_handsfree.py` and `tests/test_voice_bridge.py` drive turns through the real file bridge against an isolated test desktop. They cover menu toggles and companion commands, dialog buttons, check boxes, close and read, typing and sending the draft, reading the reply, session switching with the chat named on the next message, chat fallback and the chat prefix, the full Ask about the last fight review by voice with one send, gear comparison gating, every voice browser phrase, its DevTools calls against a fake page (no input emulation or window activation), the foreground-change report, teleport with the turn's ID and time and its refusal, refusals for an empty draft and no session, disconnect by phrase and window close, saved auto-connect, and the panel. The Lugos Voice tests cover the spoken answers and a file round trip with the companion's bridge. On 2026-11-04 the voice browser was also run on this PC against real Chrome and live Wowhead and Bing pages, without the listener: opening the window and nine commands (search, first result, read, scroll, link, back, status) left the foreground window unchanged throughout. The first design, where Chrome opened its own window, took the foreground, which is why Chrome now starts without one. A live spoken turn through the installed listener, real recognition accuracy, and in-game results are not yet verified.
