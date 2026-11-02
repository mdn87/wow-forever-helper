"""Isolated-desktop checks for the F18 Journal tool-access screen.

Synthetic notes and grants in tmp_path only. The system clipboard is never touched:
copy is captured by replacing the dialog's clipboard methods.
"""

import json
from types import SimpleNamespace
import uuid

import pytest

from test_publications import JOURNAL, NOTE, OTHER_SESSION, SESSION, env  # noqa: F401  (fixture)
from wow_helper.appearance import DEFAULTS
from wow_helper.chat import ChatError
from wow_helper.publications import PublicationService


def text_of(widget):
    return widget.get("1.0", "end-1c")


@pytest.fixture
def open_dialog(env, desktop):
    from wow_helper.tool_access_ui import ToolAccessDialog
    tk, root = desktop
    opened = []

    def make(note_id=NOTE):
        view = SimpleNamespace(tk=tk, root=root, appearance=dict(DEFAULTS), session_title="",
                               selection_key=None, activity=SimpleNamespace(storage=env.storage))
        owner = SimpleNamespace(view=view, journal_id=JOURNAL, tool_access=None)
        entry = next(e for e in env.journal.load(JOURNAL)["entries"] if e["id"] == note_id)
        dialog = owner.tool_access = ToolAccessDialog(owner, entry)
        opened.append(dialog)
        root.update()
        dialog.copied = []
        dialog.root.clipboard_clear = lambda: dialog.copied.clear()
        dialog.root.clipboard_append = lambda text: dialog.copied.append(text)
        return dialog

    yield make
    for dialog in opened:
        dialog.close()
    root.update()


def store(env):
    return PublicationService(env.storage)


def tokens(env):
    folder = env.storage / "tool-access"
    return [json.loads(p.read_text("utf-8"))["env"]["WOW_HELPER_TOOL_TOKEN"] for p in folder.glob("*.json")] if folder.exists() else []


def test_opening_and_refresh_publish_and_request_nothing(env, open_dialog):
    env.note(evidence={"text": "Synthetic snapshot", "image": str(uuid.UUID(int=50)) + ".png"})
    dialog = open_dialog()
    assert not env.state.exists()
    preview = text_of(dialog.preview)
    assert "EXACT PUBLICATION SELECTION" in preview and "Synthetic advice for Testchar" in preview
    assert ".png" not in preview and "image reference is omitted" in preview
    assert str(dialog.publish_button["state"]) == "disabled"
    assert str(dialog.show_setup_button["state"]) == "disabled"
    assert str(dialog.copy_setup_button["state"]) == "disabled"
    assert dialog.grants == [] and dialog._timer is not None
    dialog.refresh_access()
    dialog.poll_access()
    dialog.review_note()
    assert not env.state.exists()
    assert "no evidence was published" in dialog.notice.get() or "Review" in dialog.notice.get()


def test_new_grant_publishes_nothing_and_keeps_setup_hidden(env, open_dialog):
    env.note()
    dialog = open_dialog()
    dialog.lifetime.set("1 hour")
    dialog.create_grant()
    [grant] = dialog.grants
    assert grant["state"] == "active" and grant["records"] == []
    assert grant["expires_at"] - grant["created_at"] == 3600
    [token] = tokens(env)
    assert token not in text_of(dialog.setup_preview) and token not in dialog.notice.get()
    assert str(dialog.copy_setup_button["state"]) == "disabled"
    assert str(dialog.publish_button["state"]) == "normal"
    assert str(dialog.show_setup_button["state"]) == "normal"
    before = env.state.read_bytes()
    for _ in range(3):
        dialog.refresh_access()
        dialog.poll_access()
    dialog.grant_selected()
    assert env.state.read_bytes() == before
    assert store(env).status(grant["grant_id"])["record_ids"] == []
    assert dialog.copied == []


def test_private_setup_is_shown_and_copied_only_on_explicit_action(env, open_dialog):
    env.note()
    dialog = open_dialog()
    dialog.create_grant()
    [token] = tokens(env)
    dialog.copy_setup()
    assert dialog.copied == []
    dialog.show_setup()
    assert token in text_of(dialog.setup_preview)
    assert str(dialog.copy_setup_button["state"]) == "normal"
    dialog.copy_setup()
    assert len(dialog.copied) == 1 and json.loads(dialog.copied[0])["env"]["WOW_HELPER_TOOL_TOKEN"] == token
    # A changed descriptor is rechecked before copying and clears the shown setup.
    grant_id = dialog.chosen_grant()["grant_id"]
    path = env.storage / "tool-access" / (grant_id + ".json")
    descriptor = json.loads(path.read_text("utf-8"))
    descriptor["args"].append("--extra")
    path.write_text(json.dumps(descriptor), "utf-8")
    dialog.copy_setup()
    assert len(dialog.copied) == 1
    assert token not in text_of(dialog.setup_preview) and dialog._setup is None
    assert str(dialog.copy_setup_button["state"]) == "disabled"


def test_setup_is_hidden_when_access_is_removed_elsewhere(env, open_dialog):
    env.note()
    dialog = open_dialog()
    dialog.create_grant()
    [token] = tokens(env)
    dialog.show_setup()
    assert token in text_of(dialog.setup_preview)
    store(env).revoke(dialog.chosen_grant()["grant_id"])
    dialog.poll_access()
    assert token not in text_of(dialog.setup_preview) and dialog._setup is None
    assert "Private setup hidden" in dialog.notice.get()
    assert str(dialog.show_setup_button["state"]) == "disabled"
    assert str(dialog.publish_button["state"]) == "disabled"


