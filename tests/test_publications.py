"""Synthetic F18 publication store checks: authorization, isolation, freezing and storage safety.

All notes, conversations and evidence are hand-written synthetic values. No provider,
game data or real account is involved; storage lives under pytest's tmp_path.
"""

import functools
import hashlib
import json
import os
import stat
import uuid

import pytest

from wow_helper import publications
from wow_helper.chat import ChatError
from wow_helper.journal import JournalService
from wow_helper.publications import UNAVAILABLE, PublicationService

T0 = 1_800_000_000.0
JOURNAL = str(uuid.UUID(int=0))
SESSION = str(uuid.UUID(int=2))
OTHER_SESSION = str(uuid.UUID(int=3))
NOTE = str(uuid.UUID(int=10))
EVIDENCE = {"text": "Synthetic quest snapshot for Testchar on ExampleRealm", "edition": "Classic",
            "prepared_at": T0 - 600, "snapshot_at": T0 - 900, "gaps": ["Capture time is approximate"]}


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class Env:
    def __init__(self, root):
        self.root = root
        self.storage = root / ".runtime" / "chat"
        self.clock = Clock()
        self.service = PublicationService(self.storage, clock=self.clock)
        self.journal = JournalService(self.storage)
        self.state = self.storage / "tool-publications.json"

    def note(self, note_id=NOTE, *, text="Synthetic advice for Testchar", provider="claude",
             session=SESSION, evidence=EVIDENCE, source=True):
        self.journal.add(JOURNAL, "Example", text, note_id,
                         source={"provider": provider, "session_id": session} if source else None,
                         evidence=dict(evidence) if evidence is not None else None)
        return note_id

    def grant(self, provider="claude", session=SESSION, hours=24):
        grant_id = self.service.create(provider, session, hours=hours)["grant_id"]
        return grant_id, self.token(grant_id)

    def descriptor_path(self, grant_id):
        return self.storage / "tool-access" / (grant_id + ".json")

    def token(self, grant_id):
        return json.loads(self.descriptor_path(grant_id).read_text("utf-8"))["env"]["WOW_HELPER_TOOL_TOKEN"]

    def raw_journal_edit(self, note_id, **changes):
        path = self.journal.path(JOURNAL)
        data = json.loads(path.read_text("utf-8"))
        for entry in data["entries"]:
            if entry["id"] == note_id:
                entry.update(changes)
        path.write_text(json.dumps(data), "utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(publications, "ROOT", tmp_path)
    return Env(tmp_path)


def test_storage_outside_ignored_runtime_is_refused(env, tmp_path):
    with pytest.raises(ChatError, match="ignored local runtime storage"):
        PublicationService(tmp_path / "elsewhere")
    with pytest.raises(ChatError, match="ignored local runtime storage"):
        PublicationService(tmp_path / ".runtime" / ".." / "escaped")


def test_create_stores_only_a_digest_and_publishes_nothing(env):
    result = env.service.create("claude", SESSION, hours=24)
    assert set(result) == {"grant_id", "status", "provider", "integration", "launch_descriptor"}
    assert result["status"] == "configuration_required" and result["integration"] == "unverified"
    grant_id = result["grant_id"]
    token = env.token(grant_id)
    raw_state = env.state.read_text("utf-8")
    assert token not in raw_state
    assert json.loads(raw_state)["grants"][grant_id]["secret_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in json.dumps(result) and SESSION not in json.dumps(result)
    status = env.service.status(grant_id)
    assert status["active"] is True and status["record_ids"] == []
    assert env.service.query(grant_id, token) == {"records": []}
    descriptor = env.service.private_setup(grant_id)
    assert descriptor["args"] == ["-m", "wow_helper", "published-tools", "serve", "--grant-id", grant_id]
    if os.name == "nt":
        assert descriptor["command"].lower().endswith("pythonw.exe")


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not meaningful on Windows")
def test_private_files_are_owner_only(env):
    grant_id, _ = env.grant()
    for path in (env.descriptor_path(grant_id), env.state):
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    assert stat.S_IMODE(env.descriptor_path(grant_id).parent.stat().st_mode) & 0o077 == 0


@pytest.mark.parametrize("provider,hours", [("other", 24), ("claude", 0), ("claude", 169), ("codex", 1.5)])
def test_create_rejects_unknown_provider_or_lifetime(env, provider, hours):
    with pytest.raises(ChatError, match="1 to 168 hours"):
        env.service.create(provider, SESSION, hours=hours)
    assert not env.state.exists()


def test_publication_requires_the_grants_exact_source_conversation(env):
    env.note()
    env.note(str(uuid.UUID(int=11)), session=OTHER_SESSION)
    env.note(str(uuid.UUID(int=12)), provider="codex")
    grant_id, token = env.grant()
    before = env.state.read_bytes()
    for note_id in (str(uuid.UUID(int=11)), str(uuid.UUID(int=12))):
        with pytest.raises(ChatError, match="does not match this grant"):
            env.service.publish(grant_id, JOURNAL, note_id)
    assert env.state.read_bytes() == before
    assert env.service.query(grant_id, token) == {"records": []}
    assert env.service.publish(grant_id, JOURNAL, NOTE)["status"] == "published"


def test_unreviewed_or_sourceless_notes_cannot_be_published(env):
    grant_id, _ = env.grant()
    env.note(str(uuid.UUID(int=20)), evidence=None)
    env.note(str(uuid.UUID(int=21)), source=False)
    with pytest.raises(ChatError, match="reviewed evidence"):
        env.service.publish(grant_id, JOURNAL, str(uuid.UUID(int=20)))
    with pytest.raises(ChatError, match="no saved source conversation"):
        env.service.publish(grant_id, JOURNAL, str(uuid.UUID(int=21)))
    with pytest.raises(ChatError, match="reviewed evidence"):
        env.service.publish(grant_id, JOURNAL, str(uuid.UUID(int=99)))
    assert env.service.status(grant_id)["record_ids"] == []


def test_raw_image_reference_is_omitted_and_recorded_as_a_gap(env):
    image = str(uuid.UUID(int=50)) + ".png"
    env.note(evidence={**EVIDENCE, "image": image})
    grant_id, token = env.grant()
    record_id = env.service.publish(grant_id, JOURNAL, NOTE)["record_id"]
    result = env.service.query(grant_id, token, record_id)
    assert "image" not in result["data"]["evidence"]
    assert image not in json.dumps(result) and image not in env.state.read_text("utf-8")
    assert any("image reference is omitted" in gap for gap in result["data"]["gaps"])


# Built at runtime so the repository's leak check does not flag these synthetic paths.
@pytest.mark.parametrize("leak", ["\\".join(["C:", "Users", "Testchar", "Documents", "notes.txt"]),
                                  "/".join(["", "home", "testchar", "notes.txt"]),
                                  "WTF/Account/000000000/SavedVariables"])
def test_identity_paths_are_refused_not_silently_edited(env, leak):
    env.note(evidence={**EVIDENCE, "text": "See " + leak})
    grant_id, _ = env.grant()
    before = env.state.read_bytes()
    with pytest.raises(ChatError, match="removed"):
        env.service.publish(grant_id, JOURNAL, NOTE)
    assert env.state.read_bytes() == before


def test_oversized_selection_is_refused_without_truncation(env):
    env.note(evidence={"text": "x" * 63_900})
    grant_id, _ = env.grant()
    with pytest.raises(ChatError, match="64,000 bytes"):
        env.service.publish(grant_id, JOURNAL, NOTE)
    assert env.service.status(grant_id)["record_ids"] == []


def test_records_are_isolated_per_grant_and_token(env):
    env.note()
    first, first_token = env.grant()
    second, second_token = env.grant()
    other, other_token = env.grant(session=OTHER_SESSION)
    first_record = env.service.publish(first, JOURNAL, NOTE)["record_id"]
    second_record = env.service.publish(second, JOURNAL, NOTE)["record_id"]
    assert first_record != second_record
    assert [r["record_id"] for r in env.service.query(first, first_token)["records"]] == [first_record]
    assert env.service.query(other, other_token) == {"records": []}
    for grant_id, token, record_id in ((first, first_token, second_record), (second, second_token, first_record),
                                       (other, other_token, first_record)):
        with pytest.raises(ChatError) as error:
            env.service.query(grant_id, token, record_id)
        assert str(error.value) == UNAVAILABLE
    # A valid token for one grant cannot select another grant's records.
    for grant_id, token in ((first, second_token), (second, first_token), (other, first_token)):
        with pytest.raises(ChatError, match=UNAVAILABLE):
            env.service.query(grant_id, token)
    # Removing one grant does not affect another grant of the same conversation.
    env.service.revoke(first)
    assert env.service.query(second, second_token, second_record)["record_id"] == second_record


@pytest.mark.parametrize("token", ["", None, 123, "short", "x" * 43, "x" * 101, "é" * 43])
def test_wrong_or_malformed_tokens_are_denied(env, token):
    env.note()
    grant_id, real = env.grant()
    env.service.publish(grant_id, JOURNAL, NOTE)
    with pytest.raises(ChatError, match=UNAVAILABLE):
        env.service.query(grant_id, token)
    with pytest.raises(ChatError, match=UNAVAILABLE):
        env.service.authorize(grant_id, token)
    with pytest.raises(ChatError, match=UNAVAILABLE):
        env.service.authorize(grant_id, real[:-1] + ("A" if real[-1] != "A" else "B"))


@pytest.mark.parametrize("record_id", ["../tool-access/x.json", "..\\..\\tool-publications.json", "", "*",
                                       "tool-publications.json", str(uuid.UUID(int=999)), 7, None])
def test_record_ids_cannot_reach_files_or_unpublished_data(env, record_id):
    env.note()
    grant_id, token = env.grant()
    env.service.publish(grant_id, JOURNAL, NOTE)
    if record_id is None:
        assert len(env.service.query(grant_id, token, None)["records"]) == 1
        return
    with pytest.raises(ChatError) as error:
        env.service.query(grant_id, token, record_id)
    assert "Synthetic" not in str(error.value)


@pytest.mark.parametrize("grant_id", ["../tool-publications", "", str(uuid.UUID(int=998))])
def test_unknown_or_malformed_grants_are_denied(env, grant_id):
    env.note()
    real, token = env.grant()
    env.service.publish(real, JOURNAL, NOTE)
    for call in (lambda: env.service.query(grant_id, token), lambda: env.service.authorize(grant_id, token),
                 lambda: env.service.private_setup(grant_id), lambda: env.service.revoke(grant_id),
                 lambda: env.service.status(grant_id)):
        with pytest.raises(ChatError):
            call()


def test_expired_grants_and_clock_before_creation_are_denied(env):
    env.note()
    grant_id, token = env.grant(hours=1)
    record_id = env.service.publish(grant_id, JOURNAL, NOTE)["record_id"]
    env.clock.now = T0 + 3600
    with pytest.raises(ChatError, match=UNAVAILABLE):
        env.service.query(grant_id, token, record_id)
    with pytest.raises(ChatError, match=UNAVAILABLE):
        env.service.private_setup(grant_id)
    with pytest.raises(ChatError, match=UNAVAILABLE):
        env.service.publish(grant_id, JOURNAL, NOTE)
    status = env.service.status(grant_id)
    assert status["active"] is False and status["record_ids"] == []
    [listed] = env.service.for_source("claude", SESSION)
    assert listed["state"] == "expired" and listed["records"][0]["state"] == "expired"
    # A reopened store (server restart) still denies it.
    restarted = PublicationService(env.storage, clock=env.clock)
    with pytest.raises(ChatError, match=UNAVAILABLE):
        restarted.authorize(grant_id, token)
    env.clock.now = T0 - 1
    with pytest.raises(ChatError, match=UNAVAILABLE):
        env.service.query(grant_id, token)
    assert env.service.for_source("claude", SESSION)[0]["state"] == "clock_uncertain"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, "now", 5_000_000_000])
