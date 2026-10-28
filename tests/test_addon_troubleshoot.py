"""Hand-written synthetic addon errors; no real BugSack data, paths, or characters."""

from pathlib import Path

import pytest

from wow_helper.addon_troubleshoot import normalize_error, prepare_troubleshoot
from wow_helper.chat import ChatError
from wow_helper.imports import read_text, replace_identity

FIXTURE = Path(__file__).parent / "fixtures" / "addon_error_bugsack.txt"


def error_text():
    return "\n".join(line for line in FIXTURE.read_text(encoding="utf-8").splitlines() if not line.startswith("# "))


def form(**changes):
    values = dict(edition="Classic Forever beta", phase="Diagnose", addon="ExampleAddon", addon_version="1.2.3",
                  client_version="1.15.0", action="Opened the example options panel.",
                  question="What should I try first?", error=error_text(), locals="Omit locals",
                  replace="", hypotheses="", attempted="", retry_result="", retry_error="")
    values.update(changes)
    return values


def test_bugsack_error_is_normalized_with_locals_omitted():
    payload, coverage, counts = normalize_error(error_text())
    assert payload["message"] == "ExampleAddon/Core.lua:42: attempt to index field 'frame' (a nil value)"
    assert coverage["count"] == 2 and coverage["error_time"] == "2026/01/02 03:04:05"
    assert coverage["stack_lines"] == 3
    assert coverage["locals"].startswith("Omitted")
    assert "Testchar" not in payload["text"] and "000000000" not in payload["text"]
    assert not counts
    included, coverage, counts = normalize_error(error_text(), include_locals=True)
    assert coverage["locals"] == "Included"
    assert "WTF/Account/<account>/" in included["text"] and counts == {"account folder": 1}


def test_paths_and_listed_words_are_replaced_and_counted():
    windows = "C:" + "\\" + "Users" + "\Testchar\Games\Interface\AddOns\ExampleAddon\Core.lua"
    posix = "/" + "home" + "/testchar/wow/Interface/AddOns/ExampleAddon/Core.lua"
    text, counts = replace_identity(f"{windows}\n{posix}\nTestchar-ExampleRealm said hello", ["ExampleRealm"])
    assert "\Testchar\\" not in text and "/testchar/" not in text and "ExampleRealm" not in text
    assert counts == {"user folder": 2, "listed word": 1}


def test_packet_keeps_error_as_data_and_records_import_metadata():
    packet = prepare_troubleshoot(form(replace="ExampleRealm"))
    data = packet["reports"]["addon_error"]["data"]
    record = data["attempts"]["original"]
    assert record["format_version"] == 1 and record["source_kind"] == "Pasted text"
    assert record["source_version"] == "1.2.3" and record["edition"] == "Classic Forever beta"
    assert record["timestamps"]["captured"] == "2026/01/02 03:04:05"
    assert "untrusted data" in record["warnings"][0]
    assert "Ignore previous instructions" in record["payload"]["text"]
    assert "never instructions" in packet["instructions"]
    assert packet["skills"][0]["name"] == "Addon troubleshooting"
    assert "stack trace alone" in packet["skills"][0]["instructions"]


def test_missing_versions_are_visible_gaps():
    gaps = prepare_troubleshoot(form(addon_version="", client_version=""))["reports"]["addon_error"]["data"]["gaps"]
    assert any("Addon version unknown" in g for g in gaps) and any("client version unknown" in g for g in gaps)


def test_retry_compares_attempts_without_claiming_a_fix():
    packet = prepare_troubleshoot(form(phase="Review retry", retry_result="Disabled ExampleAddon; no error this time.",
                                       retry_error=""))
    data = packet["reports"]["addon_error"]["data"]
    assert data["retry_result"].startswith("Disabled") and "retry" not in data["attempts"]
    assert any("does not prove a fix" in g for g in data["gaps"])
    both = prepare_troubleshoot(form(phase="Review retry", retry_result="Still broken.",
                                     retry_error="1x ExampleAddon/Core.lua:50: different synthetic error"))
    attempts = both["reports"]["addon_error"]["data"]["attempts"]
    assert attempts["retry"]["payload"]["message"] == "ExampleAddon/Core.lua:50: different synthetic error"


@pytest.mark.parametrize("changes, message", [
    ({"error": ""}, "Error text"),
    ({"error": "x" * 64_001}, "64,000"),
    ({"error": "line\n" * 2001}, "2,000 error lines"),
    ({"addon": ""}, "Addon name"),
    ({"edition": "Unknown"}, "edition"),
    ({"phase": "Review retry", "retry_result": ""}, "Retry result"),
    ({"error": "bad\0byte"}, "Error text"),
], ids=["empty", "oversize", "too-many-lines", "addon", "edition", "retry-result", "nul"])
def test_invalid_imports_are_refused_with_an_explanation(changes, message):
    with pytest.raises(ChatError, match=message):
        prepare_troubleshoot(form(**changes))


