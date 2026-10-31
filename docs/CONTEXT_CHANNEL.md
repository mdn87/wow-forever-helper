# Context channel

Status: groundwork, not yet run on a game client. The parsers, the readers, a probe command and a probe addon exist and are tested on invented data. Nothing in the companion, the chat windows or any feature calls them yet, and no packet has come out of a real game.

The goal is to let the helper learn a few facts about what the game is showing (build, character class and level, zone, the selected quest and its objectives) without reading game memory. A small addon would hand those facts over in one packet through either of two transports, and the helper would read them back with one strict parser. Which transport works, if either, depends on what the real client does with the addon's output. That is what the probe measures. Section "Verification status" lists what is and is not known.

## What exists now

| Piece | Where | Does |
|---|---|---|
| Packet parser and writer | `wow_helper/context/envelope.py` | Accepts exactly the documented shape; names a reason code and field on refusal, never the value. |
| Text cleaning | `wow_helper/context/sanitize.py` | Port of the NeverQuestAlone rules (see "Licensing"). |
| Freshness | `wow_helper/context/tracker.py` | Says whether a packet is new, a repeat, out of order, too old or from the future. |
| Clipboard transport | `wow_helper/context/clipboard.py` | Reads the clipboard once on request. |
| Pixel strip transport | `wow_helper/context/strip.py` | Finds and reads a strip in a captured frame. |
| Probe command | `python -m wow_helper context-probe` | Reads one packet from the clipboard, the game window or an image and reports what arrived. |
| Probe addon | `wow_addon/WoWCompanionProbe/` | Draws a strip or shows a text box, only when the player types a command. |

## The packet

One JSON object, version 1, at most 8192 bytes. Every key is required, unknown keys are refused, numbers are integers with ranges, and identifiers have fixed formats. Keys are written in this order, with no spaces, and `|` and control characters are written as `\uXXXX`, so the addon and the helper produce identical bytes for the same packet.

| Key | Meaning |
|---|---|
| `v`, `kind` | `1` and `"context"`. |
| `sid`, `seq`, `at` | Session id (16 hex), sequence number rising within the session, server time in seconds. |
| `build` | `version`, `build` and `interface` as the client reports them. |
| `who` | `ref` (16 hex, a salted hash of the character id, never the id itself), `level`, `class` (upper-case token). |
| `where` | `zone`, `sub` and `map` id. |
| `quest` | `id`, `pick` (`tracked`, `watched` or `first`), `title`, `complete` and up to 8 `objectives` of `text`, `have`, `need`, `done`; or `null`. |
| `scope` | `{"quests": "one"}`. |
| `missing` | Names of fields that exist but could not be read. |

`null` and `missing` mean different things. `null` says the thing does not exist: no selected quest, no subzone. A name in `missing` says it exists but the addon could not read it, because the client marked it secret or the interface is absent. A consumer must never treat an unreadable value as an empty one. The parser enforces the pairing: a field named in `missing` must be `null`.

Refusal codes: `too-large`, `not-utf8`, `bad-json`, `too-deep`, `not-object`, `duplicate-key`, `bad-number`, `unsupported-version`, `wrong-kind`, `unknown-key`, `missing-field`, `bad-type`, `out-of-range`, `bad-format`, `too-many`, and `no-packet` for text that carries no packet at all.

## Cleaning game text

Quest titles, zone names and objective text can carry text that other addons, macros or players put there, and a packet may later be shown to a person or passed to a model. Every string goes through the same steps, in this order: strip game escapes (colours, textures, atlases; a link keeps its bracketed text), remove format and default-ignorable characters and unpaired surrogates, turn controls and line separators into spaces, drop any remaining `|`, collapse whitespace, and cap at 60 code points (80 for objective text).

The addon does a first pass and the helper repeats the whole procedure on receipt, listing the fields it had to change in `cleaned`. The addon's pass is deliberately partial: it names byte ranges rather than using pattern classes such as `%c` and `%s`, because those follow the C library's locale and can cut a valid UTF-8 character in two. Removing the invisible Unicode characters is left to the helper, which holds the pinned table (Unicode 17.0).

One upstream quirk is kept so both implementations agree: escapes are stripped before invisible characters, so a zero-width character inside an escape stops the escape from matching and the letters stay. Nothing is left that reads as a control sequence.

## Freshness

Both transports can show the same packet more than once. The tracker keeps the last 8 sessions and judges in this order: `stale` when older than 120 seconds, `future` when dated more than 120 seconds ahead of this computer, `duplicate` when the session already showed that sequence number, `older` when it showed a higher one, otherwise `fresh`. A session not seen before is fresh whatever its sequence number. The probe saves tracker state in `.runtime/context-probe.json` (ignored by git); `--no-state` treats every run as the first.

## Transports

Clipboard. The addon shows the packet in an edit box, highlighted; the player presses Ctrl+C. The text is `WFHC1:` followed by the packet. The helper reads the clipboard once per request and never writes to it or watches it. A clipboard that holds something else is the ordinary case and is reported as `no-packet`.

