"""Synthetic post-fight notes; generated images and fake sessions only, no combat logs or Details! data."""

import inspect
import json

import pytest

from wow_helper import combat_coach
from wow_helper.chat import ChatError
from wow_helper.combat_coach import prepare_manual_coaching

# Hand-written synthetic text that merely looks like a combat-log line; it must stay opaque note text.
LOG_LIKE = '1/2 03:04:05.000  SPELL_DAMAGE,Player-0000-00000000,"Testchar-ExampleRealm",0x511,0x0,Creature-0,"Example boss"'


def form(**changes):
    values = dict(edition="Classic Forever beta", encounter="Example boss", phase="First attempt",
                  question="What should I improve before the next attempt?",
                  attempt_notes="Testchar stood in the synthetic fire during phase two.",
                  prior_notes="", event_time="", redact_terms="", image="")
    values.update(changes)
    return values


def test_first_attempt_packet_is_manual_notes_with_explicit_gaps(tmp_path):
    packet = prepare_manual_coaching(form(redact_terms="Testchar, ExampleRealm",
                                          attempt_notes="Testchar died.\n" + LOG_LIKE), tmp_path)
    assert set(packet["reports"]) == {"combat"}
    record = packet["reports"]["combat"]["data"]
    assert record["source_kind"] == "manual encounter notes" and record["edition"] == "Classic Forever beta"
    payload = record["payload"]
    assert set(payload) == {"encounter", "phase", "event_time", "attempt_notes", "earlier_attempt_notes",
                            "identity_replacements"}
    assert payload["earlier_attempt_notes"] is None and payload["event_time"] == "Unknown"
    # Combat-log-shaped text is neither parsed nor expanded into rows; only listed names are masked.
    assert payload["attempt_notes"].endswith(LOG_LIKE.replace("Testchar", "<redacted>").replace("ExampleRealm", "<redacted>"))
    assert "Testchar" not in json.dumps(packet) and "ExampleRealm" not in json.dumps(packet)
    assert payload["identity_replacements"] == {"listed word": 3}
    warnings = " ".join(record["warnings"])
    assert "no Details! export or structured combat log was parsed" in warnings
    assert "exact cause of death" in warnings and "Encounter time was not supplied" in warnings
    assert record["timestamps"]["captured"] == "Unknown"
    assert "Do not infer an exact death cause" in packet["instructions"]
    assert "Never send game input" in packet["instructions"]
    assert "image" not in packet


def test_later_attempt_includes_only_supplied_earlier_notes(tmp_path):
    with pytest.raises(ChatError, match="Earlier attempt notes are required"):
        prepare_manual_coaching(form(phase="Compare later attempt"), tmp_path)
    packet = prepare_manual_coaching(form(phase="Compare later attempt", event_time="2026-01-02 20:00 UTC",
                                          prior_notes="First try: stood in fire.",
                                          attempt_notes="Second try: moved out, died to adds."), tmp_path)
    payload = packet["reports"]["combat"]["data"]["payload"]
    assert payload["earlier_attempt_notes"] == "First try: stood in fire."
    assert payload["attempt_notes"] == "Second try: moved out, died to adds."
    assert payload["event_time"] == "2026-01-02 20:00 UTC"
    assert packet["reports"]["combat"]["data"]["timestamps"]["captured"] == "2026-01-02 20:00 UTC"
    assert "Encounter time was not supplied" not in " ".join(packet["reports"]["combat"]["data"]["warnings"])


@pytest.mark.parametrize("changes, message", [
    ({"edition": "Unknown"}, "edition"),
    ({"phase": "Automatic diagnosis"}, "First attempt or Compare later attempt"),
    ({"encounter": ""}, "Encounter"),
    ({"encounter": "x" * 201}, "Encounter"),
    ({"question": ""}, "Question"),
    ({"question": "x" * 2001}, "Question"),
    ({"attempt_notes": ""}, "Attempt notes"),
    ({"attempt_notes": "   "}, "Attempt notes"),
    ({"attempt_notes": "x" * 8001}, "Attempt notes"),
    ({"attempt_notes": "\U0001F3AE" * 2001}, "Attempt notes"),
    ({"attempt_notes": "bad\0byte"}, "Attempt notes"),
    ({"attempt_notes": None}, "Attempt notes"),
    ({"prior_notes": "x" * 8001}, "Earlier attempt notes"),
    ({"event_time": "x" * 101}, "Encounter time"),
    ({"redact_terms": ",".join(f"name{i}" for i in range(21))}, "at most 20 names"),
    ({"redact_terms": "x" * 101}, "at most 20 names"),
    ({"image": "00000000-0000-0000-0000-000000000000.png"}, "unavailable"),
    ({"image": "../outside.png"}, "image"),
], ids=["edition", "phase", "encounter-empty", "encounter-long", "question-empty", "question-long", "notes-empty",
        "notes-blank", "notes-long", "notes-bytes", "notes-nul", "notes-type", "prior-long", "time-long",
        "too-many-names", "long-name", "missing-image", "image-path"])
