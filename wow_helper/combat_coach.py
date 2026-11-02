"""Manual post-fight notes with an explicit, unverified structured-import boundary."""

from copy import deepcopy
from pathlib import Path

from .activities import FLAVORS
from .build_tutor import bounded, discussion_packet
from .chat import ChatError
from .imports import import_record, replace_identity
from .notebook_ui import DiscussionNotebook
from .screen_capture import import_image, paste_image, saved_image


def prepare_manual_coaching(form, storage):
    edition = form.get("edition")
    if edition not in FLAVORS:
        raise ChatError("Choose a supported game edition.")
    encounter = bounded(form.get("encounter"), "Encounter", 200, True)
    phase = form.get("phase")
    if phase not in {"First attempt", "Compare later attempt"}:
        raise ChatError("Choose First attempt or Compare later attempt.")
    question = bounded(form.get("question"), "Question", 2000, True)
    attempt = bounded(form.get("attempt_notes"), "Attempt notes", 8000, True)
    prior = bounded(form.get("prior_notes", ""), "Earlier attempt notes", 8000)
    event_time = bounded(form.get("event_time", ""), "Encounter time", 100)
    terms_text = bounded(form.get("redact_terms", ""), "Names to mask", 1000)
    terms = [term.strip() for term in terms_text.split(",") if term.strip()]
    if len(terms) > 20 or any(len(term) > 100 for term in terms):
        raise ChatError("List at most 20 names to mask, each at most 100 characters.")
    if phase == "Compare later attempt" and not prior:
        raise ChatError("Earlier attempt notes are required for a manual comparison.")
    image = form.get("image", "")
    path = saved_image(storage, image) if image else None
    gaps = ["Manual notes only; no Details! export or structured combat log was parsed.",
            "Encounter identity, event coverage, actor identity, and timestamps are unverified.",
            "Damage or healing totals cannot establish an exact cause of death."]
    if not event_time:
        gaps.append("Encounter time was not supplied.")
    encounter, encounter_redactions = replace_identity(encounter, terms)
    attempt, attempt_redactions = replace_identity(attempt, terms)
    prior, prior_redactions = replace_identity(prior, terms)
    redactions = {key: encounter_redactions.get(key, 0) + attempt_redactions.get(key, 0) + prior_redactions.get(key, 0)
                  for key in set(encounter_redactions) | set(attempt_redactions) | set(prior_redactions)}
    payload = {"encounter": encounter, "phase": phase, "event_time": event_time or "Unknown",
               "attempt_notes": attempt,
               "earlier_attempt_notes": prior if phase == "Compare later attempt" else None,
               "identity_replacements": redactions}
    data = import_record("manual encounter notes", "Unknown", edition, payload,
                         coverage="Player-written summary; no structured rows or full event coverage.",
                         warnings=gaps, captured_at=event_time or "Unknown")
    packet = discussion_packet("Post-fight coaching", edition, question, data,
        "Review only the user-supplied encounter notes and selected image. Identify which statements are observations, "
        "which are interpretations, and what evidence supports each conclusion. Do not infer an exact death cause "
        "from aggregate totals. For a later attempt, compare only the explicitly supplied earlier and later notes. "
        "Describe missing coverage and timestamps as unknown. Do not claim this is a Details! export or structured "
        "combat-log analysis. Ask for edition-specific sources when explaining unfamiliar mechanics, and link sources "
        "actually read. Never send game input or start another capture.")
    packet["reports"]["combat"] = packet["reports"].pop("build")
    if path:
        packet["image"] = str(path.resolve())
    return packet


