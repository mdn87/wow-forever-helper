"""Frozen, reviewed advice cards. Rendering and navigation never send requests."""

from copy import deepcopy
from datetime import datetime, timezone

from .chat import ChatError
from .journal import bounded_text, metadata
from .journal_ui import JournalDialog, note_summary
from .appearance import appearance_settings, style_text
from .theme import palette

PLAY_MINIMUM = (340, 300)


def pinned_selection(selection, objective, next_step, appearance=None):
    pin = {"version": 1, "text": selection.get("text"), "objective": objective,
           "next_step": next_step, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "appearance": appearance_settings(appearance),
           **metadata(selection.get("source"), selection.get("evidence"))}
    return validate_pin(pin)


def validate_pin(pin):
    try:
        if not isinstance(pin, dict) or type(pin.get("version")) is not int or pin["version"] != 1:
            raise ValueError
        for field, limit in (("text", 8000), ("objective", 200), ("next_step", 2000), ("at", 100)):
            bounded_text(pin.get(field), limit)
        result = {key: pin[key] for key in ("version", "text", "objective", "next_step", "at")}
        result.update(metadata(pin.get("source"), pin.get("evidence")))
        result["appearance"] = appearance_settings(pin.get("appearance"))
        return deepcopy(result)
    except (ValueError, TypeError, UnicodeError):
        raise ChatError("Use an objective up to 200 characters, a next step up to 2,000, and advice up to 8,000. The review is kept.") from None


class PinAdviceDialog(JournalDialog):
    def __init__(self, view, selection):
        self.selection = deepcopy(selection)
        self.saved = False
        super().__init__(view, "Pin to Play")
        self.notice.set("Review this frozen selection. The card is saved locally even with chat retention off. Later replies never replace it.")
        self.objective = self.tk.StringVar(master=self.root, value=selection.get("objective", getattr(view, "quest_title", "Selected advice")))
        self.next_step = self.tk.StringVar(master=self.root, value=selection.get("next_step", ""))
        fields = self.frame(self.surface, padding=8)
        fields.pack(fill="x")
        self.label(fields, "Objective").pack(anchor="w")
        self.ttk.Entry(fields, textvariable=self.objective).pack(fill="x")
        self.label(fields, "Next step (write the step to keep visible)").pack(anchor="w")
        self.ttk.Entry(fields, textvariable=self.next_step).pack(fill="x")
        book = self.ttk.Notebook(self.surface)
        book.pack(fill="both", expand=True, padx=8)
        advice, evidence = self.frame(book), self.frame(book)
        book.add(advice, text="Advice")
        book.add(evidence, text="Source & evidence")
        self.body = self.text(advice, selection["text"], editable=True)
        self.text(evidence, note_summary(selection))
        self.ttk.Button(self.actions, text="Pin to Play", command=self.save).pack(side="right", padx=6)
        self.show()

    def save(self):
        if self.saved:
            return
        selection = deepcopy(self.selection)
        selection["text"] = self.body.get("1.0", "end-1c")
        try:
            self.view.pin_advice(selection, self.objective.get(), self.next_step.get(), self.view.appearance)
        except ChatError as error:
            self.notice.set(str(error))
            return
        self.saved = True
        self.view.status.set("Pinned selection saved. Later replies will not change it.")
        self.close()

    def close(self):
        self.view._pin_dialog = None
        self.root.destroy()