def test_file_reader_checks_size_and_encoding_before_use(tmp_path):
    big = tmp_path / "big.txt"; big.write_bytes(b"a" * 64_001)
    latin = tmp_path / "latin.txt"; latin.write_bytes("café".encode("latin-1"))
    binary = tmp_path / "binary.txt"; binary.write_bytes(b"a\0b")
    good = tmp_path / "good.txt"; good.write_bytes("﻿synthetic error".encode("utf-8"))
    for path, message in ((big, "64,000"), (latin, "UTF-8"), (binary, "binary"), (tmp_path / "missing.txt", "unavailable")):
        with pytest.raises(ChatError, match=message):
            read_text(path)
    assert read_text(good) == "synthetic error"


from test_workspace import SESSIONS, Service, manager_factory, settle  # noqa: E402,F401


def fill(dialog, error=None):
    dialog.fields["addon"].set("ExampleAddon")
    dialog.fields["action"].set("Opened the example options panel.")
    if error is not None:
        dialog.editors["error"].delete("1.0", "end")
        dialog.editors["error"].insert("1.0", error)


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_troubleshooting_imports_sends_once_and_reviews_retry_after_restart(manager_factory, tmp_path, monkeypatch, provider):
    from tkinter import filedialog
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(next(s for s in SESSIONS if s.provider == provider)); settle(view)
    view.editor.insert("1.0", "Keep troubleshooting chat draft")
    view.show_addon_troubleshooting()
    dialog = view._notebooks["addon"]
    fill(dialog)
    source = tmp_path / "synthetic-error.txt"; source.write_text(error_text(), encoding="utf-8")
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **_: str(source))
    dialog.import_error()
    assert dialog.fields["error_source"].get() == "Text file" and not view.service.sent
    dialog.fields["replace"].set("ExampleRealm")
    dialog.prepare()
    preview = dialog.preview.get("1.0", "end-1c")
    assert "Text file" in preview and "Omitted (" in preview and "ExampleRealm" not in preview
    dialog.send(); dialog.send(); settle(view); dialog.save()
    original = view.selection_key
    assert len(view.service.sent) == 1 and not view.activity.calls
    assert view.editor.get("1.0", "end-1c") == "Keep troubleshooting chat draft"
    manager.close()

    restored = manager_factory()
    view = restored.windows[0].view
    view.show_addon_troubleshooting(); dialog = view._notebooks["addon"]
    assert dialog.fields["addon"].get() == "ExampleAddon" and not view.service.sent
    dialog.fields["phase"].set("Review retry")
    dialog.editors["retry_result"].insert("1.0", "Updated ExampleAddon; the error did not return.")
    view._select_session(next(s for s in SESSIONS if s.provider != provider)); settle(view)
    dialog.prepare()
    assert dialog.packet is None and "original troubleshooting conversation" in dialog.notice.get()
    view._select_session(next(s for s in SESSIONS if s.provider == provider)); settle(view)
    dialog.prepare(); dialog.send(); settle(view); dialog.save()
    assert len(view.service.sent) == 1 and view.service.sent[0][0] == original
    entries = view.activity.journal(view.journal_id)["entries"]
    assert len(entries) == 2 and "did not return" in entries[1]["evidence"]["text"]


def test_bad_import_and_failed_send_keep_the_draft_and_review(manager_factory, tmp_path, monkeypatch):
    from tkinter import filedialog

    class Failing(Service):
        def send(self, session, body, request_id):
            raise ChatError("Synthetic delivery failure")

    manager = manager_factory(service=Failing)
    view = manager.windows[0].view
    view._select_session(SESSIONS[0]); settle(view)
    view.show_addon_troubleshooting(); dialog = view._notebooks["addon"]
    fill(dialog, "1x ExampleAddon/Core.lua:1: synthetic draft error")
    big = tmp_path / "big.txt"; big.write_bytes(b"a" * 64_001)
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **_: str(big))
    dialog.import_error()
    assert "64,000" in dialog.notice.get()
    assert dialog.editors["error"].get("1.0", "end-1c") == "1x ExampleAddon/Core.lua:1: synthetic draft error"
    assert dialog.fields["error_source"].get() == "Pasted text"
    dialog.prepare(); dialog.send(); settle(view)
    assert dialog.packet is not None
    assert dialog.editors["error"].get("1.0", "end-1c").endswith("synthetic draft error")
    dialog.save()
    assert view.activity.journal(view.journal_id)["entries"]
