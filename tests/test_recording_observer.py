"""recording-observe acceptance with synthetic files, a fake clock and a fake ffprobe."""

import json
import os
from types import SimpleNamespace

import pytest

from wow_helper import __main__ as cli
from wow_helper import recording_observer
from wow_helper.chat import ChatError
from wow_helper.recording_observer import RecordingObserver, observe, probe_format

from recording_fakes import (FakeClock, FakeProbe, FakeProbeProcess,
                             expected_window_options, snapshot)

SECRET_NAME = "Testchar-ExampleRealm-private"
PROBE_OUTPUT = json.dumps({"format": {"duration": "12.5", "tags": {"title": "SyntheticTagValue"}},
                           "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}).encode()


@pytest.fixture
def source(tmp_path):
    directory = tmp_path / "captures"
    directory.mkdir()
    return directory


def make_observer(source, clock, *, quiet=4, probe=False):
    return RecordingObserver(source, quiet_seconds=quiet, probe=probe, clock=clock.monotonic)


def grow(path, size):
    with path.open("ab") as stream:
        stream.write(b"\0" * size)


def no_private_detail(report, *secrets):
    text = json.dumps(report)
    for secret in secrets:
        assert str(secret) not in text
    assert "tags" not in text and "SyntheticTagValue" not in text


def test_growth_then_quiescent_candidate_with_injected_clock(source):
    clock = FakeClock()
    video = source / (SECRET_NAME + ".mp4")
    video.write_bytes(b"\0" * 1_000)
    (source / "notes.txt").write_bytes(b"ignored")
    observer = make_observer(source, clock)
    observer.poll()
    clock.advance(2)
    grow(video, 4_000)
    observer.poll()
    clock.advance(2)
    observer.poll()
    clock.advance(2)
    observer.poll()
    clock.advance(2)
    observer.poll()
    report = observer.report()
    [record] = report["files"]
    assert record["file_id"] == "recording-001"
    assert record["first_bytes"] == 1_000 and record["last_bytes"] == 5_000
    assert record["observed_growth_bytes"] == 4_000
    assert record["max_interval_bytes_per_second"] == 2_000
    assert record["state"] == "quiescent_candidate" and record["last_change_seconds"] == 2
    assert [event["state"] for event in report["events"]] == [
        "observed", "growing", "waiting_for_quiescence", "quiescent_candidate"]
    assert report["finalization"] == "unverified" and report["format_probe_enabled"] is False
    assert record["format_probe"] == {"status": "not_attempted"}
    no_private_detail(report, SECRET_NAME, source)


def test_aliases_are_ordered_and_removed_files_are_reported(source):
    clock = FakeClock()
    for name in ("b.mkv", "a.MOV", "c.mp4"):
        (source / name).write_bytes(b"x")
    observer = make_observer(source, clock)
    observer.poll()
    assert sorted(record["file_id"] for record in observer.records) == [
        "recording-001", "recording-002", "recording-003"]
    (source / "c.mp4").unlink()
    clock.advance(1)
    observer.poll()
    report = observer.report()
    assert report["events"][-1]["state"] == "removed_or_unreadable"
    no_private_detail(report, "b.mkv", "a.MOV", "c.mp4", source)
    assert RecordingObserver(source, clock=clock.monotonic).report()["files"] == []


def test_replaced_file_receives_a_new_alias(source):
    clock = FakeClock()
    video = source / "a.mp4"
    video.write_bytes(b"first")
    observer = make_observer(source, clock)
    observer.poll()
    # Create the replacement while the original exists; deleting first lets Linux reuse the inode.
    replacement = source / "other.mp4"
    replacement.write_bytes(b"second-file")
    os.replace(replacement, video)
    clock.advance(1)
    observer.poll()
    states = [(event["file_id"], event["state"]) for event in observer.report()["events"]]
    assert states == [("recording-001", "observed"), ("recording-001", "replaced"),
                      ("recording-002", "observed")]


def test_observation_and_probe_never_modify_source_files(source, monkeypatch):
    clock = FakeClock()
    (source / "a.mp4").write_bytes(b"synthetic-a")
    (source / "b.mkv").write_bytes(b"synthetic-b")
    before = snapshot(source)
    probe = FakeProbe(FakeProbeProcess(PROBE_OUTPUT), FakeProbeProcess(PROBE_OUTPUT))
    monkeypatch.setattr(recording_observer.subprocess, "Popen", probe)
    observer = make_observer(source, clock, probe=True)
    observer.executable = "ffprobe-synthetic"
    for _ in range(4):
        observer.poll()
        clock.advance(2)
    assert len(probe.calls) == 2
    assert snapshot(source) == before
    assert sorted(path.name for path in source.iterdir()) == ["a.mp4", "b.mkv"]


def test_format_probe_runs_only_after_quiescence_and_only_when_permitted(source, monkeypatch):
    clock = FakeClock()
    video = source / "a.mp4"
    video.write_bytes(b"\0" * 10)
    probe = FakeProbe(FakeProbeProcess(PROBE_OUTPUT))
    monkeypatch.setattr(recording_observer.subprocess, "Popen", probe)

    disabled = make_observer(source, clock, probe=False)
    disabled.executable = "ffprobe-synthetic"  # even when present, not permitted
    for _ in range(4):
        disabled.poll()
        clock.advance(2)
    assert probe.calls == [] and disabled.report()["probe_attempts"] == 0

    observer = make_observer(source, clock, probe=True)
    observer.executable = "ffprobe-synthetic"
    observer.poll()
    clock.advance(2)
    grow(video, 10)
    observer.poll()
    clock.advance(2)
    observer.poll()
    assert probe.calls == []  # growing / waiting: no probe
    clock.advance(2)
    observer.poll()
    assert len(probe.calls) == 1
    command, options = probe.calls[0]
    assert command[0] == "ffprobe-synthetic" and command[-1] == str(video)
    assert command[command.index("-protocol_whitelist") + 1] == "file"
    assert command[command.index("-format_whitelist") + 1] == "mov,matroska"
    assert "-show_entries" in command and "format=duration:stream=codec_type" in command
    assert options["stdin"] == recording_observer.subprocess.DEVNULL
    window = {key: value for key, value in options.items() if key == "creationflags"}
    assert window == expected_window_options()
    # Unchanged signature: one attempt only.
    clock.advance(2)
    observer.poll()
    assert len(probe.calls) == 1
    report = observer.report()
    assert report["files"][0]["format_probe"] == {
        "status": "metadata_readable", "finalization": "unverified",
        "duration_seconds": 12.5, "video_stream": True}
    assert report["format_probes"][0]["file_id"] == "recording-001"
    assert report["format_probes"][0]["result"]["finalization"] == "unverified"
    assert report["finalization"] == "unverified"
    no_private_detail(report, "a.mp4", source)


def test_missing_ffprobe_reports_unavailable_without_starting_a_process(source, monkeypatch):
    clock = FakeClock()
    (source / "a.mp4").write_bytes(b"x")
    monkeypatch.setattr(recording_observer.shutil, "which", lambda name: None)
    probe = FakeProbe()
    monkeypatch.setattr(recording_observer.subprocess, "Popen", probe)
    observer = make_observer(source, clock, probe=True)
    for _ in range(4):
        observer.poll()
        clock.advance(2)
    report = observer.report()
    assert probe.calls == []
    assert report["format_probe_available"] is False
    assert report["files"][0]["format_probe"] == {"status": "unavailable", "finalization": "unverified"}


def test_probe_lookup_happens_only_when_permitted(source, monkeypatch):
    looked_up = []
    monkeypatch.setattr(recording_observer.shutil, "which", lambda name: looked_up.append(name))
    RecordingObserver(source, probe=False)
    assert looked_up == []
    RecordingObserver(source, probe=True)
    assert looked_up == ["ffprobe"]


def expected_status(path, process, monkeypatch):
    monkeypatch.setattr(recording_observer.subprocess, "Popen", FakeProbe(process))
    expected = recording_observer.fingerprint(recording_observer.regular_stat(path))
    return probe_format(path, expected, timeout=3, executable="ffprobe-synthetic")


@pytest.mark.parametrize("process, status", [
    (FakeProbeProcess(b"{}", returncode=1), "unreadable"),
    (FakeProbeProcess(b"not json"), "unreadable"),
    (FakeProbeProcess(b"{\"format\": {}}"), "unreadable"),
    (FakeProbeProcess(b"x" * (recording_observer.MAX_PROBE_OUTPUT + 1)), "output_limit_or_unavailable"),
    (FakeProbeProcess(hang=True), "timeout"),
])
def test_probe_failures_produce_fixed_statuses(source, monkeypatch, process, status):
    video = source / "a.mp4"
    video.write_bytes(b"x")
    result = expected_status(video, process, monkeypatch)
    assert result == {"status": status, "finalization": "unverified"}


def test_probe_detects_changes_before_and_during_the_probe(source, monkeypatch):
    video = source / "a.mp4"
    video.write_bytes(b"x")
    process = FakeProbeProcess(PROBE_OUTPUT, on_wait=lambda: grow(video, 5))
    assert expected_status(video, process, monkeypatch)["status"] == "changed_during_probe"
    stale = recording_observer.fingerprint(recording_observer.regular_stat(video))
    grow(video, 5)
    probe = FakeProbe()
    monkeypatch.setattr(recording_observer.subprocess, "Popen", probe)
    assert probe_format(video, stale, timeout=3, executable="ffprobe-synthetic")["status"] == "changed_before_probe"
    assert probe.calls == []
    assert probe_format(video, stale, timeout=3, executable=None) == {
        "status": "unavailable", "finalization": "unverified"}


def test_probe_launch_failure_is_reported_as_unavailable(source, monkeypatch):
    video = source / "a.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(recording_observer.subprocess, "Popen", FakeProbe())  # raises OSError
    expected = recording_observer.fingerprint(recording_observer.regular_stat(video))
    assert probe_format(video, expected, timeout=3, executable="missing")["status"] == "unavailable"


def test_probe_attempts_are_bounded_per_invocation(source, monkeypatch):
    clock = FakeClock()
    for index in range(recording_observer.MAX_PROBES + 2):
        (source / f"{index:02}.mp4").write_bytes(b"x")
    probe = FakeProbe(*[FakeProbeProcess(PROBE_OUTPUT) for _ in range(20)])
    monkeypatch.setattr(recording_observer.subprocess, "Popen", probe)
    observer = make_observer(source, clock, probe=True)
    observer.executable = "ffprobe-synthetic"
    for _ in range(5):
        observer.poll()
        clock.advance(2)
    assert len(probe.calls) == recording_observer.MAX_PROBES
    assert observer.report()["probe_attempts"] == recording_observer.MAX_PROBES


def test_probe_worker_that_does_not_exit_stops_observation(source, monkeypatch):
    clock = FakeClock()
    (source / "a.mp4").write_bytes(b"x")
    (source / "b.mp4").write_bytes(b"x")

    class Stuck(FakeProbeProcess):
        def wait(self, timeout=None):
            raise recording_observer.subprocess.TimeoutExpired("ffprobe", timeout)

    probe = FakeProbe(Stuck(), Stuck())
    monkeypatch.setattr(recording_observer.subprocess, "Popen", probe)
    observer = make_observer(source, clock, probe=True)
    observer.executable = "ffprobe-synthetic"
    for _ in range(4):
        observer.poll()
        clock.advance(2)
    assert len(probe.calls) == 1
    report = observer.report()
    assert report["finished_reason"] == "probe_worker_not_exited" and report["status"] == "partial"


def test_file_entry_and_event_limits_are_bounded(source, monkeypatch):
    clock = FakeClock()
    for index in range(recording_observer.MAX_FILES + 1):
        (source / f"{index:03}.mp4").write_bytes(b"x")
    observer = make_observer(source, clock)
    observer.poll()
    report = observer.report()
    assert report["finished_reason"] == "file_limit" and report["status"] == "partial"
    assert len(report["files"]) == recording_observer.MAX_FILES
    observer.poll()  # a finished observer does not poll again
    assert observer.polls == 1

    monkeypatch.setattr(recording_observer, "MAX_ENTRIES", 3)
    limited = make_observer(source, clock)
    limited.poll()
    assert limited.report()["finished_reason"] == "directory_entry_limit"

    monkeypatch.setattr(recording_observer, "MAX_ENTRIES", 2048)
    monkeypatch.setattr(recording_observer, "MAX_EVENTS", 5)
    dropped = make_observer(source, clock)
    monkeypatch.setattr(recording_observer, "MAX_FILES", 10)
    dropped.poll()
    report = dropped.report()
    assert len(report["events"]) == 5 and report["dropped_events"] == 5
    assert len(report["files"]) == 10


def test_directory_replacement_and_removal_stop_observation(source, tmp_path):
    clock = FakeClock()
    observer = make_observer(source, clock)
    observer.poll()
    source.rename(tmp_path / "moved")
    source.mkdir()
    observer.poll()
    assert observer.report()["finished_reason"] == "directory_changed"
    other = make_observer(source, clock)
    source.rmdir()
    other.poll()
    assert other.report()["finished_reason"] in {"directory_unavailable", "directory_changed"}
    assert other.report()["status"] == "partial"


def test_directory_selection_and_quiet_period_are_validated(source, tmp_path):
    for bad in (tmp_path / "missing", source / "file.mp4"):
        with pytest.raises(ChatError, match="No source files were changed"):
            RecordingObserver(bad)
    if os.name == "nt":
        with pytest.raises(ChatError):
            RecordingObserver("\\\\server.invalid\\share")
    for quiet, probe in ((1, False), (301, False), (10, "yes")):
        with pytest.raises(ChatError):
            RecordingObserver(source, quiet_seconds=quiet, probe=probe)
    for arguments in ({"seconds": 0}, {"seconds": 3601}, {"interval": 0}, {"interval": 61},
                      {"interval": 6, "quiet_seconds": 10}):
        with pytest.raises(ChatError):
            observe(source, **arguments)


@pytest.fixture
def fake_time(monkeypatch):
    clock = FakeClock()
    original = RecordingObserver
    monkeypatch.setattr(recording_observer, "RecordingObserver",
                        lambda directory, **options: original(directory, clock=clock.monotonic, **options))
    monkeypatch.setattr(recording_observer, "time", SimpleNamespace(sleep=clock.sleep, monotonic=clock.monotonic))
    return clock


def run_cli(capsys, *args):
    code = cli.main(["recording-observe", *args])
    out = capsys.readouterr().out
    return code, out, json.loads(out)


def test_cli_reports_bounded_polling_without_names_or_paths(source, fake_time, capsys):
    video = source / (SECRET_NAME + ".mkv")
    video.write_bytes(b"\0" * 100)
    fake_time.on_sleep = lambda clock: grow(video, 50) if clock.mono <= 504 else None
    before_bytes = video.stat().st_size
    code, out, report = run_cli(capsys, "--directory", str(source), "--seconds", "12",
                                "--interval", "2", "--quiet-seconds", "4")
    assert code == 0
    assert report["status"] == "observed" and report["finished_reason"] == "duration_complete"
    assert report["finalization"] == "unverified" and report["format_probe_enabled"] is False
    assert report["polls"] == 6 and fake_time.sleeps == [2] * 6
    [record] = report["files"]
    assert record["file_id"] == "recording-001" and record["first_bytes"] == before_bytes
    assert record["observed_growth_bytes"] == 100 and record["state"] == "quiescent_candidate"
    assert SECRET_NAME not in out and ".mkv" not in out and str(source) not in out
    assert str(source).replace("\\", "\\\\") not in out and "captures" not in out


def test_cli_user_stop_returns_the_partial_report(source, fake_time, capsys):
    (source / "a.mp4").write_bytes(b"x")

    def interrupt(clock):
        raise KeyboardInterrupt

    fake_time.on_sleep = interrupt
    code, out, report = run_cli(capsys, "--directory", str(source), "--seconds", "60")
    assert code == 0 and report["finished_reason"] == "user_stopped" and report["polls"] == 1
    assert "a.mp4" not in out


def test_cli_limit_and_errors_omit_paths(source, fake_time, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(recording_observer, "MAX_FILES", 1)
    (source / "a.mp4").write_bytes(b"x")
    (source / "b.mp4").write_bytes(b"x")
    code, out, report = run_cli(capsys, "--directory", str(source), "--seconds", "10")
    assert code == 3 and report["status"] == "partial" and report["finished_reason"] == "file_limit"

    missing = tmp_path / "Testchar-missing"
    code, out, report = run_cli(capsys, "--directory", str(missing))
    assert code == 2 and report["status"] == "error"
    assert "Testchar" not in out and str(tmp_path) not in out
    code, out, report = run_cli(capsys, "--directory", str(source), "--interval", "5", "--quiet-seconds", "6")
    assert code == 2 and report["status"] == "error"


def test_cli_probe_flag_with_missing_ffprobe_keeps_finalization_unverified(source, fake_time,
                                                                              capsys, monkeypatch):
    (source / "a.mp4").write_bytes(b"x")
    monkeypatch.setattr(recording_observer.shutil, "which", lambda name: None)
    code, out, report = run_cli(capsys, "--directory", str(source), "--seconds", "10",
                                "--interval", "2", "--quiet-seconds", "4", "--probe-format")
    assert code == 0 and report["format_probe_enabled"] is True and report["format_probe_available"] is False
    assert report["files"][0]["format_probe"] == {"status": "unavailable", "finalization": "unverified"}
    assert report["finalization"] == "unverified" and "a.mp4" not in out
