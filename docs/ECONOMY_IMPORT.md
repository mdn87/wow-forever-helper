# Session economy import

Status: a narrow source-derived importer and reviewed discussion screen are
implemented locally. Synthetic automated tests (2026-11-01) cover parser
behavior, bounds, comparison refusals, and the screen's import, preview,
single send, Journal save, and restart. Theme layout, live provider delivery, and
actual addon exports remain unverified until the operator returns to WoW. Source
research was performed on 2026-10-31; it is not runtime acceptance.

## Use

Open **Menu → Session economy analysis…**, or find it with **Ctrl+K**. Paste or
explicitly import one UTF-8 CSV from English **Journalator → Summary → By Type**,
using Journalator 171 and Auctionator 341. Other addon versions, views, and locales
are unsupported. Mismatched columns/categories, localized money strings, and
transaction layouts are refused, but a structurally identical CSV cannot reveal
its actual version or view. The reader never searches game folders or executes Lua.

Supply private profile and filter-scope aliases, the edition, and exact reporting
start/end timestamps with time zones. Use aliases such as `profile-a` and
`all-monitored`, rather than character or realm names. An example timestamp is
`2026-10-01T00:00:00Z`. Confirm that the export versions, English view, selected
characters/realms, filters, monitors, and reporting bounds match these declarations.
The CSV itself contains none of those details, so the review labels them as user
declarations rather than independently verified facts. It cannot detect conflicting
identities or correct a mislabeled period.

**Prepare review** shows the complete normalized category rows, integer-copper
totals, missing coverage, and exact destination. **Save note** keeps that reviewed
evidence in Journal, including its declared profile and period. **Send** explicitly
uses the selected conversation once and preserves its draft. Changed inputs or a
changed destination require another review. Opening, importing, preparing, saving,
restoring, and searching send nothing. The raw CSV is omitted from prepared agent
context; editable drafts follow the existing local notebook persistence.

**Compare earlier period** accepts a second export for the same declared profile,
edition, and filter scope. Its end must precede the current start strictly, because
the source uses inclusive boundaries. Each period spans at most 366 days. The
review shows differences in exported totals; it does not infer equal playtime or
calculate hourly rates. Identical normalized summaries are conservatively refused
as possible duplicate exports, even when equal totals could be legitimate. Use a
one-period review in that case.

Each review stands alone. There is no cumulative ledger, transaction merging,
automatic cross-note comparison, or addition of repeated imports to prior totals.
Saving the same export again creates another note, not another ledger entry.

## Pinned source contract

Journalator 171 is pinned to author revision
`c6166ead2801d93cde0dbb1d09b0410ad4316b8d`:

- The [export handler](https://github.com/TheMouseNest/Journalator/blob/c6166ead2801d93cde0dbb1d09b0410ad4316b8d/Journalator_Display/Source/Display/Main.lua#L249-L258)
  asks the selected view's provider for CSV.
- The [base provider](https://github.com/TheMouseNest/Journalator/blob/c6166ead2801d93cde0dbb1d09b0410ad4316b8d/Journalator_Display/Source/DataProviders/Display.lua)
  inherits Auctionator's exporter.
- The [By Type provider](https://github.com/TheMouseNest/Journalator/blob/c6166ead2801d93cde0dbb1d09b0410ad4316b8d/Journalator_Display/Source/DataProviders/SummaryByType.lua)
  defines the four columns, negates outgoing amounts, and omits categories with
  zero incoming and outgoing values.
- The [English labels](https://github.com/TheMouseNest/Journalator/blob/c6166ead2801d93cde0dbb1d09b0410ad4316b8d/Journalator/Locales/enUS.lua)
  and [category aggregation](https://github.com/TheMouseNest/Journalator/blob/c6166ead2801d93cde0dbb1d09b0410ad4316b8d/Journalator_Display/Source/GetProfit.lua)
  establish the category names and show how transfers, fees, deposits,
  and enabled monitors affect coverage. The adapter does not reconstruct individual
  transactions from those totals.

Auctionator's expected GitHub repository URLs returned 404 during this research.
The author's [official Auctionator 341 package](https://www.curseforge.com/wow/addons/auctionator/files/9162359)
remained available. Its `Auctionator-341.zip` SHA-256 is
`32c4a2a8d24d46f4fc2725e62c255171a62877854ce6fcbd3272735f6dd3e4e2`.
Only source text was inspected; the package was neither executed nor installed,
and no addon code, artwork, or game data is bundled here.

Within that package, `Source/Components/DataProviders/DataProvider.lua`,
`AuctionatorDataProviderMixin:GetCSV`, iterates the complete layout, including
hidden columns. Headers use `headerText`; row values use
`headerParameters[1]`, independent of displayed price-cell formatting. Numbers
use Lua `tostring`; strings are double-quoted after embedded quote characters
are removed. Rows use commas and newline separators. `Locales/enUS.lua` supplies
`Name`. Combined with the pinned Journalator layout, the contract is:

| Column | Meaning retained by the companion |
| --- | --- |
| `Name` | One recognized English category; never a player or item name. |
| `In` | Nonnegative incoming integer copper. |
| `Out` | Nonpositive outgoing integer copper. |
| `Profit` | Must equal `In + Out`; labeled **net cash movement**, not economic profit. |

The recognized categories are Auction House, WoW Tokens, Crafting Orders,
Questing, Looting, Taxis, Repairs, Trainers, Vendoring, Mail, Trades, and Mission
Tables. Unsupported names cause refusal of the entire import, without echoing
the unexpected text. Categories absent from a summary are listed as missing;
they might be zero, filtered out, disabled, or unavailable on that edition.

This hand-written example is synthetic; it contains no play data:

```csv
"Name","In","Out","Profit"
"Questing",120000,0,120000
"Repairs",0,-20000,-20000
```

These rows describe 100,000 copper of net cash movement across the exported
categories. They do not establish the completeness of the period or the profit
of an activity. The header's `Profit` label is preserved only for format matching.

## Bounds and outstanding acceptance

Inputs are limited to 64,000 UTF-8 bytes per CSV, 100 physical lines, 1,024
characters per physical line, 100 characters per field, and one row per each of
the twelve recognized categories. Empty exports, zero-only rows, malformed CSV,
unknown/repeated columns or categories, inconsistent signs/totals, floating-point
or scientific notation, and values or totals above 9,000,000,000,000,000 copper
in magnitude are refused. Nothing is partially imported or silently discarded.
Derived comparison deltas use Python integers and may span twice that bound.

Still to check when testing resumes: quoting/BOM/encoding behavior, malformed and
oversized input, unknown categories and columns, integer boundaries, empty
exports, duplicate/overlapping comparisons, changed profile/edition declarations,
missing monitors, transfers/refunds, Journal and draft restoration, both themes,
and explicit Send/destination changes. Synthetic checks and actual addon export
observations must be recorded separately. This scoped aggregate reader does not
complete a transaction-level economy ledger or qualify every addon/client pair.
