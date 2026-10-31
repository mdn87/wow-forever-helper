"""Installing the context-channel probe addon, and keeping its files plain text.

No game client is involved and the optional ``lupa`` package is not needed; the addon's behaviour is
checked in test_context_addon.py and test_context_addon_ui.py.
"""
import json

import pytest

from wow_helper import __main__ as cli
from wow_helper import wtf

PROBE_FILES = ["WoWCompanionProbe.lua", "WoWCompanionProbe.toc"]


def fake_root(tmp_path):
    root = tmp_path / "World of Warcraft"
    (root / "_retail_" / "WTF").mkdir(parents=True)
    (root / "_never_run_").mkdir()
    return root


def test_installing_the_probe_copies_only_the_probe_into_game_folders_that_have_run(tmp_path):
    root = fake_root(tmp_path)
    assert wtf.install_addon([root], probe=True) == ["_retail_"]
    addons = root / "_retail_" / "Interface" / "AddOns"
    assert sorted(path.name for path in (addons / "WoWCompanionProbe").iterdir()) == PROBE_FILES
    assert not (addons / "WoWCompanion").exists()
    assert not (root / "_never_run_" / "Interface").exists()


def test_installing_the_companion_leaves_the_probe_out(tmp_path):
    root = fake_root(tmp_path)
    assert wtf.install_addon([root]) == ["_retail_"]
    addons = root / "_retail_" / "Interface" / "AddOns"
    assert (addons / "WoWCompanion").is_dir() and not (addons / "WoWCompanionProbe").exists()


def test_the_command_tells_the_player_how_to_switch_the_probe_on(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(wtf, "registry_roots", lambda: [])
    monkeypatch.setattr(wtf, "DEFAULT_ROOTS", ())
    monkeypatch.setattr(cli, "SETTINGS", tmp_path / "runtime" / "companion.json")
    root = fake_root(tmp_path)
    assert cli.main(["install-addon", "--wow-root", str(root), "--probe"]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "installed" and report["flavors"] == ["_retail_"]
    assert "Enable WoW Companion Probe" in report["next"] and "/wfhprobe" in report["next"]
    assert str(tmp_path) not in output


@pytest.mark.parametrize("name", PROBE_FILES)
def test_the_probe_files_are_plain_ascii_text(name):
    data = (wtf.PROBE_SOURCE / name).read_bytes()
    stray = sorted({byte for byte in data if not (byte in (9, 10, 13) or 32 <= byte < 127)})
    assert stray == []
