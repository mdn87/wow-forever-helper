# Explicit publications for local agent tools

F18 has a Journal management screen, local publication store, management commands, and an MCP stdio server. They expose explicitly selected, frozen Journal evidence through opaque record IDs. Tests were skipped at the operator's request. UI behavior, authorization, protocol interoperability, provider setup, and actual provider conversation binding remain unverified. This is experimental tooling; it does not complete F18 or establish Codex/Claude integration support.

## Select what a conversation may read

Save the reviewed evidence in Journal with its original conversation first. The initial record shape is `reviewed_journal_evidence`, using the existing bounded Journal metadata and evidence used by the addon troubleshooting and build notebooks. Publication copies the selected note and its evidence. It omits local image references and records that omission as a gap. It does not fetch an image, read a new game snapshot, inspect an addon, open provider transcripts, or update the saved evidence.

## Journal controls

Open Journal's **Resume session**, select a saved note, then choose **Tool access…**. The screen stays bound to that note and its original conversation while other Journal or chat selections change. A note without a saved source conversation cannot open this workflow. An unpublishable note can still open access management for its known source, so existing grants can be removed.

- **Review** shows the exact frozen note, text evidence, and gaps to publish. **Review saved note** rereads only that bound note. Publishing compares the current saved selection with the review and refuses a change until it is reviewed again. A changed source conversation requires closing and reopening the screen.
- **Access** lists grants for the original conversation, including their expiry and removal state. Choose a one-hour, 24-hour, or seven-day lifetime and press **New grant** to create access without publishing data. Select an active grant and explicitly press **Publish note** after review. The record list shows frozen-note summaries, publication times, and available snapshot ages. **Remove record** and **Remove grant** remove future access while keeping retained snapshots and Journal notes.
- **Private setup** initially hides the launch descriptor. **Show private setup** displays it locally only after checking the selected grant and descriptor. **Copy setup** rechecks both before placing credentials and paths on the system clipboard. These controls do not configure a provider or send requests.

Opening the screen, switching grants, and refreshing the list publish nothing. Local access state refreshes every five seconds. Grant expiry or removal, changed setup, or unreadable state clears any setup shown in the screen and disables unavailable operations. The backend checks access again when a button is pressed. Closing the screen clears its displayed setup and cancels its refresh callback. Clipboard copies and data already retained by a provider cannot be erased by closing the screen or removing access.

The screen uses the existing Journal window styling, a 480 × 600 minimum size, and separate tabs for review, access, and private setup. Theme layout, enlarged text, keyboard use, repeated open/close, publication failure handling, and authorization behavior have not been exercised. No interaction or visual acceptance is claimed.

## CLI management

The same operations remain available through the CLI. Journal and note UUIDs are in the private saved Journal files under `.runtime/chat/journals/`. The source conversation UUID must match the saved note's source. These are local identifiers; keep native conversation IDs and private state out of issues and commits. The placeholders below must be replaced locally.

Create a conversation grant:

```console
python -m wow_helper published-tools create --provider claude --session-id SESSION_UUID
```

`--provider` accepts `codex` or `claude` as the intended destination label. This does not connect the provider or verify its capabilities. The default lifetime is 24 hours; `--hours` permits 1–168 hours. Creation publishes no evidence. It returns a new grant ID and `configuration_required`, with provider integration marked `unverified`.

Publish a selected saved note:

```console
python -m wow_helper published-tools publish --grant-id GRANT_UUID --journal-id JOURNAL_UUID --note-id NOTE_UUID
python -m wow_helper published-tools status --grant-id GRANT_UUID
```

Publication requires reviewed evidence and an exact match between the note's source provider/conversation and the grant. A note saved without a source conversation cannot be published through this workflow. Existing user-folder and account-folder identity patterns are refused; save a reviewed selection with those values removed. Publication never silently edits or truncates that selection. The result contains an opaque record ID. Publishing an unchanged selection again reuses its current record ID and original publication time. A changed selection requires an explicit publish and receives a new ID. Ordinary refresh, Journal updates, and restarts never republish data.

Remove future access to one record or the entire grant:

```console
python -m wow_helper published-tools revoke --grant-id GRANT_UUID --record-id RECORD_UUID
python -m wow_helper published-tools revoke --grant-id GRANT_UUID
```

