# Hands-free voice bridge protocol

Lugos Voice delivers finished spoken turns to one WoW Helper chat through files in the helper checkout's ignored `.runtime/voice-bridge/` folder. Version 1. User-facing behavior is in [CHAT.md](CHAT.md#hands-free-voice-from-lugos-voice). The companion side is `wow_helper/voice_bridge.py`; the sender is `listener/_wow_helper_bridge.py` in Lugos Voice.

## Files

| Path | Written by | Contents |
|---|---|---|
| `binding.json` | companion, while a chat is connected | `version`, `binding_id` (new UUID per connection), `label`, `provider`, `connected_at`, `heartbeat` (refreshed every 5 seconds) |
| `inbox/<id>.json` | sender, written to `<id>.json.tmp` then renamed | `version`, `id` (UUID, equal to the file name), `binding_id`, `text`, `spoken_at` (epoch seconds) |
| `claimed/<id>.json` | companion | created exclusively when it takes a request, so an id is handled at most once |
| `results/<id>.json` | companion | `id`, `status` (`sent`, `rejected` or `failed`), `detail`, `at` |

## Rules

- No `binding.json`, or a heartbeat older than 15 seconds, means no chat is connected. The sender then leaves the turn to its normal routing.
- The companion refuses a request whose `binding_id` is not the current one, whose `spoken_at` is more than 60 seconds old, more than 5 seconds in the future or before the connection, whose text is empty, over 6,000 characters or contains a null character, or that arrives while the chat is sending. Refusals are written to `results/`.
- Disconnecting deletes `binding.json` only if it still holds that connection's `binding_id`. A request for a connection that ended is not answered; the sender reports that the companion did not answer.
- `sent` means the chat accepted the message for delivery to the agent. It does not confirm an agent reply.
- Receipts in `claimed/` and `results/` older than a day are removed when a chat connects.
