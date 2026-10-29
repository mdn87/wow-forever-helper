"""Isolated desktop checks for region review, destination changes and saving."""

from dataclasses import replace
import uuid
import pytest
from PIL import Image

from test_workspace import manager_factory, settle, SESSIONS
from test_live_gear import Agents
from wow_helper.gear_ui import GearDialog


class Key:
    available = True
    closed = False
    def requested(self):
        return False
    def close(self):
        self.closed = True


def panel(manager):
    view = manager.windows[0].view
    settle(view)
    view.service.agents = Agents()
    from wow_helper.activities import FLAVORS
    view.service.agents.data['edition'] = next(k for k, v in FLAVORS.items() if v == view.profile['flavor'])
    session = replace(SESSIONS[0], managed=True)
    view.service.sessions = [session, *SESSIONS[1:]]
    view._select_session(session); settle(view)
    dialog = view._gear_dialog = GearDialog(view, key_factory=Key)
    folder = view.activity.storage / 'captures'; folder.mkdir(parents=True, exist_ok=True)
    name = str(uuid.uuid4()) + '.png'
    Image.new('RGB', (400, 300), 'blue').save(folder / name)
    dialog.preview_flavor = view.profile['flavor']
    dialog.load_preview(name)
    dialog.region = [0, 0, 400, 300]
    dialog.build.set('Example build')
    return view, dialog


@pytest.mark.parametrize('theme', ['classic', 'modern'])
def test_region_and_destination_must_be_reviewed_before_enabling(manager_factory, theme):
    manager = manager_factory(); manager.preview_interface({'theme': theme})
    view, dialog = panel(manager)
    assert dialog.engine.approval is None and dialog.key is None
    dialog.enable()
    assert dialog.key is None
    dialog.review_region(); dialog.enable()
    assert dialog.key.available and dialog.engine.approval['session'].key == view.selection_key
    assert not view.service.sent
    key = dialog.key
    dialog.goal.set('Changed goal')
    assert key.closed and dialog.engine.approval is None
    dialog.chrome.place('440x480+40+40'); manager.root.update()
    for button in (dialog.preview_button, dialog.review_button, dialog.enable_button, dialog.save_button):
        assert button.winfo_ismapped()
        assert button.winfo_rooty() + button.winfo_height() <= dialog.root.winfo_rooty() + dialog.root.winfo_height()


def test_destination_change_disables_shortcut_without_sending(manager_factory):
    manager = manager_factory(); view, dialog = panel(manager)
    dialog.review_region(); dialog.enable()
    key = dialog.key
    view.selection_revision += 1
    dialog.poll()
    assert key.closed and dialog.key is None and dialog.engine.approval is None
    assert not view.service.sent


def test_closing_window_releases_enabled_shortcut(manager_factory):
    manager = manager_factory(); view, dialog = panel(manager)
    dialog.review_region(); dialog.enable()
    key = dialog.key
    dialog.close()
    assert key.closed and dialog.engine.approval is None and view._gear_dialog is None


def test_preview_button_captures_locally_without_sending_or_enabling(manager_factory):
    import time
    manager = manager_factory(); view, dialog = panel(manager)
    name = dialog.preview_name
    captures = []
    def capture(storage, flavor):
        captures.append(flavor)
        return name
    dialog.capture = capture
    dialog.preview_button.invoke()
    deadline = time.monotonic() + 2
    while dialog.future is not None and time.monotonic() < deadline:
        manager.root.update(); time.sleep(0.01)
    assert captures == [view.profile['flavor']] and dialog.future is None
    assert dialog.preview_name == name and dialog.region is None
    assert dialog.key is None and not view.service.agents.calls


def test_result_updates_without_focus_or_draft_changes_and_opens_reviewed_save(manager_factory):
    manager = manager_factory(); view, dialog = panel(manager)
    dialog.review_region(); dialog.enable()
    dialog.engine.capture = lambda *_, **__: dialog.preview_name
    dialog.engine.identify = lambda _: 42
    dialog.engine.foreground = lambda: 42
    view.editor.insert('1.0', 'Keep my unsent draft')
    focus = manager.root.focus_get()
    dialog.engine.begin(background=False)
    dialog.poll(); manager.root.update()
    assert manager.root.focus_get() == focus
    assert view.editor.get('1.0', 'end-1c') == 'Keep my unsent draft'
    assert '-30 points' in dialog.output.get('1.0', 'end-1c')
    assert dialog.evidence_name == dialog.preview_name
    dialog.save()
    assert view._journal_dialog is not None
    assert view._journal_dialog.selection['evidence']['image'] == dialog.preview_name
    assert 'Example candidate' in view._journal_dialog.selection['text']
