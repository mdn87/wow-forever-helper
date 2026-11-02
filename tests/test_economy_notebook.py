"""Hidden-desktop UI checks for Session economy analysis with synthetic summaries only."""

from pathlib import Path

import pytest

from wow_helper.economy import MODES

from test_workspace import SESSIONS, Service, manager_factory, settle  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures" / "economy"


def fixture(name):
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith("# ")) + "\n"


def declare(dialog):
    dialog.fields["edition"].set("Retail")
    dialog.fields["profile"].set("profile-a")
    dialog.fields["scope"].set("all-monitored")
    dialog.fields["start"].set("2026-10-08T00:00:00Z")
    dialog.fields["end"].set("2026-10-15T00:00:00Z")


def import_file(dialog, monkeypatch, path, field="csv"):
    from tkinter import filedialog
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **_: str(path))
    dialog.import_csv(field)
    dialog.root.update()


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_economy_import_preview_send_once_save_and_restore(manager_factory, tmp_path, monkeypatch, provider):
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(next(s for s in SESSIONS if s.provider == provider)); settle(view)
    view.editor.insert("1.0", "Keep economy chat draft")
    view.show_economy_notebook()
    dialog = view._notebooks["economy"]
    settle(view)
    assert not view.service.sent and not view.activity.calls
    assert str(dialog.send_button["state"]) == "disabled" and str(dialog.save_button["state"]) == "disabled"

    declare(dialog)
    dialog.fields["confirmed"].set("Checked")
    source = tmp_path / "synthetic-by-type.csv"
    source.write_bytes(b"\xef\xbb\xbf" + fixture("by_type_current.csv").replace("\n", "\r\n").encode("utf-8"))
    import_file(dialog, monkeypatch, source)
    assert '"Auction House",2500000' in dialog.editors["csv"].get("1.0", "end-1c")
    # A newly imported export must be re-confirmed before review.
    assert dialog.fields["confirmed"].get() == "Not checked" and not view.service.sent
    dialog.prepare()
    assert dialog.packet is None and "Confirm the addon versions" in dialog.notice.get()

    dialog.fields["confirmed"].set("Checked")
    dialog.prepare()
    assert dialog.packet is not None and not view.service.sent
    preview = dialog.preview.get("1.0", "end-1c")
    assert preview.startswith("DESTINATION\n" + view.session_title)
    assert "Session economy analysis · Retail" in preview and "net_cash_copper" in preview
    assert "2695678" in preview and "Looting" in preview and "profile-a" in preview
    assert ",2500000,-150000" not in preview  # raw CSV omitted from the agent context
    assert str(dialog.send_button["state"]) == "normal"

    dialog.send(); dialog.send(); settle(view)
    assert len(view.service.sent) == 1 and view.service.sent[0][0] == view.selection_key
    assert str(dialog.send_button["state"]) == "disabled"
    assert view.editor.get("1.0", "end-1c") == "Keep economy chat draft"
    dialog.save()
    entries = view.activity.journal(view.journal_id)["entries"]
    assert len(entries) == 1 and entries[0]["source"]["provider"] == provider
    evidence = entries[0]["evidence"]["text"]
    assert "net_cash_copper" in evidence and "all-monitored" in evidence and "User declaration" in evidence
    assert not view.activity.calls
    assert manager.save_layout()
    manager.close()

    restored = manager_factory()
    loaded = restored.windows[0].view
    loaded.show_economy_notebook()
    again = loaded._notebooks["economy"]
    settle(loaded)
    assert '"Auction House",2500000' in again.editors["csv"].get("1.0", "end-1c")
    assert again.fields["profile"].get() == "profile-a" and again.packet is None
    assert not loaded.service.sent


def test_economy_changed_inputs_failed_import_and_duplicate_comparison(manager_factory, tmp_path, monkeypatch):
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(SESSIONS[0]); settle(view)
    view.show_economy_notebook()
    dialog = view._notebooks["economy"]
    declare(dialog)
    current = fixture("by_type_current.csv")
    dialog.editors["csv"].insert("1.0", current)

    bad = tmp_path / "latin.csv"; bad.write_bytes('"Name","In","Out","Profit"\n"Quêsting",1,0,1\n'.encode("latin-1"))
    import_file(dialog, monkeypatch, bad)
    assert "UTF-8" in dialog.notice.get()
    assert dialog.editors["csv"].get("1.0", "end-1c") == current
    big = tmp_path / "big.csv"; big.write_bytes(b"x" * 64_001)
    import_file(dialog, monkeypatch, big)
    assert "64,000" in dialog.notice.get()
    assert dialog.editors["csv"].get("1.0", "end-1c") == current

    dialog.fields["confirmed"].set("Checked")
    dialog.prepare()
    assert dialog.packet is not None
    dialog.fields["scope"].set("other-filter")
    dialog.send(); dialog.save()
    assert "fresh review" in dialog.notice.get()
    assert not view.service.sent and not view.activity.journal(view.journal_id)["entries"]

    dialog.prepare()
    view._select_session(SESSIONS[1]); settle(view)
    dialog.send()
    assert "conversation changed" in dialog.notice.get() and not view.service.sent

    dialog.fields["mode"].set(MODES[1])
    dialog.fields["previous_start"].set("2026-10-01T00:00:00Z")
    dialog.fields["previous_end"].set("2026-10-07T23:59:59Z")
    dialog.editors["previous_csv"].insert("1.0", current)
    dialog.root.update()
    dialog.prepare()
    assert dialog.packet is None and "identical" in dialog.notice.get()
    dialog.editors["previous_csv"].delete("1.0", "end")
    dialog.editors["previous_csv"].insert("1.0", fixture("by_type_earlier.csv"))
    dialog.fields["previous_end"].set("2026-10-08T00:00:00Z")
    dialog.root.update()
    dialog.prepare()
    assert dialog.packet is None and "strictly before" in dialog.notice.get()
    dialog.fields["previous_end"].set("2026-10-07T23:59:59Z")
    dialog.prepare()
    assert dialog.packet is not None
    assert "totals_delta_copper" in dialog.preview.get("1.0", "end-1c")
    assert not view.service.sent
