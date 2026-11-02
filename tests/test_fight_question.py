"""Synthetic Ask-about-the-last-fight requests; the combat log reader is replaced by fakes here."""

import json
import time

import pytest

from wow_helper import combat_log
from wow_helper.chat import ChatError
from wow_helper.fight_question import prepare_fight_question

DIGEST = ("Example Boss (encounter 9999), wipe after 2:31\n"
          "Death 1: Player 2 at 1:12, killing blow Example Cleave (overkill)\n")


def form(**changes):
    values = dict(edition="Retail", question="Why did we wipe so fast?", digest=DIGEST,
                  digest_status="Last encounter read.", names="0")
    values.update(changes)
    return values


def test_packet_carries_question_digest_and_gaps():
    packet = prepare_fight_question(form())
    assert set(packet["reports"]) == {"fight"}
    record = packet["reports"]["fight"]["data"]
    assert record["source_kind"] == "combat log digest"
    assert record["payload"] == {"question": "Why did we wipe so fast?", "digest": DIGEST.strip()}
    assert "Last encounter read." in record["warnings"]
    assert "exact cause of death" in " ".join(record["warnings"])
    assert "Never send game" in packet["instructions"] and "raw log" in packet["instructions"]
    assert packet["task"] == "Why did we wipe so fast?"


def test_question_without_digest_is_labelled_question_only():
    record = prepare_fight_question(form(digest=""))["reports"]["fight"]["data"]
    assert record["source_kind"] == "question only" and record["payload"]["digest"] is None
    assert "No combat log digest was included." in record["warnings"]


@pytest.mark.parametrize("changes, message", [
    ({"edition": "Unknown"}, "edition"),
    ({"question": ""}, "Question"),
    ({"question": "x" * 4001}, "Question"),
    ({"digest": "x" * 24_001}, "Combat log digest"),
    ({"digest": "bad\0byte"}, "Combat log digest"),
])
def test_bad_requests_are_refused(changes, message):
    with pytest.raises(ChatError, match=message):
        prepare_fight_question(form(**changes))


from test_workspace import SESSIONS, manager_factory, settle  # noqa: E402,F401


def sent(manager):
    return [item for window in manager.windows if window.view for item in window.view.service.sent]


def fake_reader(monkeypatch, tmp_path, result=None, found=True):
    calls = []
    log = tmp_path / "WoWCombatLog-110426_200000.txt"
    log.write_text("# synthetic\n", encoding="utf-8")

    def find(roots, flavor):
        calls.append(("find", flavor))
        return log if found else None

    def digest(path, **options):
        calls.append(("digest", options))
        if isinstance(result, Exception):
            raise result
        return result or {"status": "ok", "text": DIGEST, "data": {}, "gaps": ["Synthetic gap."]}
    monkeypatch.setattr(combat_log, "find_combat_log", find)
    monkeypatch.setattr(combat_log, "last_encounter_digest", digest)
    return calls


def wait_read(dialog):
    deadline = time.monotonic() + 5
    while str(dialog.read_button["state"]) == "disabled" and time.monotonic() < deadline:
        dialog.root.update(); time.sleep(0.02)
    dialog.root.update()


def open_dialog(manager):
    view = manager.windows[0].view
    view._select_session(SESSIONS[0]); settle(view)
    view.show_fight_question()
    return view, view._notebooks["fight"]


def test_opening_reads_nothing_and_sends_nothing(manager_factory, monkeypatch, tmp_path):
    calls = fake_reader(monkeypatch, tmp_path)
    manager = manager_factory()
    view, dialog = open_dialog(manager)
    view.show_fight_question()
    assert view._notebooks["fight"] is dialog
    assert not calls and not sent(manager) and dialog.packet is None
    assert str(dialog.send_button["state"]) == "disabled"


def test_read_review_send_once_and_save(manager_factory, monkeypatch, tmp_path):
    calls = fake_reader(monkeypatch, tmp_path)
    manager = manager_factory()
    view, dialog = open_dialog(manager)
    view.editor.insert("1.0", "Keep this chat draft")
    dialog.editors["question"].insert("1.0", "Why did we wipe so fast?")
    dialog.fields["names"].set("1")
    dialog.own_name.set("Testchar")
    dialog.read_log(); wait_read(dialog)
    assert [c[0] for c in calls] == ["find", "digest"]
    assert calls[-1] == ("digest", {"include_names": True, "own_name": "Testchar"})
    assert dialog.editors["digest"].get("1.0", "end-1c") == DIGEST
    assert "Synthetic gap." in dialog.fields["digest_status"].get()
    assert "own_name" not in view.notebook_drafts["fight"] and "Testchar" not in json.dumps(view.notebook_drafts)
    assert not sent(manager)

    dialog.prepare()
    assert dialog.packet is not None, dialog.notice.get()
    assert "Example Cleave" in dialog.preview.get("1.0", "end-1c")
    dialog.send(); dialog.send(); settle(view)
    assert len(sent(manager)) == 1 and sent(manager)[0][0] == SESSIONS[0].key
    dialog.save()
    entries = view.activity.journal(view.journal_id)["entries"]
    assert len(entries) == 1 and "Example Cleave" in entries[0]["evidence"]["text"]
    assert "Testchar" not in json.dumps(entries)
    assert view.editor.get("1.0", "end-1c") == "Keep this chat draft"


def test_missing_log_and_read_errors_keep_the_draft(manager_factory, monkeypatch, tmp_path):
    fake_reader(monkeypatch, tmp_path, found=False)
    manager = manager_factory()
    view, dialog = open_dialog(manager)
    dialog.editors["question"].insert("1.0", "What killed us?")
    dialog.read_log()
    assert "No combat log was found" in dialog.notice.get()
    fake_reader(monkeypatch, tmp_path, result=ChatError("The combat log could not be read."))
    dialog.read_log(); wait_read(dialog)
    assert dialog.notice.get() == "The combat log could not be read."
    assert dialog.editors["question"].get("1.0", "end-1c") == "What killed us?"
    assert dialog.editors["digest"].get("1.0", "end-1c") == "" and not sent(manager)
    fake_reader(monkeypatch, tmp_path, result=ValueError("synthetic parser bug"))
    dialog.read_log(); wait_read(dialog)
    assert "could not be digested" in dialog.notice.get()
    assert str(dialog.read_button["state"]) == "normal"


def test_new_digest_or_name_choice_invalidates_the_review(manager_factory, monkeypatch, tmp_path):
    fake_reader(monkeypatch, tmp_path)
    manager = manager_factory()
    view, dialog = open_dialog(manager)
    dialog.editors["question"].insert("1.0", "Why did we wipe?")
    dialog.read_log(); wait_read(dialog)
    dialog.prepare()
    assert str(dialog.send_button["state"]) == "normal"
    dialog.fields["names"].set("1")
    assert str(dialog.send_button["state"]) == "disabled"
    dialog.prepare()
    dialog.remove_digest()
    assert str(dialog.send_button["state"]) == "disabled"
    dialog.send()
    assert not sent(manager)


def test_unsupported_layout_digest_is_labelled(manager_factory, monkeypatch, tmp_path):
    fake_reader(monkeypatch, tmp_path, result={"status": "unsupported_layout", "text": "No numbers.", "data": {},
                                               "gaps": ["Log version 99 is not recognised."]})
    manager = manager_factory()
    _, dialog = open_dialog(manager)
    dialog.read_log(); wait_read(dialog)
    assert "not recognised" in dialog.notice.get()
    assert "Log version 99" in dialog.fields["digest_status"].get()
