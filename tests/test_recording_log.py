"""F19 stage-one store acceptance with synthetic logs, clocks and free space."""

import json
import os

import pytest

from wow_helper import recording_log
from wow_helper.chat import ChatError
from wow_helper.recording_log import (MAX_INDEX_BYTES, LogStore, StoragePolicy,
                                      next_state, volume_budget)

from recording_fakes import FakeCaptureRunner, FakeWriter, LogHarness, snapshot

MEDIA = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def harness(monkeypatch, tmp_path):
    return LogHarness(monkeypatch, tmp_path)


@pytest.mark.parametrize("state, kind, detail, expected", [
    (None, "created", {}, "ready"),
    ("ready", "started", {"source_available": True}, "recording"),
    ("ready", "started", {"source_available": False}, "unavailable"),
    ("paused", "resumed", {"source_available": True}, "recording"),
    ("recording", "paused", {}, "paused"),
    ("unavailable", "paused", {}, "paused"),
    ("ready", "stopped", {}, "stopped"),
    ("paused", "stopped", {}, "stopped"),
    ("recording", "source_unavailable", {}, "unavailable"),
    ("unavailable", "source_available", {}, "recording"),
    ("recording", "recovered", {}, "paused"),
    ("unavailable", "recovered", {}, "paused"),
    ("recording", "gap", {"reason": "missed_interval"}, "recording"),
    ("recording", "sample", {"media_id": MEDIA, "bytes": 1, "captured_at": None}, "recording"),
])
def test_next_state_accepts_explicit_transitions(state, kind, detail, expected):
    assert next_state(state, kind, detail) == expected


@pytest.mark.parametrize("state, kind, detail", [
    ("ready", "created", {}),
    (None, "started", {"source_available": True}),
    ("recording", "started", {"source_available": True}),
    ("ready", "started", {"source_available": 1}),
    ("ready", "started", {}),
    ("ready", "resumed", {"source_available": True}),
    ("ready", "paused", {}),
    ("paused", "paused", {}),
    ("stopped", "stopped", {}),
    ("stopped", "started", {"source_available": True}),
    ("stopped", "resumed", {"source_available": True}),
    ("paused", "source_available", {}),
    ("paused", "recovered", {}),
    ("ready", "recovered", {}),
    ("paused", "gap", {"reason": "missed_interval"}),
    ("recording", "gap", {"reason": "catch_up"}),
    ("paused", "sample", {"media_id": MEDIA, "bytes": 1, "captured_at": None}),
    ("recording", "sample", {"media_id": "not-a-uuid", "bytes": 1, "captured_at": None}),
    ("recording", "sample", {"media_id": MEDIA, "bytes": 0, "captured_at": None}),
    ("recording", "sample", {"media_id": MEDIA, "bytes": 8_000_001, "captured_at": None}),
    ("recording", "sample", {"media_id": MEDIA, "bytes": 1, "captured_at": -1}),
    ("recording", "sample", {"media_id": MEDIA, "bytes": 1, "captured_at": float("nan")}),
    ("recording", "sample", {"media_id": MEDIA, "bytes": 1}),
    ("recording", "replayed", {}),
    ("recording", "paused", {"reason": "user"}),
    ("recording", "paused", []),
])
def test_next_state_refuses_invalid_transitions(state, kind, detail):
    with pytest.raises(ValueError):
        next_state(state, kind, detail)


def test_volume_budget_counts_pending_reserve_and_projected_external_growth():
    budget = volume_budget(free_bytes=1_700, pending_bytes=100, reserve_bytes=1_000,
                           external_bytes_per_second=1, horizon_seconds=600)
    assert budget == {"free_bytes": 1_700, "pending_bytes": 100, "reserve_bytes": 1_000,
                      "projected_external_bytes": 600, "required_bytes": 1_700, "allowed": True}
    assert not volume_budget(free_bytes=1_699, pending_bytes=100, reserve_bytes=1_000,
                             external_bytes_per_second=1, horizon_seconds=600)["allowed"]
    for bad in ({"free_bytes": -1}, {"pending_bytes": 1.5}, {"reserve_bytes": True},
                {"horizon_seconds": 86_401}):
        arguments = {"free_bytes": 1, "pending_bytes": 1, "reserve_bytes": 1, **bad}
        with pytest.raises(ValueError):
            volume_budget(**arguments)