def test_unusable_clock_refuses_instead_of_guessing(env, bad):
    grant_id, token = env.grant()
    env.clock.now = bad
    with pytest.raises(ChatError, match="clock"):
        env.service.query(grant_id, token)


def test_removed_records_and_grants_stop_future_access(env):
    env.note()
    env.note(str(uuid.UUID(int=11)), text="Second synthetic note")
    grant_id, token = env.grant()
    keep = env.service.publish(grant_id, JOURNAL, NOTE)["record_id"]
    drop = env.service.publish(grant_id, JOURNAL, str(uuid.UUID(int=11)))["record_id"]
    assert env.service.revoke(grant_id, drop) == {"status": "access_removed", "grant_id": grant_id, "record_id": drop}
    assert [r["record_id"] for r in env.service.query(grant_id, token)["records"]] == [keep]
    with pytest.raises(ChatError, match=UNAVAILABLE):
        env.service.query(grant_id, token, drop)
    assert env.service.status(grant_id)["record_ids"] == [keep]
    # Retained snapshots and Journal notes are kept.
    assert json.loads(env.state.read_text("utf-8"))["records"][drop]["revoked"] is True
    assert len(env.journal.load(JOURNAL)["entries"]) == 2
    # Republishing does not resurrect the removed record under its old ID.
    assert env.service.publish(grant_id, JOURNAL, str(uuid.UUID(int=11)))["record_id"] not in {drop, keep}
    env.service.revoke(grant_id)
    for call in (lambda: env.service.query(grant_id, token), lambda: env.service.query(grant_id, token, keep),
                 lambda: env.service.private_setup(grant_id), lambda: env.service.publish(grant_id, JOURNAL, NOTE)):
        with pytest.raises(ChatError, match=UNAVAILABLE):
            call()
    assert env.service.status(grant_id)["active"] is False