Removal marks retained publications unavailable; it never deletes Journal notes or snapshots. A new tool request rechecks the saved grant and publication state. A response already in progress can reflect its previously authorized snapshot. Removal cannot erase information already sent, copied, or retained in provider history. Expired grants deny access, including after a server restart.

## Private launch descriptor and authentication

Creation writes a private launch descriptor at `.runtime/chat/tool-access/GRANT_UUID.json`. It contains an executable path, fixed server arguments, and environment values including `WOW_HELPER_TOOL_TOKEN`. It is sensitive local configuration. Its token and machine paths are never printed by the management commands. The descriptor and publication state remain in ignored runtime storage. POSIX files are created with owner-only read/write permissions; Windows protection relies on the local account's filesystem permissions and remains unverified.

The publication state stores only a SHA-256 token digest; the private launch descriptor holds the capability token. Every protocol operation that returns tool information or records rechecks the grant. Token comparisons use a constant-time digest comparison. Credentials presented for a different grant do not select a different conversation or record list. Requests cannot supply an alternative storage path, provider, session, or source filename.

The descriptor uses `pythonw.exe` on Windows and refuses to substitute a console Python executable. The provider must launch it with inherited stdin/stdout pipes. `PYTHONPATH` is set to this checkout, so launch does not depend on the provider's working directory. Actual windowless launch behavior and provider configuration have not been checked.

Provider configuration remains a separate integration step. This increment changes no global or per-provider settings and provides no automatic connection. A compatible client must attach the descriptor only to the intended conversation. The server authenticates a capability bound to a recorded destination; it cannot independently attest the native provider's current conversation. Copying a capability into another client or a global provider configuration expands who can use it. The intended provider label is not proof of caller identity, and this tool boundary does not restrict a provider's other existing filesystem permissions.

## Tool protocol and record boundaries

The server implements the [MCP stdio transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#stdio), [initialization lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle), and [tool list/call methods](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) for protocol version `2025-06-18`. It negotiates that version explicitly and declares only tools. A client that does not support the returned version must disconnect. Authentication is through the private launch environment, not a network endpoint.

The two tools are:

| Tool | Accepted arguments | Result |
| --- | --- | --- |
| `list_published_records` | Empty object | IDs, record kinds, and publication times for this grant's available records |
| `read_published_record` | One `record_id` UUID | Frozen note/evidence, evidence gaps, publication age, and available preparation/snapshot ages |

Only records owned by the bound grant and still available may be read. Unknown, removed, or other-grant record IDs produce a fixed unavailable result. Text inside a published record remains untrusted evidence; the server never interprets it as commands. The tool server has no game-query, input, source-refresh, shell, arbitrary-file, or publication-mutation method.

Age fields distinguish publication time from preparation and snapshot time. Missing or future source timestamps produce `null` ages, and future known times mark clock uncertainty. Unknown capture time cannot be inferred from a recent publication. The first record format preserves reviewed text and existing metadata; it does not add a validated addon export schema.

Protocol requests are bounded to 16,000 UTF-8 bytes per newline-delimited frame, replies to 160,000 bytes, and each server connection to 10,000 frames. Malformed or oversized frames have fixed responses; oversized framing closes the connection. There are no batch requests, subscriptions, resources, network listeners, or provider requests. Protocol stdout contains only JSON-RPC messages. Authentication failures and startup diagnostics never echo credentials, paths, or raw provider messages.

Publication state is bounded to 4,000,000 bytes, 32 retained grants, 128 retained records, and 32 records per grant. Each frozen record is at most 64,000 encoded bytes; oversized selections are refused without truncation. Revoked and expired entries still count toward retention limits. Nothing is silently purged. Writes use exclusive ownership and atomic replacement. Unsupported or damaged state is refused and kept; interrupted private temporary files are not deleted automatically.

## What remains

No real grants, publications, or provider requests were created during implementation. Syntax compilation and static diff/leak inspection are distinct from runtime acceptance. Journal management is implemented with UI behavior unverified. Meaningful authorization/data-isolation checks and separate Codex/Claude setup and capability qualification remain required before claiming support. Prepared evidence files and the existing explicit send workflow remain available.
