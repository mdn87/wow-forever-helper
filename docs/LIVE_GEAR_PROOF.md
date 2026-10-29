# Live tooltip capture check

F07 starts with a real-client check. Passing synthetic tests does not establish
that the game renders readable tooltips in a window capture. The diagnostic
below prepares that check; it is not the delivered gear-comparison feature.

Run from the project root on Windows, using the project's installed chat extra:

```powershell
Start-Process -FilePath .venv/Scripts/pythonw.exe -ArgumentList '-m','wow_helper.tooltip_probe','--flavor','_retail_' -WindowStyle Hidden
```

Use the edition's folder label for `--flavor`: `_retail_`, `_classic_`,
`_classic_era_`, or `_classic_beta_`. One visible matching game window must be
open before the probe starts. No companion restart is required.

1. Read `.runtime/live-gear-proof/latest.json`. Continue only when its `state`
   is `ready`. A shortcut conflict or absent game ends the probe without capture.
2. Click inside WoW so it is active. Hover a candidate item in the bags and show
   its equipped-item comparison tooltip. Keep the pointer there and press
   **Ctrl+Alt+F9 once**; holding **Shift** with this chord is also supported.
   Keep WoW active until capture finishes. Two views of the same item (such as
   its socketing panel and tooltip) do not establish a candidate/equipped pair.
   This temporary diagnostic
   shortcut is separate from held voice input and expires after five minutes.
3. Read the result. `captured` means one local image was saved in the indicated
   run's `captures` folder. `focus_unchanged` compares foreground windows before
   and after capture; it does not prove focus stayed unchanged between samples.
   Record the player's observation separately. `capture_seconds` includes the
   native capture worker and PNG save, not model processing.
4. Inspect the image privately. Verify both item names, variants, slot labels,
   stats, units and effects are readable and associated correctly. Measure the
   image reader's extraction time independently. Missing or ambiguous tooltip
   evidence fails this check; request a new deliberate capture rather than
   substituting a saved equipment snapshot.

The probe captures the selected game window, including any visible chat or
player names. It never captures the whole desktop as a fallback. It does not
move the pointer, change focus, send game input, reload, listen to the microphone,
or submit the image to an agent. Review the local image before sharing it.
Captures and results are ignored private runtime data; never commit them or
copy their contents into public issues, logs, or test fixtures.

The probe exits after its first request, failure, or expiry and unregisters its
shortcut. A failed or expired check needs another explicit invocation; nothing
is replayed on restart. The normal [live-comparison flow](LIVE_GEAR.md) provides
region preview, approved destination, validated stat differences and Journal saving.

The original Pillow HWND path returned stale pixels in a real Retail check.
Both the diagnostic and normal capture now use Windows Graphics Capture with a
compositor timestamp check. A fresh Retail tooltip frame was verified afterward;
the diagnostic's `extraction_verified` field remains false because the probe
itself does not run a model or validate an item comparison.