Pixel strip. The addon draws a grid of white and black cells at the top left of the screen on an opaque black backdrop. The first row is a ruler of alternating cells and the last column alternates down the strip, so the reader can find the strip, measure every column and row boundary, and take the white and black levels from the ruler, without knowing the cell size or the colours the client produced. Frame bytes are `A7 3C`, version, flags, a 2-byte length, the packet, then a CRC-16/CCITT-FALSE over version through packet. There is no error correction: a damaged cell fails the checksum and the frame is refused with `crc-mismatch`; wrong data is never returned. Cells narrower than about 2 pixels are not reliable. The full layout is in the `wow_helper/context/strip.py` docstring.

## The probe addon and command

Install it separately from the companion: `python -m wow_helper install-addon --probe` (add `--flavor _retail_` to limit it to one game folder). Enable "WoW Companion Probe" at character select, then `/reload` once.

| Command | Does |
|---|---|
| `/wfhprobe strip [cell 2-8] [columns 32-512, even] [live]` | Draws the strip at the top left for 15 seconds. `live` redraws every 2 seconds for 30 seconds with the next sequence number. |
| `/wfhprobe copy` | Shows the packet in an edit box to copy with Ctrl+C. Typing in the box is undone. |
| `/wfhprobe copy api` | The same, with a button that calls the game's own `CopyToClipboard` and shows whether it ran, was refused or is absent. |
| `/wfhprobe status` | Reports the version, build, which features this client has and the screen size. |
| `/wfhprobe off` | Hides everything and stops a live redraw. |

The addon reads game state only. It registers no events, runs nothing every frame, and does not cast, target, move, chat, accept or change a setting. It reads these interfaces: `GetBuildInfo`, `GetServerTime`, `GetPhysicalScreenSize`, `UnitLevel`, `UnitClass`, `UnitGUID`, `GetRealZoneText`, `GetSubZoneText`, `C_Map`, `C_SuperTrack`, `C_QuestLog`, `issecretvalue`, `CopyToClipboard` (only on a button click) and the frame functions it needs to draw. It never touches a value the client marks secret, except to ask `issecretvalue`. Its only saved data is a random salt in `WoWCompanionProbeDB`, used to hide the character id. A test pins this list so adding an interface fails until the list is reviewed.

Reading back: `python -m wow_helper context-probe --source clipboard|window|image [--flavor _retail_] [--image FILE] [--corner topleft] [--max-age 120] [--show] [--no-state] [--text]`. Exit code 0 means a packet was read and judged (the verdict says whether it was new), 2 means nothing could be read from what was there, 3 means the source itself could not be used. The default report names fields, counts and measurements and never prints game text, so it is safe to paste; `--show` adds the cleaned content. `--source window` takes one fresh capture of the game window, reads it and drops it; it is never saved or logged.

## Running the probe on the Retail client

The installed Retail client can answer the engine-level questions (how the strip survives each display setting, whether the edit-box copy works, whether `CopyToClipboard` is allowed). It cannot answer anything specific to Forever. These steps need a person at the keyboard.

1. `python -m wow_helper install-addon --probe --flavor _retail_`, enable the addon, `/reload`, then `/wfhprobe status`. Record the lines it prints.
2. `/wfhprobe strip`, and while it is visible run `python -m wow_helper context-probe --source window --flavor _retail_ --text`. Record the verdict or reason code, and the strip line (columns, cell size in pixels, contrast, weakest margin).
3. Repeat step 2 with `/wfhprobe strip 3` and `/wfhprobe strip 2` to find the smallest cell that still reads.
4. Repeat steps 2 and 3 for each setting that could change the picture: windowed, fullscreen windowed and fullscreen; a low and a high UI scale; the colour-blind filter on; HDR on, if the display supports it; a lower render scale. One row per setting.
5. `/wfhprobe copy`, press Ctrl+C in the box, Esc, then `python -m wow_helper context-probe --source clipboard --text`. Record whether the copy worked.
6. `/wfhprobe copy api`, click the button, and run the clipboard probe again. Record the line the box shows (ran, refused or absent) and whether the clipboard changed.
7. Run the clipboard probe twice without copying again: the second verdict should be `duplicate`. After two minutes without copying it should be `stale`.
8. `/wfhprobe strip 4 160 live`, then run the window probe several times: `fresh` with a rising sequence while it redraws, `duplicate` when it has not changed.

What the results decide: a strip that reads at 4 pixels with a healthy margin in every setting means error correction is not needed. A failure only under one setting (the colour filter, HDR) names the setting to document or encode around. A refused `CopyToClipboard` means relying on the edit box. A failed edit-box copy leaves the strip as the only route.

## Launch-day checks on Forever (planned for 2026-11-04)

These cannot be done before the client is available to run.

