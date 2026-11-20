"""Synthetic command-library behavior; no game connection or input."""

from wow_helper.command_library import COMMANDS, find_commands


def test_search_finds_symptoms_and_exact_console_names():
    fix = find_commands("moving brighter")[0]
    assert fix.command == "/console ResampleSharpness -1"
    assert "reported" in fix.status.lower()
    assert fix in find_commands("RESAMPLESHARPNESS")
    assert not find_commands("unmatched synthetic query")
    assert all(c.category == "Draw distance" for c in find_commands(category="Draw distance"))


def test_graphics_entries_explain_uncertainty_and_offer_inspection_and_restore():
    entry = find_commands("farclip")[0]
    assert entry.status == "Experimental"
    assert "maximum" in entry.caution
    assert entry.inspect == '/dump GetCVar("farclip")'
    assert entry.restore == '/run SetCVar("farclip", GetCVarDefault("farclip"))'
    assert all(c.source.startswith("https://") for c in COMMANDS)
    assert len({c.key for c in COMMANDS}) == len(COMMANDS)


def test_addon_commands_do_not_masquerade_as_builtin_settings():
    entry = find_commands("junk confirmation")[0]
    assert entry.command == "/aajs on"
    assert entry.status == "Addon required"
    assert "Junk & Repair Manager" in entry.description
    assert not entry.inspect and not entry.restore
