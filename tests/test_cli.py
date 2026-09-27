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
    assert invoke("status")[1] == {"enabled": False, "bindings": {}}
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
