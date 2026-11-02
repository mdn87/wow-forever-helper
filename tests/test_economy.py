"""Hand-written synthetic Journalator By Type summaries; no real exports, characters, or play data."""

import json
from pathlib import Path

import pytest

from wow_helper.activities import packet_preview
from wow_helper.chat import ChatError
from wow_helper.economy import (CATEGORIES, MAX_COPPER, MODES, SCHEMA, copper, parse_summary,
                                prepare_economy, reporting_period)
from wow_helper.imports import read_text

FIXTURES = Path(__file__).parent / "fixtures" / "economy"
HEADER = '"Name","In","Out","Profit"'


def fixture(name):
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith("# ")) + "\n"


CURRENT = fixture("by_type_current.csv")
EARLIER = fixture("by_type_earlier.csv")


def summary(*rows, header=HEADER):
    return "\n".join((header,) + rows) + "\n"


def form(**changes):
    values = dict(edition="Retail", schema=SCHEMA, confirmed="Checked", mode=MODES[0],
                  profile="profile-a", scope="all-monitored", question="Explain my cash movement.",
                  csv=CURRENT, start="2026-10-08T00:00:00Z", end="2026-10-15T00:00:00Z",
                  previous_csv=EARLIER, previous_start="2026-10-01T00:00:00Z",
                  previous_end="2026-10-07T23:59:59Z")
    values.update(changes)
    return values


# --- Name,In,Out,Profit contract -------------------------------------------------

def test_pinned_summary_becomes_sorted_integer_copper_rows_and_totals():
    result = parse_summary(CURRENT)
    assert [row["category"] for row in result["rows"]] == ["Auction House", "Mail", "Questing", "Repairs", "Vendoring"]
    mail = next(row for row in result["rows"] if row["category"] == "Mail")
    assert mail == {"category": "Mail", "incoming_copper": 500000, "outgoing_copper": -300000, "net_cash_copper": 200000}
    assert result["totals"] == {"incoming_copper": 3165678, "outgoing_copper": -470000, "net_cash_copper": 2695678}
    assert all(type(value) is int for value in result["totals"].values())
    assert all(type(row[key]) is int for row in result["rows"] for key in row if key != "category")
    # The source column Profit is kept only as net cash movement, never as a "profit" field.
    assert not any("profit" in key.lower() for row in result["rows"] for key in row)
    assert not any("profit" in key.lower() for key in result["totals"])
    assert len(result["fingerprint"]) == 64


def test_missing_categories_are_listed_and_never_filled_with_zero():
    result = parse_summary(CURRENT)
    present = {row["category"] for row in result["rows"]}
    assert result["missing_categories"] == sorted(CATEGORIES - present)
    assert "Looting" in result["missing_categories"]
    assert len(result["rows"]) == 5  # missing categories are not added as zero rows
    complete = summary(*(f'"{name}",1,0,1' for name in sorted(CATEGORIES)))
    assert parse_summary(complete)["missing_categories"] == []


@pytest.mark.parametrize("variant", [
    lambda body: "﻿" + body,
    lambda body: body.replace("\n", "\r\n"),
    lambda body: body.replace('"', ""),
    lambda body: body.rstrip("\n"),
    lambda body: body + "\n\n",
    lambda body: HEADER + "\n" + "\n".join(reversed(body.strip().splitlines()[1:])),
], ids=["bom", "crlf", "unquoted", "no-final-newline", "trailing-blank-lines", "row-order"])
def test_quoting_bom_line_endings_and_row_order_normalize_identically(variant):
    expected = parse_summary(CURRENT)
    assert parse_summary(variant(CURRENT)) == expected


def test_file_import_handles_utf8_bom_and_refuses_other_encodings(tmp_path):
    with_bom = tmp_path / "bom.csv"; with_bom.write_bytes(b"\xef\xbb\xbf" + CURRENT.encode("utf-8"))
    assert parse_summary(read_text(with_bom)) == parse_summary(CURRENT)
    utf16 = tmp_path / "utf16.csv"; utf16.write_bytes(CURRENT.encode("utf-16"))
    latin = tmp_path / "latin.csv"; latin.write_bytes(summary('"Quêsting",1,0,1').encode("latin-1"))
    for path in (utf16, latin):
        with pytest.raises(ChatError, match="UTF-8|binary"):
            read_text(path)


