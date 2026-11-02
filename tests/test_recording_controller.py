"""F19 stage-one lifecycle, ticket, ownership and recovery acceptance (synthetic)."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from wow_helper.chat import ChatError
from wow_helper.recording_log import MAX_SAMPLE_BYTES, StoragePolicy

from recording_fakes import (FakeCaptureRunner, FakeWriter, LogHarness,
                             expected_window_options, snapshot)

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def harness(monkeypatch, tmp_path):
    return LogHarness(monkeypatch, tmp_path)


def kinds(controller):
    return [event["kind"] for event in controller.events(limit=1000)]


def test_creation_is_ready_and_starts_no_capture(harness):
    with harness.create() as controller:
        status = controller.status()
        assert status["state"] == "ready" and status["last_confirmed_state"] == "ready"
        assert status["worker_pending"] is False and status["write_failed"] is False
        assert kinds(controller) == ["created"]
        with pytest.raises(ChatError, match="explicitly running"):
            controller.begin_capture()
        assert harness.samples(controller.log_id) == []


def test_explicit_lifecycle_transitions_and_refusals(harness):
    controller = harness.create()
    with pytest.raises(ChatError):
        controller.pause()
    with pytest.raises(ChatError):
        controller.resume(source_available=True)
    with pytest.raises(ChatError):
        controller.start(source_available="yes")
    assert controller.start(source_available=True)["state"] == "recording"
    with pytest.raises(ChatError, match="Only a ready log"):
        controller.start(source_available=True)
    assert controller.pause()["state"] == "paused"
    assert controller.pause()["state"] == "paused"  # idempotent, no second event
    # Source recovery cannot undo a deliberate pause.
    assert controller.source_changed(True)["state"] == "paused"
    assert controller.resume(source_available=False)["state"] == "unavailable"
    with pytest.raises(ChatError):
        controller.begin_capture()
    with pytest.raises(ChatError):
        controller.source_changed(1)
    assert controller.source_changed(True)["state"] == "recording"
    assert controller.source_changed(True)["state"] == "recording"
    assert controller.source_changed(False)["state"] == "unavailable"
    assert controller.stop()["state"] == "stopped"
    assert controller.stop()["state"] == "stopped"
    for refused in (lambda: controller.start(source_available=True),
                    lambda: controller.resume(source_available=True),
                    controller.pause, controller.begin_capture, controller.gap):
        with pytest.raises(ChatError):
            refused()
    assert kinds(controller) == ["created", "started", "paused", "resumed", "source_available",
                                 "source_unavailable", "stopped"]
    assert harness.index(controller.log_id)["state"] == "stopped"
    controller.close()
    with pytest.raises(ChatError, match="closed"):
        controller.stop()


def test_only_one_capture_ticket_is_outstanding(harness):
    with harness.create() as controller:
        controller.start(source_available=True)
        runner = FakeCaptureRunner(controller, [b"first", b"second"])
        runner.launch()
        assert controller.status()["worker_pending"] is True
        with pytest.raises(ChatError, match="has not exited"):
            controller.begin_capture()
        assert runner.exit() is True
        assert runner.capture() is True
        assert len(harness.samples(controller.log_id)) == 2
        assert controller.finish_capture(None) is False


@pytest.mark.parametrize("interruption", ["pause", "stop", "source_lost"])
def test_late_results_after_interruption_are_discarded_and_never_replayed(harness, interruption):
    controller = harness.create()
    controller.start(source_available=True)
    runner = FakeCaptureRunner(controller, [b"late-sample"])
    ticket = runner.launch()
    {"pause": controller.pause, "stop": controller.stop,
     "source_lost": lambda: controller.source_changed(False)}[interruption]()
    before = kinds(controller)
    assert controller.finish_capture(ticket, b"late-sample") is False
    assert controller.status()["worker_pending"] is False
    assert kinds(controller) == before
    assert harness.samples(controller.log_id) == []
    if interruption == "pause":
        controller.resume(source_available=True)
    elif interruption == "source_lost":
        controller.source_changed(True)
    if interruption != "stop":
        # Redelivering the stale ticket after recovery is still refused.
        assert controller.finish_capture(ticket, b"late-sample") is False
        assert FakeCaptureRunner(controller, [b"fresh"]).capture() is True
        assert len(harness.samples(controller.log_id)) == 1
    controller.close()


def test_failed_and_invalid_captures_record_gaps_without_samples(harness):
    with harness.create() as controller:
        controller.start(source_available=True)
        runner = FakeCaptureRunner(controller, [None, "text", b"", b"x" * (MAX_SAMPLE_BYTES + 1)])
        assert runner.capture() is False
        for _ in range(3):
            with pytest.raises(ChatError, match="recorded as a gap"):
                runner.capture()
        with pytest.raises(ChatError, match="recorded as a gap"):
            controller.finish_capture(controller.begin_capture(), b"ok", captured_at=-5)
        gaps = [event["detail"] for event in controller.events(limit=1000) if event["kind"] == "gap"]
        assert gaps == [{"reason": "capture_failed"}] * 5
        assert harness.samples(controller.log_id) == []
        controller.gap("missed_interval")
        with pytest.raises(ChatError):
            controller.gap("catch_up")
        assert controller.status()["worker_pending"] is False


def test_close_keeps_ownership_until_the_outstanding_worker_exits(harness):
    controller = harness.create()
    controller.start(source_available=True)
    runner = FakeCaptureRunner(controller, [b"after-close"])
    runner.launch()
    controller.close()
    with pytest.raises(ChatError, match="already open"):
        harness.open(controller.log_id)
    assert runner.exit() is False
    assert harness.samples(controller.log_id) == []
    with harness.open(controller.log_id) as reopened:
        assert reopened.status()["state"] == "paused"
        assert kinds(reopened) == ["created", "started", "recovered"]


def test_a_second_controller_cannot_own_an_open_log(harness):
    controller = harness.create()
    with pytest.raises(ChatError, match="already open"):
        harness.open(controller.log_id)
    controller.close()
    harness.open(controller.log_id).close()


def test_unknown_log_is_not_created_on_open(harness):
    missing = "00000000-0000-4000-8000-0000000000aa"
    with pytest.raises(ChatError, match="No new log was created"):
        harness.open(missing)
    assert not harness.directory(missing).exists()


CHILD = """
import sys
from pathlib import Path
from wow_helper import recording_log
from wow_helper.recording_controller import RecordingController
recording_log.ROOT = Path(sys.argv[1])
controller = RecordingController.create(root=Path(sys.argv[1]) / ".runtime" / "recording-logs",
                                        free_space=lambda path: 10**13)
