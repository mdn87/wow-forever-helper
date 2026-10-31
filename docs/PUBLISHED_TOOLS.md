# Explicit publications for local agent tools

F18 has a local publication store, management commands, and an MCP stdio server. They expose explicitly selected, frozen Journal evidence through opaque record IDs. Tests were skipped at the operator's request. Authorization behavior, protocol interoperability, provider setup, and actual provider conversation binding remain unverified. This is experimental tooling; it does not complete F18 or establish Codex/Claude integration support.

## Select what a conversation may read

Save the reviewed evidence in Journal with its original conversation first. The initial record shape is `reviewed_journal_evidence`, using the existing bounded Journal metadata and evidence used by the addon troubleshooting and build notebooks. Publication copies the selected note and its evidence. It omits local image references and records that omission as a gap. It does not fetch an image, read a new game snapshot, inspect an addon, open provider transcripts, or update the saved evidence.

Management currently uses the CLI; there is no publication-management dialog. Journal and note UUIDs are in the private saved Journal files under `.runtime/chat/journals/`. The source conversation UUID must match the saved note's source. These are local identifiers; keep native conversation IDs and private state out of issues and commits. The placeholders below must be replaced locally.

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

No real grants, publications, or provider requests were created during implementation. Syntax compilation and static diff/leak inspection are distinct from runtime acceptance. Meaningful authorization/data-isolation checks and separate Codex/Claude setup and capability qualification remain required before claiming support. A user-facing management dialog also remains outside this CLI increment. Prepared evidence files and the existing explicit send workflow remain available.