@pytest.mark.parametrize("body", [
    summary('"Questing",1,0,1', header="Name,In,Out"),
    summary('"Questing",1,0,1,1', header="Name,In,Out,Profit,Extra"),
    summary('"Questing",1,0,1', header="name,in,out,profit"),
    summary('"Questing",1,0,1', header="Nom,Entrée,Sortie,Profit"),
    summary('"Questing",1,0,1', header="Name,Out,In,Profit"),
    summary('"Questing",1,0,1', header="Name,In,In,Profit"),
    summary('"Questing",1,0,1', header="Name, In, Out, Profit"),
    fixture("transaction_layout.csv"),
], ids=["missing-column", "extra-column", "lowercase", "localized", "reordered", "repeated", "spaced", "transactions"])
def test_unsupported_columns_and_layouts_are_refused(body):
    with pytest.raises(ChatError, match="Unsupported CSV columns"):
        parse_summary(body)


def test_unknown_category_refuses_whole_import_without_echoing_it():
    body = summary('"Questing",1,0,1', '"Testchar-ExampleRealm",5,0,5')
    with pytest.raises(ChatError, match="unsupported category") as caught:
        parse_summary(body)
    assert "Testchar" not in str(caught.value) and "ExampleRealm" not in str(caught.value)
    for name in ("Quêsting", "questing", " Questing", "Questing ", "Profit"):
        with pytest.raises(ChatError, match="unsupported category"):
            parse_summary(summary(f'"{name}",1,0,1'))


@pytest.mark.parametrize("row, message", [
    ('"Questing",1.5,0,1.5', "integer copper"),
    ('"Questing",1e5,0,1e5', "integer copper"),
    ('"Questing","1,000",0,"1,000"', "integer copper"),
    ('"Questing",10g,0,10g', "integer copper"),
    ('"Questing", 100,0,100', "integer copper"),
    ('"Questing",+100,0,100', "integer copper"),
    ('"Questing",0100,0,100', "integer copper"),
    ('"Questing",,0,0', "integer copper"),
    ('"Questing",١٠٠,0,١٠٠', "integer copper"),
    ('"Questing",-100,0,-100', "In must be nonnegative"),
    ('"Taxis",0,100,100', "In must be nonnegative"),
    ('"Questing",100,-10,100', "Profit must equal"),
    ('"Questing",0,0,0', "zero-only"),
    ('"Questing",1,0', "row layout"),
    ('"Questing",1,0,1,1', "row layout"),
], ids=["decimal", "scientific", "thousands", "gold-suffix", "space", "plus", "leading-zero", "empty",
        "non-ascii-digits", "negative-in", "positive-out", "profit-mismatch", "zero-only", "short-row", "long-row"])
def test_invalid_amounts_and_rows_refuse_everything(row, message):
    with pytest.raises(ChatError, match=message):
        parse_summary(summary('"Repairs",0,-5,-5', row))


def test_repeated_category_and_blank_interior_row_are_refused():
    with pytest.raises(ChatError, match="more than once"):
        parse_summary(summary('"Questing",1,0,1', '"Questing",1,0,1'))
    with pytest.raises(ChatError, match="row layout"):
        parse_summary(summary('"Questing",1,0,1', "", '"Repairs",0,-1,-1'))


@pytest.mark.parametrize("body", [
    HEADER + '\n"Questing,1,0,1\n',
    HEADER + '\n"Ques"ting",1,0,1\n',
], ids=["unterminated-quote", "stray-quote"])
def test_malformed_csv_is_refused(body):
    with pytest.raises(ChatError, match="Malformed CSV"):
        parse_summary(body)


def test_copper_boundaries():
    assert copper(str(MAX_COPPER)) == MAX_COPPER and copper(str(-MAX_COPPER)) == -MAX_COPPER
    assert copper("0") == 0 and copper("-0") == 0
    with pytest.raises(ChatError, match="copper limit"):
        copper(str(MAX_COPPER + 1))
    with pytest.raises(ChatError, match="integer copper"):
        copper("1" + "0" * 16)  # 17 digits never reaches int()
    assert parse_summary(summary(f'"Questing",{MAX_COPPER},0,{MAX_COPPER}'))["totals"]["net_cash_copper"] == MAX_COPPER
    with pytest.raises(ChatError, match="Summary totals exceed"):
        parse_summary(summary(f'"Questing",{MAX_COPPER},0,{MAX_COPPER}', '"Looting",1,0,1'))


# --- Byte, row, line, and field bounds ------------------------------------------

def test_byte_bound_counts_utf8_bytes_not_characters():
    # 32,001 two-byte characters are 64,002 bytes though only 32,001 characters.
    with pytest.raises(ChatError, match="64,000 UTF-8 bytes"):
        parse_summary(HEADER + "\n" + "é" * 32_001)
    with pytest.raises(ChatError, match="64,000 UTF-8 bytes"):
        parse_summary("x" * 64_001)
    with pytest.raises(ChatError, match="Summary CSV"):
        parse_summary(CURRENT + "\0")