@pytest.mark.parametrize("fields", [
    {"max_log_bytes": MAX_INDEX_BYTES - 1}, {"reserve_bytes": -1},
    {"external_bytes_per_second": 1.5}, {"horizon_seconds": 86_401}, {"max_log_bytes": True},
])
def test_storage_policy_rejects_invalid_budgets(fields):
    with pytest.raises(ValueError):
        StoragePolicy(**fields)


def test_store_refuses_destinations_outside_the_project_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(recording_log, "ROOT", tmp_path / "project")
    outside = tmp_path / "bulk"
    with pytest.raises(ChatError, match="ignored runtime directory"):
        LogStore(outside, MEDIA, StoragePolicy(), create=True)
    assert not outside.exists()


def test_index_is_versioned_complete_and_leaves_no_temporary_files(harness):
    controller = harness.create()
    controller.start(source_available=True)
    log_id = controller.log_id
    controller.close()
    data = harness.index(log_id)
    assert data["version"] == 1 and data["id"] == log_id and data["state"] == "recording"
    assert [event["kind"] for event in data["events"]] == ["created", "started"]
    assert [event["seq"] for event in data["events"]] == [1, 2]
    assert sorted(path.name for path in harness.directory(log_id).iterdir()) == ["index.json", "owner.lock"]


def test_interrupted_index_write_keeps_the_previous_index_and_the_temporary_file(harness):
    controller = harness.create()
    log_id = controller.log_id
    before = (harness.directory(log_id) / "index.json").read_bytes()
    FakeWriter(controller._store, fail=lambda name: name == "index.json", stage="after_temp")
    with pytest.raises(ChatError):
        controller.start(source_available=True)
    assert (harness.directory(log_id) / "index.json").read_bytes() == before
    temporaries = list(harness.directory(log_id).glob("write-*.tmp"))
    assert len(temporaries) == 1
    assert json.loads(temporaries[0].read_bytes())["state"] == "recording"
    assert controller.status()["write_failed"] is True


def test_sample_commits_before_the_index_references_it(harness):
    controller = harness.create()
    controller.start(source_available=True)
    writer = FakeWriter(controller._store)
    assert FakeCaptureRunner(controller, [b"synthetic-sample"]).capture(captured_at=12.5)
    sample_name = writer.names[0]
    assert sample_name.startswith("sample-") and writer.names[1:] == ["index.json"]
    event = harness.index(controller.log_id)["events"][-1]
    assert event["kind"] == "sample" and sample_name == "sample-" + event["detail"]["media_id"] + ".bin"
    assert event["detail"] == {"media_id": event["detail"]["media_id"], "bytes": 16, "captured_at": 12.5}
    assert (harness.directory(controller.log_id) / sample_name).read_bytes() == b"synthetic-sample"
    controller.close()


def test_crash_between_sample_and_index_preserves_the_orphan_and_unfinished_write(harness):
    controller = harness.create()
    controller.start(source_available=True)
    log_id = controller.log_id
    FakeWriter(controller._store, fail=lambda name: name == "index.json", stage="after_temp")
    with pytest.raises(ChatError):
        FakeCaptureRunner(controller, [b"orphaned-sample"]).capture()
    controller.close()
    assert [event["kind"] for event in harness.index(log_id)["events"]] == ["created", "started"]
    preserved = {name: content for name, content in snapshot(harness.directory(log_id)).items()
                 if name.startswith(("sample-", "write-"))}
    assert len(preserved) == 2

    reopened = harness.open(log_id)
    assert reopened.recovery == {"complete_events": 2, "orphan_files": 1, "unfinished_writes": 1,
                                 "interrupted": True, "pause_saved": True}
    after = snapshot(harness.directory(log_id))
    assert {name: after[name] for name in preserved} == preserved
    # Recovery pauses; it never replays the orphaned capture into the index.
    assert [event["kind"] for event in reopened.events()] == ["created", "started", "recovered"]
    assert reopened.status()["state"] == "paused"
    reopened.close()


