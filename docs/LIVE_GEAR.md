# Live gear comparison

Open **Live gear comparison…** from a companion chat or activity menu. Select a
conversation created by the companion (Codex or Claude), with image-reading
support. Existing external conversations cannot provide this feature's
structured response contract.

1. Choose the game edition, enter your build/role and comparison goal, and click
   **Capture preview**. WoW must be open and visible. This preview stays local.
2. Drag around the area where the candidate and equipped tooltips will appear.
   Include both equipped panels for rings or trinkets. Click **Review region**
   and check the cropped image and destination. Exclude names or chat you do
   not want sent.
3. Click **Enable shortcut**. In WoW, show the item comparison and press
   **Ctrl+Alt+F9** once. **Shift may stay held** while pressing the shortcut.
   Keep the tooltips visible while capture finishes.
4. Read **Result** and **Captured evidence**. Results arrive without switching
   focus or automatically selecting a tab. Capture, extraction and explanation
   durations are shown separately; a model answer is not instant.
5. **Save to Journal** opens the existing review dialog. It preserves the source
   conversation, image reference, observed facts, calculated differences,
   edition and capture time. Saving requires an explicit action in that dialog.

## What is compared

The image reader extracts the hovered candidate and visibly labeled Equipped
tooltips into bounded fields. Code checks the edition, distinct non-overlapping
tooltip bounds, slot, completeness, types, units and numerical ranges before
subtracting stats. Unreadable or missing values stay unknown; missing stats are
not silently treated as zero. Both equipped ring/trinket panels remain separate
choices. Panel order does not establish a physical equipment-slot number.
Weapon-layout changes need more evidence and are refused by this first version.

The program calculates candidate-minus-equipped differences. A separate agent
request explains their relevance to your build and goal. Sourced mechanics and
unknown enchants, sockets or effects stay separate from observed base stats.
There is no asserted overall upgrade percentage, automatic equip action, item
database, or Blizzard online API connection. Review the image against the
extracted facts: structural validation cannot prove every model reading correct.

## Capture and request boundaries

Windows Graphics Capture targets the identified game window by HWND. Only frames
whose compositor timestamp is at or after capture initialization are accepted.
The worker stops after one accepted frame and has a ten-second process deadline.
It does not fall back to desktop capture or PrintWindow. Windows may show its
capture border briefly. Normal comparisons save only the approved region;
the explicitly requested setup preview includes the whole game window locally.

WoW must be in front when the comparison is requested. No pointer movement,
focus change, game input, reload, continuous hover monitoring or automatic retry
is performed. Disable or closing the comparison panel releases its shortcut.
Voice remains held Keypad-minus dictation into a draft; it never triggers a
comparison automatically.

Only one comparison runs per panel, with durable request IDs. Presses while busy
are discarded. Destination, edition, build, goal or region changes require
another review; changed game dimensions require a new preview. Disabling during
capture prevents delivery. A model request already sent may finish in its original
conversation. Restart never restores approval or replays captures. Missing image
support, malformed extraction, absent tooltips and failed sends produce explicit
failures. An explanation failure preserves validated stat differences for review.

Captures, previews, requests and Journal evidence are private runtime data under
the existing ignored storage. Never commit them or copy them to public issues.

## Verification

On 2026-10-29, a real Retail check exposed the old HWND capture path returning
identical cached pixels across changed game views. The replacement produced a
fresh, readable image containing the candidate and both Equipped ring panels;
capture took about 3.18 seconds. The operator confirmed switching back to chat
manually, rather than capture taking focus. No game input or reload was sent.

A separate native test for each of Codex and Claude used entirely synthetic tooltip pixels through the
production extraction, validation, subtraction and explanation path. It returned
the expected differences; extraction and explanation each took roughly 14–20
seconds. These are observed timings, not guarantees. Synthetic tests cover invalid
evidence, missing values, unit mismatch, ring choices, region/size and destination
changes, duplicates, busy presses, failed sends, restart, Journal evidence and
isolated UI lifecycle in both themes. The full player-operated comparison flow
has not yet been exercised end to end.

The [one-shot diagnostic](LIVE_GEAR_PROOF.md) remains available for capture
troubleshooting. It is not required for normal comparisons.