class AdviceCard:
    def __init__(self, window):
        from tkinter import ttk
        from .task_window import text_box
        self.window = window
        tk, parent = window.manager.tk, window.body
        self.actions = tk.Frame(parent, bg=palette(parent).PANEL, padx=8, pady=6)
        self.actions.pack(side="bottom", fill="x")
        self.expand = ttk.Button(self.actions, text="Expand", command=window.toggle_play)
        self.expand.pack(side="left")
        self.source = ttk.Button(self.actions, text="Open source", command=self.open_source)
        self.source.pack(side="right")
        self.response = tk.StringVar(master=parent)
        self.status = tk.Label(parent, textvariable=self.response, bg=palette(parent).PANEL,
                               fg=palette(parent).MUTED, anchor="w", justify="left", wraplength=300,
                               font=("Segoe UI", 9), padx=8, pady=4)
        self.status.pack(side="bottom", fill="x")
        evidence = window.pin.get("evidence", {})
        value = evidence.get("snapshot_at")
        time_label = "Snapshot"
        if value is None:
            value = evidence.get("prepared_at")
            time_label = "Prepared" if value is not None else "Evidence time"
        source_time = "Unknown"
        if value is not None:
            try:
                source_time = datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            except (ValueError, OverflowError, OSError):
                pass
        self.source_time = tk.Label(parent, text=time_label + ": " + source_time,
                                    bg=palette(parent).PANEL, fg=palette(parent).MUTED,
                                    anchor="w", padx=8, font=("Segoe UI", 8))
        self.source_time.pack(side="bottom", fill="x")
        parent.bind("<Configure>", lambda e: self.status.configure(wraplength=max(180, e.width - 20)), add="+")
        self.text = text_box(tk, parent, takefocus=True)
        style_text(self.text, window.pin["appearance"])
        self.text.bind("<Control-e>", lambda _: window.toggle_play())
        self.text.bind("<Control-o>", lambda _: self.open_source())
        self.render()
        self._after = None
        self.poll()

    def render(self):
        from .task_window import replace_text
        pin = self.window.pin
        evidence = pin.get("evidence", {})
        snapshot = evidence.get("snapshot_at")
        prepared = evidence.get("prepared_at")
        # These are evidence times, never an inferred timestamp for the reply.
        def timestamp(value):
            if value is None:
                return "Unknown"
            try:
                return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")
            except (ValueError, OverflowError, OSError):
                return "Unknown"
        body = "OBJECTIVE\n" + pin["objective"] + "\nNEXT STEP\n" + pin["next_step"]
        if self.window.mode == "desk":
            body += ("\n\nSnapshot: " + timestamp(snapshot) + "\nPrepared: " + timestamp(prepared)
                     + "\nReply time: Unknown\nPinned: " + pin["at"] + "\n\n" + note_summary(pin))
        replace_text(self.text, body)
        self.expand.configure(text="Expand" if self.window.mode == "play" else "Back to Play")

    def poll(self):
        if self._after is not None:
            self.window.root.after_cancel(self._after)
            self._after = None
        source = self.window.pin.get("source")
        label = "Source unavailable · saved selection kept"
        if source:
            key = source["provider"], source["session_id"]
            for window in self.window.manager.windows:
                if not window.view:
                    continue
                for view in [window.view, *window.view.quest_chats.values()]:
                    if view.selection_key != key:
                        continue
                    if not view.selected:
                        continue
                    messages = view.history_cache.get(key, [])
                    latest = next((m for m in reversed(messages) if m.role == "assistant"), None)
                    if view.response_waits.get(key) or view.sending_wait:
                        label = "Source waiting for reply · pin unchanged"
                    elif latest and latest.id != source.get("message_id"):
                        label = "Source has another reply · pin unchanged"
                    else:
                        response = view.status.get()
                        label = ("Source: " + response if response.startswith("Response ") else
                                 "Source connected · saved reply; completion unknown")
        self.response.set(label)
        self._after = self.window.root.after(750, self.poll)

    def open_source(self):
        source = self.window.pin.get("source")
        if not source:
            self.window.set_notice("Original conversation unknown. Expand to read the saved advice.")
            return None
        try:
            result = self.window.manager.resume_conversation(source)
            self.window.set_notice("Source opened without sending. Saved advice remains here if the source is unavailable.")
            return result
        except ChatError as error:
            self.window.set_notice(str(error))
            return None

    def close(self):
        if self._after is not None:
            self.window.root.after_cancel(self._after)