controller.start(source_available=True)
ticket = controller.begin_capture()
controller.finish_capture(ticket, b"child-sample")
controller.begin_capture()  # a worker is outstanding when the process dies
print(controller.log_id, flush=True)
sys.stdin.read()
"""


def test_process_crash_releases_ownership_and_recovery_pauses_without_replay(harness, tmp_path):
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(tmp_path)], cwd=PROJECT,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             **expected_window_options())
    try:
        log_id = child.stdout.readline().decode().strip()
        assert log_id, "synthetic child did not create a log"
        with pytest.raises(ChatError, match="already open"):
            harness.open(log_id)
    finally:
        child.kill()
        child.wait(timeout=10)
        child.stdin.close()
        child.stdout.close()
    with harness.open(log_id) as recovered:
        status = recovered.status()
        assert status["state"] == "paused" and status["worker_pending"] is False
        assert status["recovery"]["interrupted"] is True and status["recovery"]["pause_saved"] is True
        assert kinds(recovered) == ["created", "started", "sample", "recovered"]
        assert len(harness.samples(log_id)) == 1
        with pytest.raises(ChatError):
            recovered.begin_capture()
        assert recovered.resume(source_available=True)["state"] == "recording"


def test_reopening_a_stopped_or_paused_log_adds_no_recovery_event(harness):
    for finish in ("stop", "pause"):
        controller = harness.create()
        controller.start(source_available=True)
        getattr(controller, finish)()
        log_id = controller.log_id
        controller.close()
        with harness.open(log_id) as reopened:
            assert reopened.recovery["interrupted"] is False
            assert reopened.recovery["pause_saved"] is None
            assert kinds(reopened)[-1] == ("stopped" if finish == "stop" else "paused")


def test_recovery_without_space_exposes_events_and_disables_writes(harness):
    policy = StoragePolicy(reserve_bytes=1_000_000)
    controller = harness.create(policy)
    controller.start(source_available=True)
    log_id = controller.log_id
    controller.close()
    before = snapshot(harness.directory(log_id))
    harness.space.free_bytes = 1_000_000
    with harness.open(log_id, policy) as reopened:
        status = reopened.status()
        assert status["recovery"]["pause_saved"] is False
        assert status["state"] == "paused" and status["last_confirmed_state"] == "recording"
        assert status["write_failed"] is True
        assert kinds(reopened) == ["created", "started"]
        for refused in (lambda: reopened.resume(source_available=True), reopened.begin_capture):
            with pytest.raises(ChatError):
                refused()
        stopped = reopened.stop()
        assert stopped["state"] == "stopped" and stopped["last_confirmed_state"] == "recording"
    assert snapshot(harness.directory(log_id)) == before


def test_uncertain_write_is_not_retried_and_reopen_reads_it_once(harness):
    controller = harness.create()
    controller.start(source_available=True)
    ticket = controller.begin_capture()
    FakeWriter(controller._store, fail=lambda name: name == "index.json", stage="after_replace")
    with pytest.raises(ChatError, match="close and reopen"):
        controller.gap()
    status = controller.status()
    assert status["write_failed"] is True and status["last_confirmed_state"] == "recording"
    assert controller.finish_capture(ticket, b"pending") is False
    assert harness.samples(controller.log_id) == []
    with pytest.raises(ChatError):
        controller.gap()
    assert controller.stop()["state"] == "stopped"
    log_id = controller.log_id
    controller.close()
    with harness.open(log_id) as reopened:
        assert kinds(reopened) == ["created", "started", "gap", "recovered"]


def test_wall_clock_adjustment_does_not_reorder_events(harness):
    controller = harness.create()
    harness.clock.advance(5)
    controller.start(source_available=True)
    harness.clock.wall -= 3_600
    harness.clock.mono += 1
    controller.gap()
    events = controller.events(limit=1000)
    assert [event["seq"] for event in events] == [1, 2, 3]
    assert events[2]["at"] < events[1]["at"]
    assert [event["elapsed"] for event in events] == [0, 5, 6]
    assert len({event["run_id"] for event in events}) == 1
    log_id = controller.log_id
    controller.pause()
    controller.close()
    with harness.open(log_id) as reopened:
        reopened.resume(source_available=True)
        events = reopened.events(limit=1000)
        assert events[-1]["run_id"] != events[0]["run_id"] and events[-1]["elapsed"] == 0


def test_status_and_events_contain_no_paths(harness, tmp_path):
    with harness.create() as controller:
        controller.start(source_available=True)
        FakeCaptureRunner(controller, [b"sample"]).capture(captured_at=1.0)
        text = json.dumps([controller.status(), controller.events(limit=1000)])
        assert str(tmp_path) not in text and os.sep + "recording-logs" not in text