class CombatNotebook(DiscussionNotebook):
    kind, title = "combat", "Post-fight coaching"

    def make_fields(self):
        edition = next(key for key, value in FLAVORS.items() if value == self.view.profile["flavor"])
        self.bound_source = {key: self.initial.get(key, "") for key in ("source_provider", "source_session")}
        self.field("edition", "Game edition", edition, list(FLAVORS))
        self.field("encounter", "Encounter name")
        self.field("phase", "Review stage", "First attempt", ["First attempt", "Compare later attempt"])
        self.field("event_time", "Encounter time, if known")
        self.field("redact_terms", "Names to mask before sending (optional, comma-separated)")
        self.field("question", "Question", "What should I improve before the next attempt?")
        tab = self.editor("attempt_notes", "Attempt notes",
                          "Manual summary from your observations. Omit player names unless needed; do not paste raw combat logs.")
        self.ttk.Button(tab, text="Import readable summary…",
                        command=lambda: self.import_text("attempt_notes", 8000)).pack(side="bottom")
        self.editor("prior_notes", "Earlier attempt",
                    "For Compare later attempt, review the saved earlier notes and edit them if needed.")
        tab = self.tab("Image")
        bar = self.frame(tab)
        bar.pack(fill="x")
        self.ttk.Button(bar, text="Open image…", command=self.open_image).pack(side="left")
        self.ttk.Button(bar, text="Paste", command=self.paste).pack(side="left", padx=4)
        self.ttk.Button(bar, text="Remove", command=self.remove_image).pack(side="left")
        self.fields["image"] = self.tk.StringVar(master=self.root, value=self.initial.get("image", ""))
        self.image_label = self.label(tab, "No encounter image selected.")
        self.image_label.pack(fill="both", expand=True)
        self.image_label.bind("<Configure>", lambda _event: self.render_image())
        self.photo = None
        self.render_image()

    def form(self):
        return {**super().form(), **self.bound_source}

    def prepare_form(self, form):
        if form["phase"] == "Compare later attempt":
            bound = (self.bound_source["source_provider"], self.bound_source["source_session"])
            if not all(bound):
                raise ChatError("Save or send the first attempt in a conversation before comparing another attempt.")
            if self.view.selection_key != bound:
                raise ChatError("Select the original coaching conversation before comparing a later attempt.")
        return prepare_manual_coaching(form, self.view.activity.storage)

    def evidence(self, packet):
        result = super().evidence(packet)
        if packet.get("image"):
            result["image"] = Path(packet["image"]).name
        return result

    def remember_first_attempt(self):
        if not self.source:
            return
        reviewed = self.packet is not None and self.form() == self.reviewed_form
        self.bound_source = {"source_provider": self.source["provider"], "source_session": self.source["session_id"]}
        if self.fields["phase"].get() == "First attempt":
            earlier = self.editors["prior_notes"]
            if not earlier.get("1.0", "end-1c").strip():
                combat_data = self.packet["reports"]["combat"]["data"]
                earlier.insert("1.0", combat_data["payload"]["attempt_notes"])
        if reviewed:
            # A first-attempt packet excludes the binding and earlier-notes copy, so the same review stays valid.
            self.reviewed_form = deepcopy(self.form())
        self.changed()

    def save(self):
        stage = self.fields["phase"].get()
        if not self.valid_review():
            return
        try:
            self.view.activity.add_note(self.view.journal_id, self.title[:80], self.packet["task"], self.note_id,
                                        source=self.source, evidence=self.evidence(self.packet))
            self.notice.set("Saved in this window’s Journal. The manual evidence remains separate from any later attempt.")
        except (ChatError, OSError) as error:
            self.notice.set(str(error) if isinstance(error, ChatError)
                            else "The note could not be saved. Your review is kept.")
        if stage == "First attempt" and self.notice.get().startswith("Saved in"):
            self.remember_first_attempt()
            self.notice.set("First attempt saved locally and linked to the selected conversation. Check that chat before comparing a later attempt.")

    def send(self):
        stage = self.fields["phase"].get()
        if self.fields["image"].get():
            try:
                saved_image(self.view.activity.storage, self.fields["image"].get())
            except ChatError as error:
                self.notice.set(str(error))
                return
        super().send()
        if stage == "First attempt" and self.attempted:
            self.remember_first_attempt()
            self.notice.set("First attempt request queued once. Check the conversation for delivery; the saved notes can support a later comparison.")

    def choose_image(self, action):
        try:
            name = action()
            if name:
                self.fields["image"].set(name)
                self.render_image()
                self.changed()
        except ChatError as error:
            self.notice.set(str(error))

    def open_image(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title="Open a manually selected encounter image",
                                          filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")])
        if path:
            self.choose_image(lambda: import_image(self.view.activity.storage, path))

    def paste(self):
        self.choose_image(lambda: paste_image(self.view.activity.storage))

    def remove_image(self):
        self.fields["image"].set("")
        self.render_image()
        self.changed()

    def render_image(self):
        from PIL import Image, ImageTk
        name = self.fields["image"].get()
        self.photo = None
        if not name:
            self.image_label.configure(image="", text="No encounter image selected.")
            return
        try:
            with Image.open(saved_image(self.view.activity.storage, name)) as source:
                if source.width * source.height > 40_000_000:
                    raise ValueError
                preview = source.copy()
                preview.thumbnail((max(200, self.image_label.winfo_width() - 16),
                                   max(120, self.image_label.winfo_height() - 16)))
                self.photo = ImageTk.PhotoImage(preview, master=self.root)
            self.image_label.configure(image=self.photo, text="")
        except (ChatError, OSError, ValueError, Image.DecompressionBombError):
            self.image_label.configure(image="", text="Saved image unavailable. Select it again before sending.")

    def close(self):
        self.photo = None
        super().close()
