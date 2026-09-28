"""CLI integration with synthetic state and a fake input boundary."""

import json

import pytest

from wow_helper import __main__ as cli
from wow_helper.assist import Assistant
from wow_helper import windows_input


@pytest.fixture
def command(tmp_path, monkeypatch, capsys):
    calls = []
    class Desktop:
        def press(self, chord):
            calls.append(chord.name)
    monkeypatch.setattr(windows_input, "WindowsInput", Desktop)
    monkeypatch.setattr(cli, "Assistant", lambda path, desktop: Assistant(
        tmp_path / "assist.sqlite", desktop, clock=lambda: 100))
    def invoke(*args):
        code = cli.main(list(args))
        return code, json.loads(capsys.readouterr().out)
    return invoke, calls


def test_cli_setup_preview_execute_stop_and_duplicate(command):
    invoke, calls = command
    assert invoke("status")[1] == {"enabled": False, "stub": False, "bindings": {}}
    assert invoke("bind", "teleport-orgrimmar", "--key", "SHIFT+7")[0] == 0
    assert invoke("request", "cast teleport to orgrimmar")[1]["status"] == "preview"
    assert calls == []
    invoke("enable")
    args = ("request", "cast teleport to orgrimmar on my mage", "--execute",
            "--request-id", "synthetic-cli-event", "--issued-at", "99")
    assert invoke(*args)[1]["status"] == "sent"
    assert calls == ["SHIFT+7"]
    assert invoke(*args)[0] == 2
    assert calls == ["SHIFT+7"]
    invoke("stop")
    assert invoke("status")[1]["enabled"] is False


def test_stub_mode_records_the_press_and_sends_nothing(command, tmp_path):
    invoke, calls = command
    invoke("bind", "teleport-orgrimmar", "--key", "SHIFT+F4")
    assert invoke("stub", "on")[1] == {"status": "stub on"}
    assert invoke("status")[1]["stub"] is True
    args = ("request", "Cast teleport to Org Grimmar.", "--execute",
            "--request-id", "synthetic-stub-event", "--issued-at", "99")
    # Every other check still applies: stopped input refuses before anything is recorded.
    assert invoke(*args)[0] == 2
    invoke("enable")
    code, result = invoke(*args)
    assert (code, result["status"], result["key"]) == (0, "stubbed", "SHIFT+F4")
    assert calls == []
    log = (tmp_path / "stub-presses.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["key"] for line in log] == ["SHIFT+F4"]
    # Replay protection is shared with live mode.
    assert invoke(*args)[0] == 2
    assert len((tmp_path / "stub-presses.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    invoke("stub", "off")
    invoke(*args[:3], "--request-id", "synthetic-live-event", "--issued-at", "99")
    assert calls == ["SHIFT+F4"]


def test_cli_does_not_echo_rejected_speech(command):
    invoke, _ = command
    code, result = invoke("request", "some synthetic private text")
    assert code == 2
    assert "private" not in json.dumps(result)


def test_cli_storage_error_does_not_echo_paths(monkeypatch, capsys):
    def fail(*args):
        raise OSError("synthetic sensitive filesystem detail")
    monkeypatch.setattr(cli, "Assistant", fail)
    assert cli.main(["status"]) == 3
    assert "filesystem detail" not in capsys.readouterr().out
