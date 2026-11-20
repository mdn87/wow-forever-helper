# Command library

Open **Settings → Tools → Command library**, or press **Ctrl+K** and search for
"command library". Search by a console-variable name, effect, or symptom and
choose a category to narrow the list.

Select an entry to see its purpose, exact command, evidence label, caveats and
source link. **Copy command** puts one line on the clipboard for you to paste
into game chat. The companion does not send it to the game, modify game files,
install addons, or change settings itself.

For settings, **Copy read value** lets you inspect the current value first.
Record it before experimenting. **Copy reset** copies a command to restore the
game's default, which may differ from your previous custom value. These buttons
are disabled for entries where they do not apply.

## Contents and evidence

- Graphics: draw distance, distant detail, foliage, lighting, HDR and inspection
  commands for settings without verified tuning values.
- Fixes: disabling FSR sharpening with `/console ResampleSharpness -1`, reported
  to resolve ground-brightness changes during movement. `0` is maximum sharpening.
- Convenience: automatic looting.
- Addons: Junk & Repair Manager's confirmation toggle and settings shortcut.
  `/aajs on` skips manual sale confirmation; `/jrm` opens settings where automatic
  vendor selling is enabled separately. The addon must already be installed.

Experimental values are examples, not verified engine maximums. Some controls
overlap menu settings, may already be enabled, or may be clamped or ignored by a
particular build. A command being present does not prove its effect. Source links
are references, not evidence of testing against the player's installed client.

The catalog is hand-authored in `wow_helper/command_library.py`; it contains no
client-data dump or copied guide text. Add entries with an original explanation,
category, exact command, evidence label, limitations and source. Tests cover
search, filtering, copying, empty results, requirements and companion navigation.