def test_record_removal_is_bound_to_its_grant(env):
    env.note()
    first, _ = env.grant()
    second, second_token = env.grant()
    record_id = env.service.publish(second, JOURNAL, NOTE)["record_id"]
    before = env.state.read_bytes()
    with pytest.raises(ChatError, match=UNAVAILABLE):
        env.service.revoke(first, record_id)
    with pytest.raises(ChatError, match=UNAVAILABLE):
        env.service.revoke(first, str(uuid.UUID(int=997)))
    assert env.state.read_bytes() == before
    assert env.service.query(second, second_token, record_id)["record_id"] == record_id


def test_stale_records_report_actual_ages(env):
    env.note()
    env.note(str(uuid.UUID(int=11)), evidence={"text": "Future-dated synthetic snapshot", "snapshot_at": T0 + 500})
    env.note(str(uuid.UUID(int=12)), evidence={"text": "Undated synthetic snapshot"})
    grant_id, token = env.grant(hours=168)
    dated = env.service.publish(grant_id, JOURNAL, NOTE)["record_id"]
    future = env.service.publish(grant_id, JOURNAL, str(uuid.UUID(int=11)))["record_id"]
    undated = env.service.publish(grant_id, JOURNAL, str(uuid.UUID(int=12)))["record_id"]
    env.clock.now = T0 + 86_400
    result = env.service.query(grant_id, token, dated)
    assert result["published_at"] == T0
    assert result["published_age_seconds"] == 86_400
    assert result["snapshot_age_seconds"] == 86_400 + 900
    assert result["prepared_age_seconds"] == 86_400 + 600
    assert result["clock_uncertain"] is False
    [listed] = env.service.for_source("claude", SESSION)
    by_id = {record["record_id"]: record for record in listed["records"]}
    assert by_id[dated]["published_age_seconds"] == 86_400 and by_id[dated]["snapshot_age_seconds"] == 86_400 + 900
    env.clock.now = T0 + 100
    result = env.service.query(grant_id, token, future)
    assert result["snapshot_age_seconds"] is None and result["clock_uncertain"] is True
    result = env.service.query(grant_id, token, undated)
    assert result["snapshot_age_seconds"] is None and result["prepared_age_seconds"] is None
    assert result["published_age_seconds"] == 100 and result["clock_uncertain"] is False