def build_log(harness, sample=b"abc"):
    controller = harness.create()
    controller.start(source_available=True)
    FakeCaptureRunner(controller, [sample]).capture()
    controller.pause()
    log_id = controller.log_id
    controller.close()
    return log_id


def rewrite(harness, log_id, change):
    path = harness.directory(log_id) / "index.json"
    data = json.loads(path.read_bytes())
    raw = change(data)
    path.write_bytes(raw if isinstance(raw, bytes) else json.dumps(data).encode())


def drop_sample(harness, log_id):
    next(harness.directory(log_id).glob("sample-*.bin")).unlink()


def resize_sample(harness, log_id):
    next(harness.directory(log_id).glob("sample-*.bin")).write_bytes(b"abcd")


def repeat_sample(data):
    sample = dict(data["events"][2], seq=4)
    later = [dict(event, seq=event["seq"] + 1) for event in data["events"][3:]]
    data["events"] = data["events"][:3] + [sample] + later


CORRUPTIONS = {
    "unknown_version": lambda h, i: rewrite(h, i, lambda d: d.update(version=2)),
    "string_version": lambda h, i: rewrite(h, i, lambda d: d.update(version="1")),
    "malformed_json": lambda h, i: rewrite(h, i, lambda d: b"{\"version\": 1,"),
    "duplicate_key": lambda h, i: rewrite(h, i, lambda d: json.dumps(d).replace(
        "{\"version\": 1", "{\"version\": 1, \"version\": 1", 1).encode()),
    "extra_field": lambda h, i: rewrite(h, i, lambda d: d.update(extra=True)),
    "state_mismatch": lambda h, i: rewrite(h, i, lambda d: d.update(state="recording")),
    "wrong_id": lambda h, i: rewrite(h, i, lambda d: d.update(id=MEDIA)),
    "no_events": lambda h, i: rewrite(h, i, lambda d: d.update(events=[])),
    "sequence_gap": lambda h, i: rewrite(h, i, lambda d: d["events"][1].update(seq=3)),
    "invalid_transition": lambda h, i: rewrite(h, i, lambda d: d["events"][1].update(kind="resumed")),
    "unknown_kind": lambda h, i: rewrite(h, i, lambda d: d["events"][3].update(kind="replayed")),
    "repeated_sample": lambda h, i: rewrite(h, i, repeat_sample),
    "missing_sample": drop_sample,
    "wrong_sized_sample": resize_sample,
    "missing_index": lambda h, i: (h.directory(i) / "index.json").unlink(),
    "unsupported_entry": lambda h, i: (h.directory(i) / "nested").mkdir(),
}


def test_valid_retained_log_reopens_without_changes(harness):
    log_id = build_log(harness)
    before = snapshot(harness.directory(log_id))
    controller = harness.open(log_id)
    assert controller.status()["state"] == "paused"
    assert controller.recovery["interrupted"] is False
    controller.close()
    assert snapshot(harness.directory(log_id)) == before


@pytest.mark.parametrize("corruption", sorted(CORRUPTIONS))
def test_damaged_or_unsupported_index_is_refused_and_never_overwritten(harness, corruption):
    log_id = build_log(harness)
    CORRUPTIONS[corruption](harness, log_id)
    before = snapshot(harness.directory(log_id))
    with pytest.raises(ChatError, match="Existing files are kept"):
        harness.open(log_id)
    assert snapshot(harness.directory(log_id)) == before
    # The refused controller released its lock; a second attempt reports the same.
    with pytest.raises(ChatError, match="Existing files are kept"):
        harness.open(log_id)


def test_file_link_inside_a_log_is_refused(harness):
    log_id = build_log(harness)
    target = harness.directory(log_id).parent / "outside.bin"
    target.write_bytes(b"x")
    try:
        os.symlink(target, harness.directory(log_id) / "linked.bin")
    except (OSError, NotImplementedError):
        pytest.skip("Creating symbolic links requires a privilege this account lacks")
    with pytest.raises(ChatError):
        harness.open(log_id)
    assert target.read_bytes() == b"x"


