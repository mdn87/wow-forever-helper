"""Synthetic cached text never becomes executable instructions or a send queue."""

from wow_helper.chat import Message
from wow_helper.window_state import MAX_HISTORY_CHARS, history_state, restored_history, saved_selection


def test_saved_history_is_bounded_to_recent_human_and_agent_text():
    messages = [Message(str(i), "assistant", "A" * 10_000) for i in range(150)]
    messages.append(Message("tool", "tool", "This is not chat text"))
    saved = history_state(messages)
    assert len(saved) <= 100
    assert sum(len(item["text"]) for item in saved) <= MAX_HISTORY_CHARS
    assert saved[-1]["id"] == "149"
    assert all(item["role"] == "assistant" for item in saved)


def test_long_saved_preview_is_marked_without_mutating_source():
    original = Message("long", "assistant", "B" * 80_000)
    saved = history_state([original])
    assert "Saved preview shortened" in saved[0]["text"]
    assert len(original.text) == 80_000


def test_malformed_saved_content_is_ignored():
    raw = [None, 3, {"id": [], "role": "assistant", "text": "bad"},
           {"id": "tool", "role": "tool", "text": "bad"},
           {"id": "valid", "role": "user", "text": "Synthetic message"}]
    assert restored_history(raw) == [Message("valid", "user", "Synthetic message")]
    assert restored_history({}) == []
    assert saved_selection({"provider": [], "id": "invalid"}) is None
    assert saved_selection({"provider": "codex", "id": "invalid"}) is None