def test_malformed_or_oversized_notes_are_refused(tmp_path, changes, message):
    with pytest.raises(ChatError, match=message):
        prepare_manual_coaching(form(**changes), tmp_path)


def test_no_combat_log_or_details_reader_exists():
    source = inspect.getsource(combat_coach)
    for forbidden in ("WoWCombatLog", "SavedVariables", "savedvars", "Details_", "read_text(", "glob(", "subprocess"):
        assert forbidden not in source
    # The only file reads are the reviewed text importer (import_text) and image preview decoding.
    assert source.count("open(") == source.count("Image.open(") == 1


# Companion UI: Actions -> Post-fight coaching.

from test_workspace import SESSIONS, manager_factory, settle  # noqa: E402,F401


def png(tmp_path):
    from PIL import Image
    source = tmp_path / "synthetic-encounter.png"
    Image.new("RGB", (320, 160), "darkred").save(source)
    return source


def fill(dialog, notes):
    dialog.fields["encounter"].set("Example boss")
    dialog.editors["attempt_notes"].delete("1.0", "end")
    dialog.editors["attempt_notes"].insert("1.0", notes)
    dialog.root.update()


def sent(manager):
    return [item for window in manager.windows if window.view for item in window.view.service.sent]


def test_opening_coaching_sends_nothing_and_reads_no_reports(manager_factory):
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(SESSIONS[0]); settle(view)
    view.show_combat_coaching()
    dialog = view._notebooks["combat"]
    view.show_combat_coaching()
    assert view._notebooks["combat"] is dialog
    assert dialog.packet is None and str(dialog.send_button["state"]) == "disabled"
    assert str(dialog.save_button["state"]) == "disabled"
    assert not sent(manager) and not view.activity.calls
    assert not (view.activity.storage / "prepared").exists()


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_first_attempt_saved_sent_once_then_compared_only_in_same_conversation(manager_factory, tmp_path,
                                                                               monkeypatch, provider):
    from tkinter import filedialog
    original_session = next(s for s in SESSIONS if s.provider == provider)
    other_session = next(s for s in SESSIONS if s.provider != provider)
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(original_session); settle(view)
    view.editor.insert("1.0", "Keep this chat draft")
    view.show_combat_coaching()
    dialog = view._notebooks["combat"]
    fill(dialog, "Synthetic first attempt: stood in fire.")
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **_: str(png(tmp_path)))
    dialog.open_image()
    assert dialog.photo is not None and dialog.fields["image"].get().endswith(".png")
    assert not sent(manager)

    dialog.prepare()
    assert dialog.packet is not None, dialog.notice.get()
    preview = dialog.preview.get("1.0", "end-1c")
    assert "Synthetic first attempt" in preview and str(tmp_path) not in preview
    assert not sent(manager)
    dialog.send(); dialog.send()
    settle(view)
    assert len(sent(manager)) == 1 and sent(manager)[0][0] == original_session.key
    assert dialog.bound_source == {"source_provider": provider, "source_session": original_session.id}
    assert dialog.editors["prior_notes"].get("1.0", "end-1c") == "Synthetic first attempt: stood in fire."

    dialog.save()
    entries = view.activity.journal(view.journal_id)["entries"]
    assert len(entries) == 1, dialog.notice.get()
    assert entries[0]["source"] == {"provider": provider, "session_id": original_session.id}
    assert entries[0]["evidence"]["image"] == dialog.fields["image"].get()
    assert str(tmp_path) not in json.dumps(entries[0])
    assert "Synthetic first attempt" in entries[0]["evidence"]["text"]

    dialog.fields["phase"].set("Compare later attempt")
    fill(dialog, "Synthetic second attempt: moved out, died to adds.")
    view._select_session(other_session); settle(view)
    dialog.prepare()
    assert dialog.packet is None and "original coaching conversation" in dialog.notice.get()
    view._select_session(original_session); settle(view)
    dialog.prepare()
    assert dialog.packet is not None, dialog.notice.get()
    payload = dialog.packet["reports"]["combat"]["data"]["payload"]
    assert payload["earlier_attempt_notes"] == "Synthetic first attempt: stood in fire."
    assert payload["attempt_notes"] == "Synthetic second attempt: moved out, died to adds."
    dialog.send(); dialog.send()
    settle(view)
    assert len(sent(manager)) == 2 and all(key == original_session.key for key, _ in sent(manager))
    dialog.save()
    entries = view.activity.journal(view.journal_id)["entries"]
    assert len(entries) == 2 and "second attempt" in entries[1]["evidence"]["text"]
    assert view.editor.get("1.0", "end-1c") == "Keep this chat draft"


