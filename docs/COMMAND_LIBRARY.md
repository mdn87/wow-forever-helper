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

## Find new commands with your agent

Select a conversation in the companion, then open **Find new commands…** in the
library. Enter the effect you want and, if known, your exact client version.
**Review request** shows the destination, model choice and complete prompt.
**Send one search** sends that request once through the selected conversation,
without replacing your unsent chat draft. Changing the question, destination or
saved model settings requires a new review. Results appear in the conversation;
you can save useful replies to the Journal. Suggestions are not automatically
added to the curated library or executed in the game.

The prompt asks for up to three candidates, two web searches, sources,
compatibility evidence, caveats and read/reset commands, in under 400 words.
These are instructions to the agent, **not a hard token cap**. An existing
conversation's history and tools can consume additional usage. Attached agents
retain their current permissions. If browsing is unavailable, the request asks
the agent to disclose that rather than claim fresh verification.

The companion allows three research attempts across all windows, then pauses
research until **Allow 3 more searches** is pressed. The allowance persists over
restarts. Failed or uncertain sends count because delivery may have occurred;
there is no automatic retry. Ordinary chats, activity requests and actions in
the provider's own app are outside this allowance. Renewing it does not purchase
credits or reset provider quota.

## Model and usage controls

Use the model button above the conversation or **Settings → Conversation →
Model & usage…**. Settings apply per conversation on the next companion send.

| Connection | Model control | Usage visibility |
| --- | --- | --- |
| Companion-owned Codex | CLI model ID and reasoning effort; selected models use standard service tier | Live catalog and quota snapshot when the local app server is available |
| Attached Codex | Choose an advertised model and supported effort; next send starts a turn only while idle and changes later turns in that thread too | Read-only catalog and account quota snapshot |
| Companion-owned Claude | CLI model name or `haiku`, `sonnet`, `opus` alias; low/medium/high effort | Check `/usage` in Claude; quota is unavailable through the companion's CLI transport |
| Attached Claude | Use `/model` and `/effort` in Claude; companion controls are disabled | Check `/usage` in Claude |

Companion-owned chat defaults to low reasoning effort and a 180-second CLI time
limit. You can choose 90, 180, 360 or 600 seconds. This stops the owned CLI process
at its time limit; it does not promise provider-side cancellation or a token or
dollar ceiling. It cannot time-limit an externally attached session. Background
activity research has its own existing settings and is not changed by these
chat preferences.

A blank model inherits the provider or session default, which is not necessarily
the cheapest option. For attached Codex, leave both model and effort blank to
keep the existing queue behavior. Explicit model choices use the supported
`turn/start` API and do not fall back to queued delivery after errors. The
companion does not upgrade models or retry inference automatically. Provider
policies still apply. Unavailable models or efforts can be rejected by the
provider, and an uncertain delivery must be checked in the original conversation.

Subscription pricing is not a token allowance. Quota displays are snapshots,
not cost predictions; unavailable quota is explicitly unknown. The companion
does not configure billing, buy credits or set provider spending caps. Check
paid extra usage and spending limits in the provider's own billing settings.

Provider references: [Codex App Server](https://learn.chatgpt.com/docs/app-server),
[Claude CLI](https://code.claude.com/docs/en/cli-reference), and
[Claude model configuration](https://code.claude.com/docs/en/model-config).