def test_local_refresh_never_republishes_and_published_records_stay_frozen(env):
    env.note()
    grant_id, token = env.grant()
    first = env.service.publish(grant_id, JOURNAL, NOTE)
    before = env.state.read_bytes()
    env.clock.now = T0 + 300
    env.service.for_source("claude", SESSION)
    env.service.status(grant_id)
    env.service.review(JOURNAL, NOTE)
    env.service.query(grant_id, token)
    env.service.query(grant_id, token, first["record_id"])
    env.service.private_setup(grant_id)
    assert env.state.read_bytes() == before
    # Re-publishing an unchanged selection reuses the ID and its original publication time.
    assert env.service.publish(grant_id, JOURNAL, NOTE) == {"record_id": first["record_id"], "status": "already_published"}
    assert env.service.query(grant_id, token, first["record_id"])["published_at"] == T0
    # A later Journal change does not alter the frozen record.
    reviewed = env.service.review(JOURNAL, NOTE)
    env.raw_journal_edit(NOTE, text="Edited synthetic advice")
    assert env.service.query(grant_id, token, first["record_id"])["data"]["note"] == "Synthetic advice for Testchar"
    # A changed saved selection is refused until reviewed again.
    with pytest.raises(ChatError, match="Review it again"):
        env.service.publish(grant_id, JOURNAL, NOTE, expected=reviewed)
    assert len(env.service.query(grant_id, token)["records"]) == 1
    second = env.service.publish(grant_id, JOURNAL, NOTE, expected=env.service.review(JOURNAL, NOTE))
    assert second["status"] == "published" and second["record_id"] != first["record_id"]
    assert env.service.query(grant_id, token, second["record_id"])["data"]["note"] == "Edited synthetic advice"