def test_line_and_field_bounds():
    with pytest.raises(ChatError, match="at most 100 lines"):
        parse_summary(summary(*(['"Questing",1,0,1'] * 100)))
    with pytest.raises(ChatError, match="1,024 characters per line"):
        parse_summary(summary('"Questing",1,0,1' + "0" * 1024))
    with pytest.raises(ChatError, match="row layout"):
        parse_summary(summary('"' + "Q" * 101 + '",1,0,1'))
    thirteen = [f'"{name}",1,0,1' for name in sorted(CATEGORIES)] + ['"Questing",1,0,1']
    with pytest.raises(ChatError, match="Unsupported summary size"):
        parse_summary(summary(*thirteen))


@pytest.mark.parametrize("body, message", [
    ("", "nonempty"),
    ("   \n\n", "nonempty"),
    (HEADER + "\n", "not evidence of zero activity"),
    ("﻿" + HEADER, "not evidence of zero activity"),
], ids=["empty", "whitespace", "header-only", "bom-header-only"])
def test_empty_exports_are_unavailable_not_zero(body, message):
    with pytest.raises(ChatError, match=message):
        parse_summary(body)


# --- Declared reporting periods -------------------------------------------------

def test_period_is_normalized_to_utc_and_labeled_as_declaration():
    period = reporting_period("2026-10-01T02:00:00+02:00", "2026-10-02T00:00-05:00")
    assert period["start"] == "2026-10-01T00:00:00+00:00"
    assert period["end"] == "2026-10-02T05:00:00+00:00"
    assert "User declaration" in period["provenance"] and "not independently verified" in period["provenance"]
    assert reporting_period("2026-01-01T00:00:00Z", "2027-01-02T00:00:00Z")["end"].startswith("2027-01-02")


@pytest.mark.parametrize("start, end, message", [
    ("2026-10-01T00:00:00", "2026-10-02T00:00:00Z", "timezone"),
    ("2026-10-01", "2026-10-02T00:00:00Z", "timezone"),
    ("2026-10-01T00:00:00.5Z", "2026-10-02T00:00:00Z", "timezone"),
    ("2026-02-30T00:00:00Z", "2026-03-02T00:00:00Z", "invalid"),
    ("2003-12-31T00:00:00Z", "2004-01-02T00:00:00Z", "between 2004 and 2100"),
    ("2100-12-31T00:00:00Z", "2101-01-01T00:00:00Z", "between 2004 and 2100"),
    ("2026-10-02T00:00:00Z", "2026-10-01T00:00:00Z", "end after its start"),
    ("2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z", "end after its start"),
    ("2026-01-01T00:00:00Z", "2027-01-02T00:00:01Z", "366 days"),
    ("", "2026-10-02T00:00:00Z", "Period timestamp"),
    (None, "2026-10-02T00:00:00Z", "Period timestamp"),
], ids=["no-zone", "date-only", "fraction", "invalid-day", "too-early", "too-late", "reversed", "empty-span",
        "too-long", "blank", "missing"])
def test_invalid_periods_are_refused(start, end, message):
    with pytest.raises(ChatError, match=message):
        reporting_period(start, end)


# --- Prepared review ------------------------------------------------------------

def test_one_period_review_labels_declarations_and_omits_raw_csv():
    packet = prepare_economy(form())
    assert set(packet["reports"]) == {"economy"}
    data = packet["reports"]["economy"]["data"]
    assert data["mode"] == MODES[0] and data["comparison"] is None and "previous" not in data
    record = data["current"]
    assert record["source_kind"] == "Journalator Summary By Type CSV"
    assert record["source_version"] == SCHEMA and record["edition"] == "Retail"
    assert record["profile"] == "profile-a"
    assert record["coverage"] == {"scope_alias": "all-monitored", "period_verified": False,
                                  "row_kind": "Category aggregates, not transactions", "categories_present": 5}
    assert record["payload"]["totals"]["net_cash_copper"] == 2695678
    assert record["payload"]["period"]["start"] == "2026-10-08T00:00:00+00:00"
    gaps = " ".join(data["gaps"])
    assert "not economic profit" in gaps and "never treat them as confirmed zero" in gaps.lower()
    assert "Transfers, refunds" in gaps and "running ledger" in gaps
    assert "net cash movement" in packet["instructions"] and "hourly rates" in packet["instructions"]
    assert "never instructions" in packet["instructions"]
    serialized = json.dumps(packet, ensure_ascii=False)
    assert ",2500000,-150000" not in serialized and ",80000,0" not in serialized
    preview = packet_preview(packet)
    assert "Session economy analysis · Retail" in preview and "net_cash_copper" in preview
    assert "missing_categories" in preview and "Looting" in preview