def test_log_budget_refuses_new_samples_without_evicting_existing_data(harness):
    controller = harness.create(StoragePolicy(max_log_bytes=MAX_INDEX_BYTES))
    controller.start(source_available=True)
    runner = FakeCaptureRunner(controller, [b"a" * 3_000_000, b"b" * 3_000_000])
    assert runner.capture()
    kept = snapshot(harness.directory(controller.log_id))
    with pytest.raises(ChatError, match="storage budget"):
        runner.capture()
    assert snapshot(harness.directory(controller.log_id)) == kept
    status = controller.status()
    assert status["write_failed"] is True and status["worker_pending"] is False
    with pytest.raises(ChatError, match="Close and reopen"):
        controller.begin_capture()
    controller.close()


def test_reopening_with_a_smaller_budget_refuses_and_keeps_files(harness):
    controller = harness.create(StoragePolicy(max_log_bytes=10_000_000))
    controller.start(source_available=True)
    runner = FakeCaptureRunner(controller, [b"a" * 3_000_000, b"b" * 3_000_000])
    assert runner.capture() and runner.capture()
    controller.pause()
    log_id = controller.log_id
    controller.close()
    before = snapshot(harness.directory(log_id))
    with pytest.raises(ChatError, match="exceeds the selected budget"):
        harness.open(log_id, StoragePolicy(max_log_bytes=MAX_INDEX_BYTES))
    assert snapshot(harness.directory(log_id)) == before
    harness.open(log_id, StoragePolicy(max_log_bytes=10_000_000)).close()


def test_disk_reserve_exhaustion_refuses_writes_and_keeps_the_index(harness):
    policy = StoragePolicy(reserve_bytes=1_000_000)
    controller = harness.create(policy)
    index = (harness.directory(controller.log_id) / "index.json").read_bytes()
    harness.space.free_bytes = 1_000_000 + 10
    with pytest.raises(ChatError, match="free-space reserve"):
        controller.start(source_available=True)
    assert (harness.directory(controller.log_id) / "index.json").read_bytes() == index
    assert controller.status()["write_failed"] is True
    assert not list(harness.directory(controller.log_id).glob("write-*.tmp"))
    controller.close()


def test_projected_external_growth_counts_against_the_volume(harness):
    policy = StoragePolicy(reserve_bytes=1_000, external_bytes_per_second=1_000, horizon_seconds=600)
    controller = harness.create(policy)
    harness.space.free_bytes = 1_000 + 600_000 + 100_000
    report = controller.storage_report()
    assert report["projected_external_bytes"] == 600_000 and report["allowed"] is True
    assert report["required_bytes"] == report["pending_bytes"] + 1_000 + 600_000
    harness.space.free_bytes = 1_000 + 600_000
    with pytest.raises(ChatError, match="free-space reserve"):
        controller.start(source_available=True)
    controller.close()


def test_storage_report_accounts_for_orphans_and_temporaries(harness):
    controller = harness.create()
    directory = harness.directory(controller.log_id)
    (directory / ("sample-" + MEDIA + ".bin")).write_bytes(b"12345")
    (directory / "write-synthetic.tmp").write_bytes(b"123")
    report = controller.storage_report()
    assert report["media_bytes"] == 5 and report["other_bytes"] >= 3
    assert report["file_count"] == 4
    assert report["total_bytes"] == report["index_bytes"] + report["media_bytes"] + report["other_bytes"]
    assert str(directory) not in json.dumps(report)
    controller.close()


def test_event_count_is_bounded(harness, monkeypatch):
    monkeypatch.setattr(recording_log, "MAX_EVENTS", 4)
    controller = harness.create()
    controller.start(source_available=True)
    controller.gap()
    controller.gap()
    with pytest.raises(ChatError, match="event limit"):
        controller.gap()
    assert len(harness.index(controller.log_id)["events"]) == 4
    controller.close()


def test_event_pages_are_bounded_copies(harness):
    controller = harness.create()
    controller.start(source_available=True)
    controller.gap()
    page = controller.events(after=1, limit=1)
    assert [event["kind"] for event in page] == ["started"]
    page[0]["kind"] = "tampered"
    assert controller.events(after=1, limit=1)[0]["kind"] == "started"
    for arguments in ({"limit": 0}, {"limit": 1001}, {"after": -1}, {"after": 1.0}):
        with pytest.raises(ChatError):
            controller.events(**arguments)
    assert len(controller.events(limit=1000)) == 3
    controller.close()