def test_responses_carry_only_the_frozen_payload_and_metadata(env):
    env.note()
    grant_id, token = env.grant()
    record_id = env.service.publish(grant_id, JOURNAL, NOTE)["record_id"]
    listing = env.service.query(grant_id, token)
    assert listing == {"records": [{"record_id": record_id, "kind": "reviewed_journal_evidence", "published_at": T0}]}
    result = env.service.query(grant_id, token, record_id)
    assert set(result) == {"record_id", "published_at", "published_age_seconds", "snapshot_age_seconds",
                           "prepared_age_seconds", "clock_uncertain", "data"}
    text = json.dumps(result)
    for secret in (token, SESSION, JOURNAL, NOTE, grant_id, str(env.root)):
        assert secret not in text
    assert set(result["data"]) == {"version", "kind", "note", "evidence", "gaps"}
    assert any("untrusted data" in gap for gap in result["data"]["gaps"])
    # Mutating the returned copy cannot change the store.
    result["data"]["note"] = "tampered"
    assert env.service.query(grant_id, token, record_id)["data"]["note"] == "Synthetic advice for Testchar"


def test_private_setup_rejects_a_tampered_descriptor(env):
    grant_id, token = env.grant()
    path = env.descriptor_path(grant_id)
    original = json.loads(path.read_text("utf-8"))
    for change in ({"WOW_HELPER_TOOL_TOKEN": "y" * 43}, {"PYTHONPATH": "elsewhere"}):  # wrong token: generic refusal
        tampered = json.loads(json.dumps(original))
        tampered["env"].update(change)
        path.write_text(json.dumps(tampered), "utf-8")
        with pytest.raises(ChatError, match="does not match|unavailable"):
            env.service.private_setup(grant_id)
    tampered = dict(original, args=original["args"] + ["--extra"])
    path.write_text(json.dumps(tampered), "utf-8")
    with pytest.raises(ChatError, match="does not match"):
        env.service.private_setup(grant_id)
    path.write_text("{not json", "utf-8")
    with pytest.raises(ChatError, match="does not match"):
        env.service.private_setup(grant_id)
    path.unlink()
    with pytest.raises(ChatError, match="unavailable"):
        env.service.private_setup(grant_id)


def valid_state(env):
    env.note()
    grant_id, _ = env.grant()
    env.service.publish(grant_id, JOURNAL, NOTE)
    return json.loads(env.state.read_text("utf-8")), grant_id


