# Explicit user-command input

The first supported action is `teleport-orgrimmar`. An explicit phrase such as
“cast teleport to Orgrimmar on my mage” resolves to that action and a locally
configured key chord. This is a command interface, not an autonomous gameplay loop.

## Setup

1. In the intended WoW client, put **Teleport: Orgrimmar** on an action-bar slot and
   assign that slot a keybind. Check that it is the teleport spell, not a portal.
2. Record the same binding locally. For example, if the actual slot uses Shift+7:

   ```console
   python -m wow_helper bind teleport-orgrimmar --key SHIFT+7
   ```

3. Preview a command and check the displayed key:

   ```console
   python -m wow_helper request "cast teleport to Orgrimmar on my mage"
   ```

4. Enable dispatch once you want to use it:

   ```console
   python -m wow_helper enable
   ```

Input starts disabled on a new installation. Enabled state persists locally.
`python -m wow_helper stop` disables subsequent dispatch, including across restarts.
There are no scheduled actions, held-key loops, or repeat timers. STOP cannot undo
an input packet already dispatched or cancel a spell already casting in the game.

Supported keys are A-Z, 0-9, F1-F12, optionally combined with CTRL, ALT, and SHIFT.
Both `SHIFT+7` and `SHIFT+F4` are supported. Windows keys and ALT+F4 are excluded.
No default spell key is assumed. Setup does not modify any game file.

## Voice or conversation integration

The CLI accepts the transcription from an existing voice-to-assistant system. It
does not record audio or call an AI API. The operator's own voice listener (a separate,
private project) calls it for any spoken command that mentions teleporting, before the
command can reach an assistant window. If this parser does not recognize the words, the
listener sends them on as an ordinary request. This is the invocation contract:

```text
python -m wow_helper request <original-command-text> --execute --request-id <event-id> --issued-at <unix-seconds>
```

Pass arguments as a subprocess argument list, never interpolate transcribed speech
into a shell command. Use the event's original timestamp and stable ID. Repeated
delivery of one utterance must keep the same ID; a new deliberate utterance gets
a new ID. IDs are 1-80 letters, digits, underscores, or hyphens. Commands expire
after 15 seconds. Do not refresh their timestamp to bypass expiry.

For a local trusted adapter, the equivalent Python call is:

```python
from pathlib import Path
import wow_helper
from wow_helper.assist import Assistant
from wow_helper.windows_input import WindowsInput

store = Path(wow_helper.__file__).resolve().parents[1] / ".runtime" / "assist.sqlite"
helper = Assistant(store, WindowsInput())
# event is supplied by the user's voice system; never construct it from game chat.
result = helper.request(event.text, execute=True,
                        request_id=event.id, issued_at=event.issued_at)
```

Only direct player instructions may invoke execution. Explanations, suggested
actions, quoted examples, screenshots, addon data, and in-game chat are not
execution requests. Questions, negation, unknown spells, and compound requests
are rejected by the narrow parser, which tolerates only commas and a few transcript
spellings of Orgrimmar ("Orgrimar", "Org Grimmar", "Orgrimmer"); no language model chooses a spell for it.

Keep WoW foreground when the voice adapter dispatches. If the voice system raises
its chat window over the game, delivery is refused. The operator's listener checks
game commands before it moves any window, so WoW stays in front. The helper does not steal focus or send background window messages.
The supported process basenames are `wow.exe`, `wowb.exe`, and `wowclassic.exe`.
Executable names identify the foreground app; they are not cryptographic identity
checks. No game edition or release-date assumption is needed for the key mapping.

## Outcomes and failure handling

- `preview`: the request resolved, but no input was attempted.
- `sent`: Windows accepted one down/up packet for the chord. Spell success is unverified.
- `refused`: an explicit check failed. Read the message; input may already have been
  partially accepted if it reports an incomplete delivery.
- `error`: local storage or the OS boundary failed. The CLI never retries automatically.

Exit codes are 0 for preview/success, 2 for a refusal, and 3 for an OS/storage error.
A request ID is durably reserved before reaching the native input boundary. Even a
process crash or uncertain delivery leaves that ID consumed. If delivery fails,
inspect the game and issue a new deliberate command; do not manufacture a new ID
for an automatic retry. Separate invocations in the same checkout share the store.
Copies of the repository have separate stores and must not dispatch the same voice
events. Deleting local state also deletes replay protection.

The Windows boundary checks the foreground process twice and rejects held mapped
keys or modifiers. It sends all key-downs followed by reverse-order key-ups in one
Windows input packet. On a partial insertion, it attempts only the remaining
key-ups and reports an unknown spell outcome. It never repeats a key-down.

Windows input goes to the foreground application. Focus can still change after
the final check; that check and dispatch are not atomic. The helper cannot tell
whether a chat box, menu, wrong character, or changed action bar is active. It cannot
verify spell availability, cooldown, combat restrictions, or a successful teleport.
Use the intended character and close chat/menus before issuing a request. Windows
may block delivery across privilege levels; run the game and helper normally rather
than adding elevation or bypasses.

## Implementation and evidence

- `assist.py`: exact command grammar, chord validation, SQLite controls and bindings,
  timestamp checks, and atomic persistent request reservation.
- `windows_input.py`: query-only foreground process identification and the sole
  permitted native keyboard boundary. No game-memory reads, hooks, or injection.
- `__main__.py`: preview-first local CLI and path-free JSON result messages.
- Tests cover parsing, both example keybinds, duplicate/concurrent delivery,
  persistence, expiry, STOP, focus changes, held keys, partial insertion and release.
  Native ABI/API initialization checks run on Windows; OS calls are mocked for input tests.

Runtime state lives in ignored `.runtime/assist.sqlite`. It contains bindings,
enabled state, request IDs, action IDs, and delivery outcomes; it contains no raw
speech transcripts, game screenshots, or character/account names. The screenshot
panel, addon, and in-game acceptance test remain separate work.

Windows behavior follows Microsoft's [keyboard input API documentation](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
and [INPUT structure layout](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-input).
