# MDT route import research

Status: source research only, checked 2026-10-31. The companion still accepts
readable route notes and selected images. Encoded MDT exports remain unsupported.
No decoder, map renderer, or edition compatibility claim was added. Application,
UI, and live-client testing remain deferred at the operator's request.

## Current upstream format

The inspected author revision is
`613c7c67936fd0bfa15f2f5a3881019a4d90462a`, whose
[manifest](https://github.com/Nnoggie/MythicDungeonTools/blob/613c7c67936fd0bfa15f2f5a3881019a4d90462a/MythicDungeonTools.toc)
declares MDT 6.3.28 and interface targets 120107 and 120105. This records the
source examined; it does not identify an installed addon or prove compatibility
with the operator's client.

The author's
[transmission code](https://github.com/Nnoggie/MythicDungeonTools/blob/613c7c67936fd0bfa15f2f5a3881019a4d90462a/Modules/Transmission.lua#L10-L26)
emits `!~MDT2~` followed by Base64-encoded, Deflate-compressed CBOR. Both
serialization and compression call the game's native `C_EncodingUtil` API.
The reader at this revision rejects other prefixes. Implementing the older
LibDeflate/AceSerializer path alone would therefore miss these exports.

The inspected
[package metadata](https://github.com/Nnoggie/MythicDungeonTools/blob/613c7c67936fd0bfa15f2f5a3881019a4d90462a/pkgmeta.yaml)
does not supply a portable implementation of those native codecs. This source
pass did not establish the exact emitted compression framing or CBOR table
representation. A codec with the same algorithm names is not yet a qualified
reader of the game's actual bytes.

## Route meaning and privacy

The author's
[preset validation and normalization](https://github.com/Nnoggie/MythicDungeonTools/blob/613c7c67936fd0bfa15f2f5a3881019a4d90462a/Modules/Presets.lua)
use a route title, dungeon index, current pull/sublevel, and a pull table.
Pull entries reference enemy-table indexes and clone indexes. Those indexes
need matching dungeon data before they can identify enemies or positions.
The same module can attach `createdBy` character and realm information.

Consequently, a future importer must discard author identity, route UID, and
unselected free text before preparing agent context. A decoded numeric pull
list alone cannot establish NPC names, mechanics, map positions, enemy forces,
or route suitability. It must not silently substitute a different data version.

The author's
[build check](https://github.com/Nnoggie/MythicDungeonTools/blob/613c7c67936fd0bfa15f2f5a3881019a4d90462a/BuildCheck.lua#L23-L30)
limits this addon revision to its Retail branch. It supplies no basis for
claiming Classic Forever compatibility. Manual Forever route discussion remains
available through images and readable notes.

## Smallest useful implementation after qualification

The first importer should produce a reviewed structural summary: source
revision and declared edition, dungeon index, ordered pulls, and opaque enemy
and clone references. It should explicitly omit identity, drawing objects,
embedded notes, and unsupported fields. It should retain the existing image
workflow so the operator can supply visible route context separately.

The following are proposed desktop limits, not limits claimed by MDT:

| Boundary | Proposed limit and refusal behavior |
| --- | --- |
| Text input | 24,000 UTF-8 bytes, matching the existing route editor; require one recognized prefix and strict Base64. |
| Compression | At most 18,000 compressed bytes and 256,000 expanded bytes; stop while expanding, require a complete single stream, reject trailing data. |
| CBOR | Depth 16, 10,000 total values, 4,000 bytes per string; reject duplicate keys, references/cycles, unsupported tags, non-finite values, and trailing values. |
| Route shape | At most 200 ordered pulls and 4,000 enemy/clone references; reject ambiguous indexes and unsupported shapes rather than repairing them. |
| Prepared context | Keep the normalized summary within existing context bounds; refuse excess content rather than silently dropping pulls. |

These limits need behavior checks before support is claimed. A decoder should
parse data directly; it must never execute Lua, invoke an addon runtime, load
embedded code, fetch links, or send a provider request while importing. No addon
map artwork, extracted game data, or gameplay capture belongs in this repository.

## What would unblock the decoder

1. Establish the native wire representation from an author-maintained portable
   specification, or qualify a hand-written synthetic route through the
   appropriate client codec. Settle compression framing and CBOR strings,
   arrays, integer-keyed maps, and empty tables. A real player's export is not
   needed and must not become a public fixture.
2. Record the supported addon revision, Retail client build, and exact data
   shape. If only opaque references can be established, label them as such;
   require a separately qualified mapping before producing named/map-based
   claims. Classic Forever needs an independent contract.
3. When testing resumes, exercise the size/depth limits, malformed streams,
   duplicate keys, identity omission, unsupported editions, and manual fallback.
   The upstream
   [transmission test](https://github.com/Nnoggie/MythicDungeonTools/blob/613c7c67936fd0bfa15f2f5a3881019a4d90462a/Developer/Tests/TestTransmissionValidation.lua)
   performs an in-client round trip; it is not a portable encoded fixture and
   was not run here.

The remaining dependency is codec and edition qualification, not UI wiring.
With those observations and checks deferred, adding a speculative decoder now
would create another unverified integration without resolving its input
contract. Keep the existing manual route workflow until that dependency is met.