def damage_cases():
    def version(data, _):
        data["version"] = 2

    def extra_key(data, _):
        data["extra"] = True

    def long_grant(data, grant_id):
        data["grants"][grant_id]["expires_at"] = data["grants"][grant_id]["created_at"] + 8 * 86400

    def orphan_record(data, _):
        next(iter(data["records"].values()))["grant_id"] = str(uuid.UUID(int=996))

    def image_payload(data, _):
        next(iter(data["records"].values()))["payload"]["evidence"]["image"] = str(uuid.UUID(int=50)) + ".png"

    def leaked_path(data, _):
        next(iter(data["records"].values()))["payload"]["note"] = "\\".join(["C:", "Users", "Testchar", "notes"])

    def bad_hash(data, grant_id):
        data["grants"][grant_id]["secret_hash"] = "Z" * 64

    def noncanonical_id(data, grant_id):
        data["grants"][grant_id.upper()] = data["grants"].pop(grant_id)

    return [version, extra_key, long_grant, orphan_record, image_payload, leaked_path, bad_hash, noncanonical_id]


@pytest.mark.parametrize("damage", damage_cases(), ids=lambda f: f.__name__)
def test_damaged_or_unsupported_state_is_refused_and_kept(env, damage):
    data, grant_id = valid_state(env)
    damage(data, grant_id)
    env.state.write_text(json.dumps(data), "utf-8")
    before = env.state.read_bytes()
    for call in (lambda: env.service.create("claude", SESSION), lambda: env.service.publish(grant_id, JOURNAL, NOTE),
                 lambda: env.service.revoke(grant_id), lambda: env.service.status(grant_id),
                 lambda: env.service.for_source("claude", SESSION)):
        with pytest.raises(ChatError, match="damaged or unsupported. Existing files are kept"):
            call()
    assert env.state.read_bytes() == before


@pytest.mark.parametrize("raw", [b"", b"{not json", b"[]", b'{"version":1,"version":1,"grants":{},"records":{}}',
                                 b"\xff\xfe", b"[" * 5000 + b"]" * 5000])
def test_unparseable_state_is_refused_and_kept(env, raw):
    env.state.parent.mkdir(parents=True)
    env.state.write_bytes(raw)
    with pytest.raises(ChatError, match="damaged or unsupported"):
        env.service.create("claude", SESSION)
    assert env.state.read_bytes() == raw


def test_oversized_state_is_refused_without_reading_it_all(env):
    env.state.parent.mkdir(parents=True)
    raw = b'{"version":1,"grants":{},"records":{},"pad":"' + b"x" * publications.MAX_STATE_BYTES + b'"}'
    env.state.write_bytes(raw)
    with pytest.raises(ChatError, match="damaged or unsupported"):
        env.service.status(str(uuid.UUID(int=1)))
    assert env.state.read_bytes() == raw


def test_failed_atomic_write_keeps_prior_state(env, monkeypatch):
    env.note()
    grant_id, token = env.grant()
    record_id = env.service.publish(grant_id, JOURNAL, NOTE)["record_id"]
    before = env.state.read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError("Synthetic disk failure")

    with monkeypatch.context() as patch:
        patch.setattr(publications.os, "replace", fail)
        with pytest.raises(ChatError, match="could not be saved. Existing records are kept"):
            env.service.revoke(grant_id)
    assert env.state.read_bytes() == before
    assert env.service.query(grant_id, token, record_id)["record_id"] == record_id


def test_concurrent_writer_is_refused_without_changes(env):
    from wow_helper.window_state import LayoutLock
    grant_id, _ = env.grant()
    before = env.state.read_bytes()
    lock = LayoutLock(env.state)
    try:
        with pytest.raises(ChatError, match="Another process"):
            env.service.revoke(grant_id)
    finally:
        lock.close()
    assert env.state.read_bytes() == before


def test_retention_limits_refuse_without_purging(env, monkeypatch):
    monkeypatch.setattr(publications, "MAX_GRANTS", 2)
    monkeypatch.setattr(publications, "MAX_PER_GRANT", 1)
    env.note()
    env.note(str(uuid.UUID(int=11)), text="Second synthetic note")
    grant_id, _ = env.grant()
    env.grant()
    before = env.state.read_bytes()
    with pytest.raises(ChatError, match="grant limit"):
        env.service.create("claude", SESSION)
    assert env.state.read_bytes() == before
    env.service.publish(grant_id, JOURNAL, NOTE)
    with pytest.raises(ChatError, match="publication limit"):
        env.service.publish(grant_id, JOURNAL, str(uuid.UUID(int=11)))
    env.service.revoke(grant_id)
    assert len(json.loads(env.state.read_text("utf-8"))["grants"]) == 2


