"""Explicit Journal publication review and private local tool setup."""

from copy import deepcopy
from datetime import datetime, timezone
import json

from .chat import ChatError
from .journal import identifier
from .journal_ui import JournalDialog
from .publications import PublicationService


def when(value):
    try:
        return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (OSError, ValueError, TypeError, OverflowError):
        return "Unknown"


def age(value):
    if value is None:
        return "Unknown"
    return f"{int(value)} seconds" if value < 60 else f"{value / 60:.1f} minutes"


class ToolAccessDialog(JournalDialog):
    """Stay bound to one note and its original source while the owner changes."""

    def __init__(self, owner, entry):
        self.owner, self.journal_id, self.note_id = owner, owner.journal_id, entry["id"]
        source = entry.get("source") or {}
        if source.get("provider") not in {"codex", "claude"} or not source.get("session_id"):
            raise ChatError("Choose a saved note with an original conversation to manage tool access.")
        self.source = {"provider": source["provider"], "session_id": identifier(source["session_id"])}
        self.service = PublicationService(owner.view.activity.storage)
        self.review = None
        self.grants = []
        self._closed = False
        self._timer = None
        self._setup = None
        self._setup_grant_id = None
        super().__init__(owner.view, "Journal tool access · experimental")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.chrome.minimum = (480, 600)
        self.root.minsize(*self.chrome.minimum)
        key = (self.source["provider"], self.source["session_id"])
        label = (getattr(self.view, "session_title", "") if getattr(self.view, "selection_key", None) == key else "")
        label = label or f"Saved {self.source['provider'].title()} conversation · …{self.source['session_id'][-8:]}"
        destination = self.label(self.surface, "Original conversation: " + label)
        destination.configure(wraplength=440, justify="left")
        destination.pack(fill="x", padx=8, pady=4)
        self.surface.bind("<Configure>", lambda event: destination.configure(wraplength=max(200, event.width - 24)), add="+")
        self.label(self.surface, "Grant · this conversation's time-limited tool access").pack(anchor="w", padx=8)
        self.grant_choice = self.ttk.Combobox(self.surface, state="readonly")
        self.grant_choice.pack(fill="x", padx=8, pady=(2, 6))
        self.grant_choice.bind("<<ComboboxSelected>>", self.grant_selected)
        self.book = self.ttk.Notebook(self.surface)
        self.book.pack(fill="both", expand=True, padx=8)
        self.review_tab, self.access_tab, self.setup_tab = [self.frame(self.book, padding=6) for _ in range(3)]
        for tab, title in ((self.review_tab, "Review"), (self.access_tab, "Access"), (self.setup_tab, "Private setup")):
            self.book.add(tab, text=title)
        controls = self.frame(self.review_tab)
        controls.pack(side="bottom", fill="x", pady=4)
        self.ttk.Button(controls, text="Review saved note", command=self.review_note).pack(side="left")
        self.publish_button = self.ttk.Button(controls, text="Publish note", command=self.publish_note, state="disabled")
        self.publish_button.pack(side="right")
        self.preview = self.text(self.review_tab)
        self._make_access()
        setup_controls = self.frame(self.setup_tab)
        setup_controls.pack(side="bottom", fill="x", pady=4)
        self.show_setup_button = self.ttk.Button(setup_controls, text="Show private setup", command=self.show_setup)
        self.show_setup_button.pack(side="left")
        self.copy_setup_button = self.ttk.Button(setup_controls, text="Copy setup", command=self.copy_setup, state="disabled")
        self.copy_setup_button.pack(side="right")
        self.setup_preview = self.text(self.setup_tab)
        self.ttk.Button(self.actions, text="Refresh access", command=self.refresh_access).pack(side="left")
        self.clear_setup()
        self.review_note()
        self.refresh_access(quiet=True)
        self._timer = self.root.after(5000, self.poll_access)
        self.show()

    def _make_access(self):
        controls = self.frame(self.access_tab)
        controls.pack(fill="x", pady=4)
        self.lifetime = self.ttk.Combobox(controls, state="readonly", values=("1 hour", "24 hours", "7 days"), width=10)
        self.lifetime.set("24 hours")
        self.lifetime.grid(row=0, column=0, sticky="ew", padx=2)
        self.ttk.Button(controls, text="New grant", command=self.create_grant).grid(row=0, column=1, sticky="ew", padx=2)
        self.remove_record_button = self.ttk.Button(controls, text="Remove record", command=self.remove_record, state="disabled")
        self.remove_record_button.grid(row=1, column=0, sticky="ew", padx=2, pady=4)
        self.remove_grant_button = self.ttk.Button(controls, text="Remove grant", command=self.remove_grant, state="disabled")
        self.remove_grant_button.grid(row=1, column=1, sticky="ew", padx=2, pady=4)
        controls.columnconfigure((0, 1), weight=1)
        listing = self.frame(self.access_tab)
        listing.pack(fill="x")
        self.records = self.ttk.Treeview(listing, columns=("state", "published"), show="tree headings",
                                          height=4, selectmode="browse", style="Journal.Treeview")
        for column, title, width in (("#0", "Frozen note", 180), ("state", "Access", 90), ("published", "Published (UTC)", 130)):
            self.records.heading(column, text=title)
            self.records.column(column, width=width, minwidth=60)
        self.records.pack(side="left", fill="both", expand=True)
        scroll = self.ttk.Scrollbar(listing, orient="vertical", command=self.records.yview)
        scroll.pack(side="right", fill="y")
        self.records.configure(yscrollcommand=scroll.set)
        self.records.bind("<<TreeviewSelect>>", self.record_selected)
        self.access_preview = self.text(self.access_tab)

    def chosen_grant(self):
        index = self.grant_choice.current()
        return self.grants[index] if 0 <= index < len(self.grants) else None

    def clear_setup(self):
        from .task_window import replace_text
        self._setup = self._setup_grant_id = None
        self.copy_setup_button.configure(state="disabled")
        replace_text(self.setup_preview,
            "Show private setup only when configuring a compatible client for this conversation. "
            "It contains a secret token and local paths. Copy setup places them on the system clipboard.\n\n"
            "Provider setup and native conversation binding remain unverified. "
            "Do not attach this grant as a global provider configuration. No provider settings are changed here.")

    def review_note(self):
        from .task_window import replace_text
        self.review = None
        self.publish_button.configure(state="disabled")
        try:
            selection = self.service.review(self.journal_id, self.note_id)
            if selection["source"] != self.source:
                raise ChatError("The note's source conversation changed. Close and reopen Tool access for that saved note.")
            self.review = deepcopy(selection)
            replace_text(self.preview, "EXACT PUBLICATION SELECTION\nSaved: " + selection["saved_at"] + "\n\n" +
                         json.dumps(selection["payload"], ensure_ascii=False, indent=2))
            self.notice.set("Review this frozen selection before Publish note. Grant creation and refresh publish nothing. Runtime authorization is unverified.")
        except ChatError as error:
            replace_text(self.preview, "This note cannot currently be published.\n\n" + str(error) +
                         "\n\nExisting access for its original conversation can still be removed in Access.")
            self.notice.set(str(error))
        self.update_buttons()

    def refresh_access(self, *, grant_id=None, record_id=None, quiet=False):
        if self._closed:
            return
        old = self.chosen_grant()
        previous_id = old["grant_id"] if old else None
        selected = self.records.selection()
        record_id = record_id or (selected[0] if selected else None)
        try:
            self.grants = self.service.for_source(**self.source)
            labels = [f"{grant['state'].replace('_', ' ').title()} · until {when(grant['expires_at'])} · …{grant['grant_id'][-8:]}"
                      for grant in self.grants]
            self.grant_choice.configure(values=labels)
            wanted = grant_id or previous_id
            index = next((i for i, grant in enumerate(self.grants) if grant["grant_id"] == wanted), None)
            if index is None and self.grants:
                index = next((i for i, grant in enumerate(self.grants) if grant["state"] == "active"), 0)
            if index is None:
                self.grant_choice.set("")
            else:
                self.grant_choice.current(index)
            grant = self.chosen_grant()
            if self._setup is not None:
                if not grant or grant["grant_id"] != self._setup_grant_id or grant["state"] != "active":
                    self.clear_setup()
                else:
                    try:
                        if self.service.private_setup(grant["grant_id"]) != self._setup:
                            self.clear_setup()
                    except ChatError:
                        self.clear_setup()
                if self._setup is None:
                    self.notice.set("Private setup hidden because access or its setup changed. Refresh and inspect the grant before showing it again.")
            self.render_records(record_id)
            self.update_buttons()
            if not quiet:
                self.notice.set("Access refreshed locally. Provider connection and authorization remain unverified; no evidence was published.")
            return True
        except ChatError as error:
            self.grants = []
            self.grant_choice.configure(values=())
            self.grant_choice.set("")
            self.clear_setup()
            self.render_records()
            self.update_buttons()
            self.notice.set(str(error))
            return False

    def grant_selected(self, _event=None):
        self.clear_setup()
        self.render_records()
        self.update_buttons()

    def render_records(self, selected=None):
        for key in self.records.get_children():
            self.records.delete(key)
        grant = self.chosen_grant()
        for record in grant["records"] if grant else []:
            self.records.insert("", "end", iid=record["record_id"], text=record["summary"],
                                values=(record["state"].replace("_", " ").title(), when(record["published_at"])))
        choices = self.records.get_children()
        if choices:
            self.records.selection_set(selected if selected in choices else choices[0])
        self.record_selected()

    def selected_record(self):
        grant, selected = self.chosen_grant(), self.records.selection()
        return next((record for record in grant["records"] if selected and record["record_id"] == selected[0]), None) if grant else None

    def record_selected(self, _event=None):
        from .task_window import replace_text
        grant, record = self.chosen_grant(), self.selected_record()
        lines = (["Grant access: " + grant["state"].replace("_", " "), "Expires: " + when(grant["expires_at"])]
                 if grant else ["No grant selected. New grant creates access without publishing the reviewed note."])
        if record:
            lines += ["", record["summary"], "Record access: " + record["state"].replace("_", " "),
                      "Published: " + when(record["published_at"]), "Publication age: " + age(record["published_age_seconds"]),
                      "Snapshot age: " + age(record["snapshot_age_seconds"])]
        lines += ["", "Removing access stops future reads. Already delivered information can remain in provider history.",
                  "Provider connection, native conversation binding, and runtime authorization remain unverified."]
        replace_text(self.access_preview, "\n".join(lines))
        self.remove_record_button.configure(state="normal" if record and record["state"] == "available" else "disabled")

    def update_buttons(self):
        grant = self.chosen_grant()
        active = bool(grant and grant["state"] == "active")
        self.publish_button.configure(state="normal" if active and self.review is not None else "disabled")
        self.show_setup_button.configure(state="normal" if active else "disabled")
        self.remove_grant_button.configure(state="normal" if grant and grant["state"] != "removed" else "disabled")

    def create_grant(self):
        hours = {"1 hour": 1, "24 hours": 24, "7 days": 168}.get(self.lifetime.get())
        try:
            result = self.service.create(**self.source, hours=hours)
            if self.refresh_access(grant_id=result["grant_id"], quiet=True):
                self.notice.set("Grant created. Review the note and press Publish note separately. Private setup is available; provider integration remains unverified.")
        except ChatError as error:
            self.notice.set(str(error))

    def publish_note(self):
        grant = self.chosen_grant()
        if self.review is None or not grant or grant["state"] != "active":
            self.notice.set("Review this saved note and select an active grant first.")
            return
        try:
            result = self.service.publish(grant["grant_id"], self.journal_id, self.note_id, expected=self.review)
            if self.refresh_access(grant_id=grant["grant_id"], record_id=result["record_id"], quiet=True):
                self.notice.set("Reviewed evidence published locally. No provider request was sent; existing publication IDs keep their original age.")
        except ChatError as error:
            self.review = None
            self.update_buttons()
            self.notice.set(str(error))

    def remove_record(self):
        grant, record = self.chosen_grant(), self.selected_record()
        if grant and record:
            self.remove_access(grant["grant_id"], record["record_id"])

    def remove_grant(self):
        grant = self.chosen_grant()
        if grant:
            self.remove_access(grant["grant_id"])

    def remove_access(self, grant_id, record_id=None):
        try:
            self.service.revoke(grant_id, record_id)
            if record_id is None:
                self.clear_setup()
            if self.refresh_access(grant_id=grant_id, record_id=record_id, quiet=True):
                self.notice.set("Future tool access removed. Journal notes and publication snapshots are kept; provider history cannot be erased here.")
        except ChatError as error:
            self.notice.set(str(error))

    def show_setup(self):
        from .task_window import replace_text
        grant = self.chosen_grant()
        if not grant:
            return
        try:
            self._setup = self.service.private_setup(grant["grant_id"])
            self._setup_grant_id = grant["grant_id"]
            replace_text(self.setup_preview, json.dumps(self._setup, ensure_ascii=False, indent=2))
            self.copy_setup_button.configure(state="normal")
            self.notice.set("Private setup is visible locally. It contains a secret; attach it only to this conversation in a compatible client. Integration is unverified.")
        except ChatError as error:
            self.clear_setup()
            self.notice.set(str(error))

    def copy_setup(self):
        grant = self.chosen_grant()
        if self._setup is None or not grant or self._setup_grant_id != grant["grant_id"]:
            return
        try:
            if self.service.private_setup(grant["grant_id"]) != self._setup:
                raise ChatError("Private setup changed. Show it again before copying.")
            self.root.clipboard_clear()
            self.root.clipboard_append(json.dumps(self._setup, ensure_ascii=False, indent=2))
            self.notice.set("Private setup copied to the system clipboard. Keep it local. Provider configuration remains unchanged and integration is unverified.")
        except (ChatError, self.tk.TclError) as error:
            self.clear_setup()
            self.notice.set(str(error) if isinstance(error, ChatError) else "The private setup could not be copied.")

    def poll_access(self):
        if not self._closed:
            self.refresh_access(quiet=True)
            self._timer = self.root.after(5000, self.poll_access)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._timer is not None:
            self.root.after_cancel(self._timer)
        self.clear_setup()
        if self.owner.tool_access is self:
            self.owner.tool_access = None
        self.root.destroy()
