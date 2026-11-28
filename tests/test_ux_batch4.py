"""Synthetic isolated-desktop regression tests for UX Batch 4 (U14-U18) and Codex UX-03."""

from datetime import datetime
from pathlib import Path
import time
import uuid

import pytest

from test_workspace import SESSIONS, SyntheticActivities, manager_factory, settle  # noqa: F401
from wow_helper.assist import Assistant
from wow_helper.chat import ChatError
from wow_helper.recurrence import local_timezone_name, validate_rule
from wow_helper.search import open_row
from wow_helper.setup_health_ui import SetupHealthDialog


def test_u14_quest_master_detail_priority_groups_and_character_gear_table(manager_factory, tmp_path, monkeypatch):
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)

    class RichActivities(SyntheticActivities):
        def reports(self, steps, flavor):
            self.calls.append((list(steps), flavor))
            result = {}
            if "quests" in steps:
                plan = [
                    {"id": 101, "level": 12, "title": "Turn-in Synthetic Quest", "zone": "Example Zone",
                     "action": "turn in", "complete": True, "remaining": [], "notes": ["Speak to Example NPC"]},
                    {"id": 102, "level": 13, "title": "Local Zone Synthetic Quest", "zone": "Example Zone",
                     "action": "finish", "complete": False, "remaining": ["2/5 Example Boars"], "notes": []},
                    {"id": 103, "level": 14, "title": "Distant Synthetic Quest", "zone": "Far Hills",
                     "action": "finish", "complete": False, "remaining": ["0/1 Example Map"], "notes": []},
                ]
                result["quests"] = {
                    "snapshot_at": 1000,
                    "data": {
                        "quest_count": 3, "age_seconds": 30, "zone": "Example Zone",
                        "player": {"level": 13, "class": "WARRIOR", "zone": "Example Zone"},
                        "plan": plan, "available": [{"title": "Nearby Synthetic Offer"}], "warnings": [],
                    },
                    "text": "Synthetic quests",
                }
            if "character" in steps:
                result["character"] = {
                    "snapshot_at": 1000,
                    "data": {
                        "age_seconds": 30,
                        "player": {"level": 13, "class": "WARRIOR"},
                        "gear": [
                            {"slot": "chest", "id": 1001, "ilvl": 15, "durability_percent": 20},
                            {"slot": "hands", "id": 1002, "ilvl": 14, "durability_percent": 95},
                        ],
                    },
                    "text": "Testchar · Level 13 Warrior · 12g 34s 56c",
                }
            return result

    class Research:
        def __init__(self):
            self.calls = []
        def request(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return "c" * 64
        def poll(self):
            pass
        def get(self, _key):
            return {"status": "running", "tier": "easy"}

    activity = RichActivities(tmp_path)
    manager = manager_factory(activity=lambda: activity)
    qwin = manager.new_window(kind="quests")
    qview = qwin.view
    settle(qview)
    qview._guidance = research = Research()
    qview.guide_auto.set(False)
    qview._guide_settings()

    qt = qview.quest_tree
    assert qt.tree.exists("group:turnin")
    assert qt.tree.exists("group:zone")
    assert qt.tree.exists("group:progress")
    assert qt.tree.exists("group:pickups")

    keys = list(qt.quests)
    qt.tree.focus(keys[1])
    qt.tree.selection_set(keys[1])
    qt._selected_changed()
    manager.root.update()
    assert "Local Zone Synthetic Quest" in qt.detail_title.get()
    assert "2/5 Example Boars" in qt.detail.get("1.0", "end-1c")

    # Explicit Research quest button queues research even when guide_auto=False.
    qt.research_button.invoke()
    qview.on_tick()
    settle(qview)
    assert len(research.calls) == 1

    # Guide sources render clickable safe URLs and ignore unsafe javascript: URLs.
    qt.set_guide(keys[1], {
        "status": "completed", "tier": "easy",
        "guide": {
            "summary": "Hunt boars north of camp.",
            "steps": ["Head north along the synthetic road."],
            "caveats": ["Drop rate varies."],
            "sources": [
                {"title": "Example Guide", "url": "https://example.org/quest-102"},
                {"title": "Bad Link", "url": "javascript:alert(1)"},
            ],
        },
    })
    manager.root.update()
    assert list(qt.detail_links.values()) == ["https://example.org/quest-102"]
    qt._open_url("https://example.org/quest-102")
    qt._open_url("javascript:alert(1)")
    assert opened == ["https://example.org/quest-102"]

    # Character status formats an aligned equipment table with [LOW] durability callout & separate Gear research tab.
    cwin = manager.new_window(kind="character")
    cview = cwin.view
    settle(cview)
    report_body = cview.report_text.get("1.0", "end-1c")
    assert "EQUIPMENT" in report_body
    assert "20%  [LOW]" in report_body
    assert "Repair check: low durability (<35%) on Chest." in report_body

    cview._gear_guide = {
        "status": "completed",
        "guide": {
            "summary": "Crafted chest upgrade available.",
            "steps": ["Check auction house or blacksmithing."],
            "caveats": ["Prices fluctuate."],
            "sources": [{"title": "Item Guide", "url": "https://example.org/item-1001"}],
        },
    }
    cview._render_gear()
    manager.root.update()
    assert "Crafted chest upgrade available." in cview.gear_research_text.get("1.0", "end-1c")
    assert cview.character_book.select() == str(cview.gear_research_tab)


def test_u15_review_overview_full_payload_and_codex_ux03_invariants(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    view = window.view
    settle(view)
    view._select_session(SESSIONS[0])
    settle(view)
    manager.handsfree.connect(window)

    # 1. DiscussionNotebook (FightQuestion): unprepared Send refused by button AND hands-free voice.
    view.show_fight_question()
    fight = view._notebooks["fight"]
    manager.root.update()
    assert str(fight.send_button["state"]) == "disabled"
    fight.send()
    assert view.service.sent == []

    manager.handsfree.handle({"id": str(uuid.UUID(int=401)), "text": "send"})
    settle(view)
    assert view.service.sent == []

    # Prepare review: Overview is default tab, Full payload has verbatim packet, hands-free "read it" works.
    fight.editors["question"].insert("1.0", "Why did tank take spike damage?")
    fight.editors["digest"].insert("1.0", "Example Cleave hit You for 4200 damage.")
    fight.changed()
    fight.prepare()
    manager.root.update()

    assert fight.review_book.index("current") == 0
    overview_text = fight.overview.get("1.0", "end-1c")
    payload_text = fight.preview.get("1.0", "end-1c")
    assert view.session_title in overview_text
    assert "Example Cleave" in overview_text
    assert "Example Cleave" in payload_text
    assert "DESTINATION\n" + view.session_title in payload_text
    assert str(fight.send_button["state"]) == "normal"

    manager.handsfree.handle({"id": str(uuid.UUID(int=402)), "text": "read it"})
    manager.root.update()
    assert "Example Cleave" in manager.handsfree.history[-1][2]

    # Input edit invalidates BOTH Overview and Full payload and blocks button + hands-free Send.
    fight.editors["question"].insert("end", " Extra edit")
    fight.changed()
    manager.root.update()
    assert fight.packet is None
    assert str(fight.send_button["state"]) == "disabled"
    assert str(fight.save_button["state"]) == "disabled"
    assert "Inputs changed" in fight.overview.get("1.0", "end-1c")
    assert "Inputs changed" in fight.preview.get("1.0", "end-1c")

    fight.send()
    manager.handsfree.handle({"id": str(uuid.UUID(int=403)), "text": "send"})
    settle(view)
    assert view.service.sent == []

    # Re-prepare, then change destination -> Send refuses and dispatches nothing.
    fight.prepare()
    manager.root.update()
    assert fight.packet is not None
    view._select_session(SESSIONS[1])
    settle(view)
    fight.send()
    assert "conversation changed" in fight.notice.get().lower()
    assert view.service.sent == []

    # Switch back, re-prepare, and Send dispatches exact prepared packet to bound destination.
    view._select_session(SESSIONS[0])
    settle(view)
    fight.prepare()
    bound_task = fight.packet["task"]
    fight.send()
    settle(view)
    assert len(view.service.sent) == 1
    assert view.service.sent[0][0] == SESSIONS[0].key
    assert bound_task in view.service.sent[0][1]
    fight.close()

    # 2. RequestDialog: Overview default + Full payload verbatim + destination mismatch blocks Send.
    from wow_helper.task_window import RequestDialog
    packet = {
        "window": "Journal", "edition": "Classic Forever", "task": "Summarize my notes.",
        "instructions": "Be concise.", "skills": [], "reports": {}, "context_files": [], "prepared_at": 1000.0,
    }
    req = view._request_dialog = RequestDialog(view, packet, SESSIONS[0].key)
    manager.root.update()
    assert req.review_book.index("current") == 0
    assert "Summarize my notes." in req.overview.get("1.0", "end-1c")
    assert "OPENING REQUEST" in req.preview.get("1.0", "end-1c")
    view._select_session(SESSIONS[1])
    settle(view)
    req.send()
    assert str(req.send_button["state"]) == "disabled"
    assert len(view.service.sent) == 1
    req.close()

    # 3. FollowupDialog: Overview default + Full payload verbatim + invalidate disables Send and clears both tabs.
    view._select_session(SESSIONS[0])
    settle(view)
    view.activity.add_note(
        view.journal_id, "My journal", "Synthetic saved advice",
        source={"provider": SESSIONS[0].provider, "session_id": SESSIONS[0].id},
        evidence={"text": "Synthetic evidence", "edition": "Classic Forever"},
    )
    view.resume_session()
    resume = view._resume_dialog
    resume.use_current.set(True)
    resume.prepare_followup()
    fup = resume.followup
    manager.root.update()
    assert fup.review_book.index("current") == 0
    assert "Synthetic saved advice" in fup.preview.get("1.0", "end-1c")
    assert str(fup.send_button["state"]) == "normal"
    fup.task.set("Updated follow-up question")
    manager.root.update()
    assert fup.packet is None
    assert str(fup.send_button["state"]) == "disabled"
    assert "Selection changed" in fup.overview.get("1.0", "end-1c")
    assert "Selection changed" in fup.preview.get("1.0", "end-1c")
    fup.prepare()
    manager.root.update()
    assert fup.packet is not None and str(fup.send_button["state"]) == "normal"
    resume.close()
    manager.handsfree.disconnect()


@pytest.mark.parametrize("theme,scaling", [("classic", 1.33), ("modern", 1.67)])
def test_u15_review_overview_fits_without_scrolling_at_a_large_chat_font(manager_factory, theme, scaling):
    # The Overview took the 20-point chat font and needed scrolling; Full payload keeps the chat font.
    from tkinter import font
    from wow_helper.task_window import RequestDialog
    manager = manager_factory()
    manager.preview_interface({"theme": theme})
    view = manager.windows[0].view
    settle(view)
    view._select_session(SESSIONS[0])
    settle(view)
    view.set_appearance({**view.appearance, "font_size": 20})
    original = view.root.tk.call("tk", "scaling")
    view.root.tk.call("tk", "scaling", scaling)
    try:
        packet = {"window": "Journal", "edition": "Classic Forever", "task": "Summarize my notes.",
                  "instructions": "Be concise.", "skills": [], "reports": {}, "context_files": [], "prepared_at": 1000.0}
        req = view._request_dialog = RequestDialog(view, packet, SESSIONS[0].key)
        manager.root.update()
        assert req.overview.winfo_ismapped()
        assert req.overview.yview() == (0.0, 1.0)
        assert font.Font(root=req.preview, font=req.preview.cget("font")).actual("size") == 20
        req.close()

        view.show_fight_question()
        fight = view._notebooks["fight"]
        fight.editors["question"].insert("1.0", "Why did tank take spike damage?")
        fight.editors["digest"].insert("1.0", "Example Cleave hit You for 4200 damage.")
        fight.changed()
        fight.prepare()
        manager.root.update()
        assert fight.overview.winfo_ismapped()
        assert fight.overview.yview() == (0.0, 1.0)
        fight.close()
    finally:
        view.root.tk.call("tk", "scaling", original)


def test_u14_quest_guide_states_read_in_the_detail_pane(manager_factory, tmp_path):
    # A failed read left "Loading the saved quest snapshot…" in the list, cut by the column at 20 points.
    class NoSnapshot(SyntheticActivities):
        def reports(self, steps, flavor):
            raise ChatError("No snapshot for this edition. Enable WoW Companion and /reload in game, then Refresh.")

    manager = manager_factory(activity=lambda: NoSnapshot(tmp_path / "missing"))
    window = manager.new_window(kind="quests")
    tree = window.view.quest_tree
    assert tree.tree.get_children() == ()
    assert tree.detail_title.get() == "Loading quests…"
    assert "Reading the saved quest snapshot" in tree.detail.get("1.0", "end-1c")
    settle(window.view)
    assert tree.tree.get_children() == ()
    assert tree.detail_title.get() == "No quests loaded"
    assert "No snapshot for this edition" in tree.detail.get("1.0", "end-1c")
    assert str(tree.research_button["state"]) == "disabled"

    # An empty snapshot says so in the pane as well.
    tree.load({"plan": [], "available": []}, "_forever_")
    assert tree.tree.get_children() == ()
    assert tree.detail_title.get() == "No quests in this snapshot"

    # A failed refresh keeps quests that were already read.
    loaded = manager_factory(path=tmp_path / "loaded.json").new_window(kind="quests")
    settle(loaded.view)
    quests_before = loaded.view.quest_tree.tree.get_children()
    assert quests_before
    loaded.view._report_result(None, "Synthetic read failure")
    assert loaded.view.quest_tree.tree.get_children() == quests_before
    assert loaded.view.quest_tree.detail_title.get() != "No quests loaded"


@pytest.mark.parametrize("theme,scaling", [("classic", None), ("classic", 1.33), ("modern", 1.67)])
def test_u16_goal_presets_stay_fully_visible_at_minimum_size(manager_factory, theme, scaling):
    manager = manager_factory()
    manager.preview_interface({"theme": theme})
    view = manager.windows[0].view
    settle(view)
    view._select_session(SESSIONS[0])
    settle(view)
    original = view.root.tk.call("tk", "scaling")
    if scaling:
        view.root.tk.call("tk", "scaling", scaling)
    try:
        view.show_goals()
        resume = view._resume_dialog
        resume.edit_goal(new=True)
        goal = resume.goal_dialog
        goal.root.geometry("%dx%d" % goal.root.minsize())
        goal.book.select(goal.book.tabs()[-1])
        manager.root.update()
        for label, button in goal.preset_buttons.items():
            row = button.master
            assert button.winfo_ismapped(), label
            assert button.winfo_width() >= button.winfo_reqwidth(), label
            assert button.winfo_x() + button.winfo_width() <= row.winfo_width(), label
        resume.close()
    finally:
        view.root.tk.call("tk", "scaling", original)


def test_u16_goal_presets_economy_checkbutton_and_bookmark_now(manager_factory):
    manager = manager_factory()
    view = manager.windows[0].view
    settle(view)
    view._select_session(SESSIONS[0])
    settle(view)

    # GoalDialog: prefilled local IANA zone and NA Weekly preset pass validate_rule.
    view.show_goals()
    resume = view._resume_dialog
    resume.edit_goal(new=True)
    goal = resume.goal_dialog
    manager.root.update()
    expected_zone = local_timezone_name()
    if expected_zone:
        assert goal.fields["zone"].get() == expected_zone
    goal.preset_buttons["NA Weekly"].invoke()
    manager.root.update()
    assert goal.fields["frequency"].get() == "Weekly"
    assert goal.fields["zone"].get() == "UTC"
    assert goal.fields["reset_time"].get() == "15:00"
    assert goal.fields["weekday"].get() == "Tuesday"
    rule = validate_rule({"frequency": "Weekly", "zone": "UTC", "time": "15:00", "weekday": 1})
    assert rule["weekday"] == 1
    resume.close()

    # EconomyNotebook: real Checkbutton with Checked/Not checked + Today/Last 7 days quick-fill.
    view.show_economy_notebook()
    econ = view._notebooks["economy"]
    manager.root.update()
    assert econ.confirm_check.winfo_class() == "TCheckbutton"
    assert econ.fields["confirmed"].get() == "Not checked"
    econ.confirm_check.invoke()
    assert econ.fields["confirmed"].get() == "Checked"
    econ.period_buttons[""][1].invoke()  # Last 7 days
    start_iso = econ.fields["start"].get()
    end_iso = econ.fields["end"].get()
    start_dt = datetime.fromisoformat(start_iso)
    end_dt = datetime.fromisoformat(end_iso)
    assert start_dt.tzinfo is not None and end_dt.tzinfo is not None
    assert start_dt < end_dt
    econ.close()

    # BookmarkDialog: Now (local) inserts timezone-aware ISO timestamp.
    view.bookmark_moment()
    bm = view._bookmark_dialog
    manager.root.update()
    bm.now_time_button.invoke()
    stamped = bm.image_time.get()
    parsed = datetime.fromisoformat(stamped)
    assert parsed.tzinfo is not None
    bm.close()


def test_u17_touch_quest_display_wrapping_and_activity_deck_touch_mode(manager_factory, monkeypatch):
    areas = [(0, 0, 1280, 800), (1280, 0, 2560, 800)]
    monkeypatch.setattr("wow_helper.workspace.display_workareas", lambda _: areas)
    manager = manager_factory()
    quest_win, cards_win = manager.open_wow_displays(areas[0], areas[1])

    qdisp = quest_win.display
    long_title = "Very long synthetic quest title " * 4
    qdisp.load_report({
        "snapshot_at": 2000,
        "data": {
            "quest_count": 2,
            "warnings": [],
            "plan": [
                {"action": "finish", "title": long_title, "zone": "Example Zone", "remaining": ["1/3 Items"]},
                {"action": "turn in", "title": "Second Synthetic Quest", "zone": "Example Town", "remaining": []},
            ],
            "available": None,
        },
    })
    manager.root.update()
    assert len(qdisp.row_buttons) == 2
    assert int(qdisp.row_buttons[0].cget("wraplength")) > 0
    qdisp.row_buttons[1].invoke()
    manager.root.update()
    assert qdisp.selected == 1
    assert "Second Synthetic Quest" in qdisp.detail.get("1.0", "end-1c")

    # ActivityDeck opens embedded TaskWindow with touch=True and Touch.TNotebook styling.
    deck = cards_win.display
    journal = deck.open_activity("journal")
    settle(journal)
    assert journal.touch is True
    assert journal.book.cget("style") == "Touch.TNotebook"


def test_u18_setup_health_dialog_install_check_assist_stop_and_inline_prompt(manager_factory, tmp_path):
    # Synthetic WoW install tree with synthetic SavedVariables fixture.
    wow_root = tmp_path / "SyntheticWoW"
    saved_dir = wow_root / "_forever_" / "WTF" / "Account" / "000000000" / "SavedVariables"
    saved_dir.mkdir(parents=True)
    fixture = Path(__file__).parent / "fixtures" / "savedvariables_check.lua"
    (saved_dir / "WoWCompanion.lua").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    settings_path = tmp_path / "companion.json"
    assist_path = tmp_path / "assist.sqlite"

    # Seed assistive state enabled with one binding.
    assistant = Assistant(assist_path, None)
    assistant.bind("teleport-orgrimmar", "F8")
    assistant.enable(True)

    installed_calls = []

    def fake_install(install_roots, only=None):
        installed_calls.append((list(install_roots), only))
        target = wow_root / "_forever_" / "Interface" / "AddOns" / "WoWCompanion"
        target.mkdir(parents=True, exist_ok=True)
        (target / "WoWCompanion.toc").write_text("## Interface: 11508\n## Version: 0.4.1\n", encoding="utf-8")
        return ["_forever_"]

    manager = manager_factory()
    window = manager.windows[0]
    settle(window.view)

    dialog = manager._setup_health_dialog = SetupHealthDialog(
        manager, window, settings_path=settings_path, assist_path=assist_path,
        roots_fn=lambda _cfg=None: [wow_root], install_fn=fake_install,
    )
    manager.root.update()

    # Opening never installs automatically.
    assert installed_calls == []
    assert dialog.tree.item("_forever_", "values")[1] == "Not installed"
    assert "Enabled" in dialog.assist_status.get()
    assert "F8" in dialog.assist_status.get()
    assert str(dialog.stop_assist_button["state"]) == "normal"

    # Explicit Install addon installs off-thread and updates edition status.
    dialog.edition.set("Classic Forever")
    dialog.install_button.invoke()
    deadline = time.monotonic() + 4
    while dialog.future is not None and time.monotonic() < deadline:
        manager.root.update()
        time.sleep(0.02)
    manager.root.update()
    assert len(installed_calls) == 1 and installed_calls[0][1] == "_forever_"
    assert "Installed (0.4.1)" in dialog.tree.item("_forever_", "values")[1]

    # Explicit Check snapshot renders path-free report without local paths or account IDs.
    dialog.check_button.invoke()
    deadline = time.monotonic() + 4
    while dialog.future is not None and time.monotonic() < deadline:
        manager.root.update()
        time.sleep(0.02)
    manager.root.update()
    report_text = dialog.report_text.get("1.0", "end-1c")
    assert "Snapshot check from" in report_text
    assert str(tmp_path) not in report_text
    assert "000000000" not in report_text

    # Safety Stop disables assistive input in sqlite and disables Stop button.
    dialog.stop_assist_button.invoke()
    manager.root.update()
    assert Assistant(assist_path, None).status()["enabled"] is False
    assert "Stopped" in dialog.assist_status.get()
    assert str(dialog.stop_assist_button["state"]) == "disabled"
    dialog.close()

    # Search command action "setup_health" opens SetupHealthDialog cleanly.
    open_row(manager, window, {"kind": "command", "target": "setup_health", "title": "WoW setup and addon health"})
    manager.root.update()
    assert manager._setup_health_dialog is not None
    manager._setup_health_dialog.close()

    # Missing snapshot in a quests window reveals inline WoW setup & addon button; valid refresh hides it.
    class FailingThenOk(SyntheticActivities):
        def __init__(self, storage):
            super().__init__(storage)
            self.fail = True
        def reports(self, steps, flavor):
            if self.fail:
                raise ChatError("No snapshot for this edition. Enable WoW Companion and /reload in game, then Refresh.")
            return super().reports(steps, flavor)

    flaky = FailingThenOk(tmp_path)
    manager.close()
    manager2 = manager_factory(activity=lambda: flaky)
    qwin = manager2.new_window(kind="quests")
    settle(qwin.view)
    assert qwin.view.setup_health_button.winfo_manager()
    flaky.fail = False
    qwin.view.refresh_panel()
    settle(qwin.view)
    assert not qwin.view.setup_health_button.winfo_manager()