def management_cli(env, monkeypatch, capsys, *argv):
    from wow_helper.__main__ import main
    monkeypatch.setattr(publications, "PublicationService", functools.partial(PublicationService, env.storage,
                                                                             clock=env.clock))
    code = main(["published-tools", *argv])
    return code, capsys.readouterr().out


def test_cli_management_output_omits_tokens_conversation_ids_and_paths(env, monkeypatch, capsys):
    env.note()
    code, out = management_cli(env, monkeypatch, capsys, "create", "--provider", "claude", "--session-id", SESSION)
    assert code == 0
    created = json.loads(out)
    grant_id = created["grant_id"]
    token = env.token(grant_id)
    descriptor = env.descriptor_path(grant_id)
    outputs = [out]
    code, out = management_cli(env, monkeypatch, capsys, "publish", "--grant-id", grant_id,
                               "--journal-id", JOURNAL, "--note-id", NOTE)
    assert code == 0 and json.loads(out)["status"] == "published"
    record_id = json.loads(out)["record_id"]
    outputs.append(out)
    code, out = management_cli(env, monkeypatch, capsys, "status", "--grant-id", grant_id)
    assert code == 0 and json.loads(out)["record_ids"] == [record_id]
    outputs.append(out)
    code, out = management_cli(env, monkeypatch, capsys, "revoke", "--grant-id", grant_id, "--record-id", record_id)
    assert code == 0 and json.loads(out)["status"] == "access_removed"
    outputs.append(out)
    code, out = management_cli(env, monkeypatch, capsys, "publish", "--grant-id", grant_id,
                               "--journal-id", JOURNAL, "--note-id", str(uuid.UUID(int=55)))
    assert code == 2 and json.loads(out)["status"] == "error"
    outputs.append(out)
    code, out = management_cli(env, monkeypatch, capsys, "status", "--grant-id", "../" + str(env.root))
    assert code == 2
    outputs.append(out)
    for out in outputs:
        for secret in (token, SESSION, str(env.root), str(descriptor), str(env.storage), "WOW_HELPER_TOOL_TOKEN",
                       "Synthetic advice", "Testchar"):
            assert secret not in out
        assert "Users" not in out and "\\" not in out


def test_cli_serve_without_a_valid_token_writes_nothing_to_stdout(env, monkeypatch, capsys):
    from wow_helper import published_tools
    from wow_helper.__main__ import main
    grant_id, token = env.grant()
    monkeypatch.setattr(published_tools, "PublicationService",
                        functools.partial(PublicationService, env.storage, clock=env.clock))
    monkeypatch.setenv(published_tools.TOKEN_ENV, "z" * 43)
    assert main(["published-tools", "serve", "--grant-id", grant_id]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "The tool grant or its authentication is unavailable.\n"
    monkeypatch.delenv(published_tools.TOKEN_ENV)
    assert main(["published-tools", "serve", "--grant-id", grant_id]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "The tool grant or its authentication is unavailable.\n"


def test_session_tools_returns_only_the_newest_active_grant_for_that_conversation(env):
    assert env.service.session_tools("claude", SESSION) is None
    older, _ = env.grant()
    env.clock.now = T0 + 60
    newer, token = env.grant()
    env.grant(session=OTHER_SESSION)
    env.grant(provider="codex")
    descriptor = env.service.session_tools("claude", SESSION)
    assert descriptor["args"][-1] == newer and descriptor["env"]["WOW_HELPER_TOOL_TOKEN"] == token
    env.service.revoke(newer)
    assert env.service.session_tools("claude", SESSION)["args"][-1] == older
    env.service.revoke(older)
    assert env.service.session_tools("claude", SESSION) is None


def test_session_tools_ignore_expired_grants_and_tampered_setup(env):
    grant_id, _ = env.grant(hours=1)
    env.clock.now = T0 + 3600
    assert env.service.session_tools("claude", SESSION) is None
    env.clock.now = T0
    env.descriptor_path(grant_id).write_text("{}", "utf-8")
    assert env.service.session_tools("claude", SESSION) is None