def test_save_then_send_first_attempt_uses_one_review(manager_factory):
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(SESSIONS[0]); settle(view)
    view.show_combat_coaching()
    dialog = view._notebooks["combat"]
    fill(dialog, "Synthetic attempt saved before sending.")
    dialog.prepare()
    dialog.save()
    dialog.root.update()
    assert len(view.activity.journal(view.journal_id)["entries"]) == 1
    assert "First attempt saved locally" in dialog.notice.get()
    dialog.send()
    settle(view)
    assert len(sent(manager)) == 1, dialog.notice.get()


def test_offline_first_attempt_saves_but_cannot_compare_without_a_conversation(manager_factory):
    manager = manager_factory()
    view = manager.windows[0].view
    assert view.selection_key is None
    view.show_combat_coaching()
    dialog = view._notebooks["combat"]
    fill(dialog, "Synthetic offline attempt.")
    dialog.prepare()
    assert str(dialog.send_button["state"]) == "disabled"
    dialog.save()
    entry = view.activity.journal(view.journal_id)["entries"][0]
    assert "source" not in entry and "image" not in entry["evidence"]
    dialog.fields["phase"].set("Compare later attempt")
    dialog.editors["prior_notes"].insert("1.0", "Typed earlier notes")
    dialog.prepare()
    assert dialog.packet is None and "Save or send the first attempt" in dialog.notice.get()
    assert not sent(manager)


def test_oversized_notes_in_window_are_refused_and_kept(manager_factory):
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(SESSIONS[0]); settle(view)
    view.show_combat_coaching()
    dialog = view._notebooks["combat"]
    fill(dialog, "x" * 8001)
    dialog.prepare()
    assert dialog.packet is None and "8,000" in dialog.notice.get()
    assert len(dialog.editors["attempt_notes"].get("1.0", "end-1c")) == 8001
    dialog.save(); dialog.send()
    assert not sent(manager) and not view.activity.journal(view.journal_id)["entries"]


def test_restart_keeps_first_attempt_binding_for_comparison(manager_factory):
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(SESSIONS[0]); settle(view)
    view.show_combat_coaching()
    dialog = view._notebooks["combat"]
    fill(dialog, "Synthetic attempt before restart.")
    dialog.prepare(); dialog.save()
    dialog.close()
    manager.save_layout()
    path = manager.layout_path
    manager.close()

    restored = manager_factory(path)
    view = restored.windows[0].view
    settle(view)
    view.show_combat_coaching()
    dialog = view._notebooks["combat"]
    assert not sent(restored)
    assert dialog.bound_source == {"source_provider": "codex", "source_session": SESSIONS[0].id}
    assert dialog.editors["prior_notes"].get("1.0", "end-1c") == "Synthetic attempt before restart."
    dialog.fields["phase"].set("Compare later attempt")
    fill(dialog, "Synthetic attempt after restart.")
    view._select_session(SESSIONS[1]); settle(view)
    dialog.prepare()
    assert dialog.packet is None and "original coaching conversation" in dialog.notice.get()
    view._select_session(SESSIONS[0]); settle(view)
    dialog.prepare(); dialog.send()
    settle(view)
    assert len(sent(restored)) == 1 and sent(restored)[0][0] == SESSIONS[0].key
