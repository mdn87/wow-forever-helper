"""Synthetic local counts; no personal usage or game content."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from wow_helper.chat import ChatError
from wow_helper.usage_study import UsageStudy


def test_disabled_by_default_and_only_allowlisted_counts(tmp_path):
    study = UsageStudy(tmp_path, clock=lambda: 1000)
    assert study.report()["status"] == "not_started"
    assert not study.hit("chat", "send")
    assert not study.path.exists()
    study.start(7)
    for feature, action in [("Synthetic private content", "open"), ("chat", "Synthetic content"), ([], "open")]:
        assert not study.hit(feature, action)
    assert study.hit("chat", "send")
    raw = study.path.read_text()
    assert "Synthetic" not in raw
    assert study.report()["totals"] == {"chat": {"send": 1}}


def test_expiry_stop_restart_and_report_do_not_extend_study(tmp_path):
    now = [1000]
    study = UsageStudy(tmp_path, clock=lambda: now[0])
    first = study.start(3)
    study.hit("goals", "open")
    now[0] += 86400
    assert study.start(14)["ends_at"] == first["ends_at"]
    study.hit("goals", "open")
    assert len(study.report()["days_used"]["goals"]) == 2
    restored = UsageStudy(tmp_path, clock=lambda: now[0])
    before = restored.path.read_bytes()
    restored.report()
    assert restored.path.read_bytes() == before
    now[0] = first["ends_at"]
    assert not restored.hit("goals", "open")
    assert restored.report()["status"] == "finished"
    assert restored.report()["totals"] == {"goals": {"open": 2}}
    restored.start(7)
    assert len(restored.load()["studies"]) == 2  # Keep the earlier study.
    restored.stop()
    assert not restored.hit("chat", "send")
    assert restored.report()["status"] == "stopped"


def test_concurrent_counts_and_corrupt_storage_do_not_break_actions(tmp_path):
    study = UsageStudy(tmp_path, clock=lambda: 1000)
    study.start()
    def hit(_):
        return UsageStudy(tmp_path, clock=lambda: 1000).hit("chat", "send")
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(hit, range(20)))
    assert study.report()["totals"] == {"chat": {"send": 20}}
    study.path.write_text("broken")
    assert not study.hit("chat", "send")
    assert study.path.read_text() == "broken"
    with pytest.raises(ChatError, match="kept"):
        study.report()


def test_outcome_observation_and_repeated_dismissals_are_not_inflated(tmp_path):
    import uuid
    from wow_helper.activity_history import ActivityHistory
    study = UsageStudy(tmp_path)
    study.start()
    history = ActivityHistory(tmp_path)
    source = {"type": "chat", "provider": "codex", "session_id": str(uuid.UUID(int=1)),
              "request_id": str(uuid.UUID(int=2))}
    key = history.record(source, "completed", "Synthetic title excluded from metrics", 1000)
    history.record(source, "completed", "Synthetic", 1000)
    history.act(key, "dismiss"); history.act(key, "dismiss")
    assert study.report()["totals"] == {"chat": {"completed": 1}, "activity_history": {"dismiss": 1}}
    assert "Synthetic" not in study.path.read_text()


def test_cli_study_does_not_touch_assistive_input(tmp_path, monkeypatch, capsys):
    from wow_helper import __main__ as cli, usage_study
    monkeypatch.setattr(usage_study, "UsageStudy", lambda: UsageStudy(tmp_path, clock=lambda: 1000))
    assert cli.main(["usage-study", "start", "--days", "7"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "active"
    assert cli.main(["usage-study", "stop"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "stopped"