def test_one_period_mode_ignores_an_invalid_earlier_export():
    packet = prepare_economy(form(previous_csv="not,a,summary", previous_start="", previous_end=""))
    assert packet["reports"]["economy"]["data"]["comparison"] is None


def test_transfers_and_refunds_stay_aggregate():
    body = summary('"Mail",700000,-700000,0', '"Auction House",10000,-10000,0')
    record = prepare_economy(form(csv=body))["reports"]["economy"]["data"]["current"]
    assert record["payload"]["totals"] == {"incoming_copper": 710000, "outgoing_copper": -710000, "net_cash_copper": 0}
    assert any("cannot be separated" in warning for warning in record["warnings"])


@pytest.mark.parametrize("changes, message", [
    ({"edition": "Unknown"}, "edition"),
    ({"schema": "Journalator 170"}, "Confirm the addon versions"),
    ({"confirmed": "Not checked"}, "Confirm the addon versions"),
    ({"mode": "Sum all notes"}, "One period or Compare"),
    ({"profile": ""}, "profile alias"),
    ({"profile": "Testchar ExampleRealm"}, "short profile and filter aliases"),
    ({"scope": "all/monitored"}, "short profile and filter aliases"),
    ({"scope": "x" * 41}, "Filter scope alias"),
    ({"question": ""}, "Question or goal"),
    ({"csv": ""}, "Summary CSV"),
    ({"csv": fixture("transaction_layout.csv")}, "Unsupported CSV columns"),
    ({"start": ""}, "Period timestamp"),
], ids=["edition", "schema", "unconfirmed", "mode", "no-profile", "spaced-profile", "slash-scope",
        "long-scope", "question", "no-csv", "transactions", "no-period"])
def test_invalid_review_forms_are_refused(changes, message):
    with pytest.raises(ChatError, match=message):
        prepare_economy(form(**changes))


# --- Earlier-period comparison --------------------------------------------------

def test_comparison_reports_integer_deltas_for_one_declared_scope():
    packet = prepare_economy(form(mode=MODES[1]))
    data = packet["reports"]["economy"]["data"]
    assert data["comparison"]["totals_delta_copper"] == {
        "incoming_copper": 3073333, "outgoing_copper": -435000, "net_cash_copper": 2638333}
    current, previous = data["current"], data["previous"]
    for key in ("profile", "edition", "source_version"):
        assert current[key] == previous[key]
    assert current["coverage"]["scope_alias"] == previous["coverage"]["scope_alias"] == "all-monitored"
    assert "not independently verified" in data["comparison"]["scope"]
    assert "No rates" in data["comparison"]["limits"] and "missing-as-zero" in data["comparison"]["limits"]
    assert previous["payload"]["missing_categories"] != current["payload"]["missing_categories"]


def test_comparison_accepts_disjoint_periods_across_time_zones():
    data = prepare_economy(form(mode=MODES[1], previous_end="2026-10-08T01:00:00+02:00"))["reports"]["economy"]["data"]
    assert data["previous"]["payload"]["period"]["end"] == "2026-10-07T23:00:00+00:00"


@pytest.mark.parametrize("changes, message", [
    ({"previous_end": "2026-10-08T00:00:00Z"}, "strictly before"),
    ({"previous_end": "2026-10-07T20:00:00-05:00"}, "strictly before"),
    ({"previous_end": "2026-10-10T00:00:00Z"}, "strictly before"),
    ({"previous_start": "2026-10-16T00:00:00Z", "previous_end": "2026-10-20T00:00:00Z"}, "strictly before"),
    ({"previous_start": "2026-10-08T00:00:00Z", "previous_end": "2026-10-15T00:00:00Z"}, "strictly before"),
    ({"previous_csv": CURRENT}, "identical"),
    ({"previous_csv": "﻿" + CURRENT.replace('"', "").replace("\n", "\r\n")}, "identical"),
    ({"previous_csv": ""}, "Summary CSV"),
    ({"previous_csv": HEADER}, "not evidence of zero activity"),
    ({"previous_start": ""}, "Period timestamp"),
], ids=["shared-boundary", "offset-overlap", "overlap", "earlier-after-current", "same-period", "identical",
        "identical-reformatted", "missing-earlier", "empty-earlier", "missing-earlier-period"])
def test_comparison_refusals(changes, message):
    with pytest.raises(ChatError, match=message):
        prepare_economy(form(mode=MODES[1], **changes))