1. Repeat the Retail steps above against the Forever game folder, including the display table.
2. Log out and back in, then `python -m wow_helper character --text`: gold and rested XP must be the real values, not zero (the logout guard in addon 0.4.1 is tested on invented data only).
3. `python -m wow_helper check-snapshot --text` to see which bag and tooltip fields the client provides.
4. Run `/wfhprobe copy` in a few places (open world, an instance, in combat) and read the `missing` list in the probe report, to see where secret values appear in practice.
5. `/wfhprobe copy api`: whether addons may call `CopyToClipboard` at all on this client.
6. Whether the flavor folder name is the one the helper expects.

## Verification status

"Invented data" means values made up for the tests; no game client, character or captured screen was involved. Local runs used CPython 3.14.3 on Windows 11; CI runs CPython 3.11 on Windows and Linux.

| Claim | Evidence | Status |
|---|---|---|
| The packet parser and writer accept the documented shape, refuse everything else with a named code, and round-trip byte for byte | `tests/test_context_envelope.py`, invented data | Verified on invented data |
| The helper's cleaning gives the same result as the upstream rules | 40 invented inputs whose expected values were produced by running the upstream function under Node 24; `tests/test_context_sanitize.py` | Verified on invented data |
| Freshness verdicts | `tests/test_context_tracker.py`, invented data | Verified on invented data |
| The clipboard parser accepts and refuses text correctly | `tests/test_context_clipboard.py` with a stand-in reader | Verified on invented data |
| The Windows clipboard read returns real text | The text path has not been run on real clipboard text; only the no-text case was compared with an independent check | Not verified |
| The strip reader decodes invented frames: clean grids at 2, 3, 4, 6 and 8 pixel cells and 32 to 512 columns, busy backgrounds, reduced contrast, noise, soft edges, gamma, and resizes by 10 scales with 4 filters | `tests/test_context_strip.py`; damaged frames give a named error and never other data | Verified on invented frames |
| The probe addon runs under Lua 5.1 and its packets, text cleaning, checksum, cells and drawn rectangles agree with the helper's own code, including pixel for pixel against the reference renderer and decoded back from invented screens | `tests/test_context_addon.py`, `tests/test_context_addon_ui.py`, run with `lupa` 2.8 (Lua 5.1) against an invented game | Verified in a Lua 5.1 test runtime |
| The addon never touches a secret value, reads only the listed interfaces, writes only its slash command and saved table, and registers no events | The same tests; the invented secret value raises on any use except `issecretvalue` | Verified against the invented game only |
| `context-probe --source window` captures the game window and reads the strip | The command's tests use a stand-in grabber; the real capture function is the one other helper features use, but it has not been run for this command | Not verified |
| The addon loads and draws in a WoW client | Not run | Not verified |
| The strip is drawn crisply and read correctly from a real capture in each display mode, UI scale, colour filter and HDR | Not run | Not verified |
| Ctrl+C in the addon's edit box reaches the clipboard on a client | Not run | Not verified |
| Addons may call `CopyToClipboard` on Forever | Not run. The published interface source for the Forever build (70532) marks the function as restricted | Not verified, and a warning sign |
| Secret values appear where, and how often, the design assumes | Not run | Not verified |
| The logout guard keeps real values when a client reports zeros at unload | Tested on invented data only (addon 0.4.1) | Not verified on a client |

The strip reader was also explored with scripts that are not in the repository (a wider sweep of resize filters and cell sizes, including 2 pixel cells on cluttered backgrounds, which are the weakest case). Treat those numbers as indicative; the table above lists only what a committed test reproduces.

## Proposed repository rule (not applied)

`AGENTS.md` is not changed by this work. Reading a packet from the game window or the clipboard is new behaviour next to the existing capture and assistive-input exceptions, so the wording below needs the operator's approval before it goes into `AGENTS.md`. It deliberately does not broaden the Ctrl+Alt+F9 gear-comparison exception.

> Context channel (proposed). The operator may run `context-probe` to read one packet per invocation from a fresh capture of the selected game window (decoded in memory and dropped, never saved or logged), from the clipboard text the player copied, or from an image file the operator names. The opt-in `WoWCompanionProbe` addon draws a strip or shows a text box only when the player types a `/wfhprobe` command. A packet is untrusted data: parse it with `wow_helper/context`, show cleaned text only on explicit request, and never derive game input, commands, focus changes or pointer movement from a packet. No capture loop, background watcher, scheduled capture, clipboard monitor or replay on restart. This adds no hook, memory access, injection or automation.

## Licensing

The cleaning rules are a port of `sanitizeGameString` from NeverQuestAlone (MIT), itself derived from chelinho139/wow-ai (MIT); `THIRD_PARTY_NOTICES.md` carries the licence text. The test vectors are invented inputs with expected values produced by running that function. The Lua test runtime is the optional `lupa` package (`pip install -e ".[chat,addon-tests]"`); without it the tests that need it skip.