def test_switching_grants_clears_setup(env, open_dialog):
    env.note()
    dialog = open_dialog()
    dialog.create_grant()
    dialog.create_grant()
    dialog.show_setup()
    assert dialog._setup is not None
    dialog.grant_choice.current(1 - dialog.grant_choice.current())
    dialog.grant_selected()
    assert dialog._setup is None and not any(t in text_of(dialog.setup_preview) for t in tokens(env))


def test_publish_requires_review_of_the_current_saved_selection(env, open_dialog):
    env.note()
    dialog = open_dialog()
    dialog.create_grant()
    dialog.publish_note()
    grant = dialog.chosen_grant()
    [record] = grant["records"]
    assert record["state"] == "available"
    before = env.state.read_bytes()
    dialog.refresh_access()
    dialog.poll_access()
    assert env.state.read_bytes() == before
    # Change the saved note after review: publishing is refused until it is reviewed again.
    env.raw_journal_edit(NOTE, text="Edited synthetic advice")
    dialog.publish_note()
    assert "Review it again" in dialog.notice.get()
    assert dialog.review is None and str(dialog.publish_button["state"]) == "disabled"
    assert env.state.read_bytes() == before
    dialog.publish_note()
    assert env.state.read_bytes() == before
    dialog.review_note()
    assert "Edited synthetic advice" in text_of(dialog.preview)
    assert str(dialog.publish_button["state"]) == "normal"
    dialog.publish_note()
    assert len(dialog.chosen_grant()["records"]) == 2


def test_cross_conversation_grants_are_not_listed(env, open_dialog):
    env.note()
    store(env).create("claude", OTHER_SESSION)
    store(env).create("codex", SESSION)
    dialog = open_dialog()
    assert dialog.grants == []
    assert str(dialog.publish_button["state"]) == "disabled"


def test_remove_record_and_grant(env, open_dialog):
    env.note()
    dialog = open_dialog()
    dialog.create_grant()
    dialog.publish_note()
    grant_id = dialog.chosen_grant()["grant_id"]
    record_id = dialog.chosen_grant()["records"][0]["record_id"]
    assert str(dialog.remove_record_button["state"]) == "normal"
    dialog.remove_record()
    assert dialog.chosen_grant()["records"][0]["state"] == "removed"
    assert str(dialog.remove_record_button["state"]) == "disabled"
    assert store(env).status(grant_id)["record_ids"] == []
    dialog.show_setup()
    dialog.remove_grant()
    assert dialog.chosen_grant()["state"] == "removed"
    assert dialog._setup is None
    for button in (dialog.publish_button, dialog.show_setup_button, dialog.remove_grant_button, dialog.copy_setup_button):
        assert str(button["state"]) == "disabled"
    assert store(env).status(grant_id)["active"] is False
    # The Journal note and retained snapshot are kept.
    assert env.journal.load(JOURNAL)["entries"][0]["id"] == NOTE
    assert record_id in json.loads(env.state.read_text("utf-8"))["records"]


def test_unpublishable_note_still_manages_existing_access(env, open_dialog):
    env.note(evidence=None)
    grant_id = store(env).create("claude", SESSION)["grant_id"]
    dialog = open_dialog()
    assert "cannot currently be published" in text_of(dialog.preview)
    assert str(dialog.publish_button["state"]) == "disabled"
    assert dialog.chosen_grant()["grant_id"] == grant_id
    dialog.remove_grant()
    assert store(env).status(grant_id)["revoked"] is True


def test_note_without_original_conversation_cannot_open(env, desktop):
    from wow_helper.tool_access_ui import ToolAccessDialog
    env.note(source=False)
    tk, root = desktop
    view = SimpleNamespace(tk=tk, root=root, appearance=dict(DEFAULTS), activity=SimpleNamespace(storage=env.storage))
    owner = SimpleNamespace(view=view, journal_id=JOURNAL, tool_access=None)
    with pytest.raises(ChatError, match="original conversation"):
        ToolAccessDialog(owner, env.journal.load(JOURNAL)["entries"][0])
    assert not env.state.exists()


def test_unreadable_state_disables_operations_without_overwrite(env, open_dialog):
    env.note()
    dialog = open_dialog()
    dialog.create_grant()
    dialog.show_setup()
    env.state.write_text('{"version":2}', "utf-8")
    dialog.refresh_access()
    assert "damaged or unsupported" in dialog.notice.get()
    assert dialog.grants == [] and dialog._setup is None
    assert str(dialog.publish_button["state"]) == "disabled"
    assert env.state.read_text("utf-8") == '{"version":2}'


def test_close_cancels_refresh_and_clears_setup(env, open_dialog, desktop):
    env.note()
    dialog = open_dialog()
    dialog.create_grant()
    dialog.show_setup()
    owner = dialog.owner
    dialog.close()
    assert dialog._closed and dialog._setup is None and owner.tool_access is None
    assert dialog.refresh_access() is None
    dialog.poll_access()
    desktop[1].update()
    dialog.close()
