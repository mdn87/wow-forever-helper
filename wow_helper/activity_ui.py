"""Quiet activity navigation and explicit retry review."""

from datetime import datetime
import json

from .activity_history import LABELS
from .chat import ChatError
from .theme import palette
from .window_frame import WindowFrame


def research_record(manager, source):
    """Read the referenced report without polling, starting, or retrying research."""
    from .guidance import guidance
    service = guidance(manager.activity_factory().storage)
    try:
        with service.path(source["key"]).open("rb") as stream:
            raw = stream.read(256_001)
        if len(raw) > 256_000:
            raise ValueError
        record = json.loads(raw)
        if not isinstance(record, dict) or record.get("attempt") != source["attempt"]:
            raise ValueError
        return service, record
    except (OSError, ValueError):
        raise ChatError("This research report is unavailable or a newer attempt replaced it. Open Quest guide or Character status to review current research. Nothing was retried.") from None


def research_text(record):
    lines = [str(record.get("kind", "Guide")).title() + " research",
             "Edition: " + str(record.get("edition", "Unknown")),
             "Status: " + str(record.get("status", "Unknown")),
             "Depth: " + str(record.get("tier", "Unknown"))]
    if record.get("error"):
        lines += ["", str(record["error"])]
    guide = record.get("guide")
    if isinstance(guide, dict):
        lines += ["", str(guide.get("summary", ""))]
        lines += [f"{i}. {step}" for i, step in enumerate(guide.get("steps", []), 1)]
        lines += ["Note: " + str(c) for c in guide.get("caveats", [])]
        lines += [str(s.get("title", "Source")) + "\n" + str(s.get("url", "")) for s in guide.get("sources", [])]
        if guide.get("nodes"):
            lines += ["Quest prerequisites and follow-ups:", json.dumps(guide["nodes"], ensure_ascii=False, indent=2)]
    lines += ["", "Original evidence for this request:", json.dumps(record.get("context", {}), ensure_ascii=False, indent=2)]
    return "\n".join(lines)


class ActivityDialog:
    def __init__(self, manager, window):
        from tkinter import ttk
        from .task_window import text_box
        self.manager, self.parent = manager, window.root
        self.store = manager.activity_history
        tk = manager.tk
        self.root = tk.Toplevel(self.parent)
        self.root.withdraw()
        self.root.geometry("660x590")
        self.root.transient(self.parent)
        self.root.attributes("-topmost", self.parent.attributes("-topmost"))
        self.chrome = WindowFrame(self.root, title="Activity history", close=self.close, minimum=(480, 480))
        surface, colors = self.chrome.content, palette(self.parent)
        self.notice = tk.StringVar(master=self.root, value="Opening an item never sends a request. Latest 500 outcomes are retained.")
        tk.Label(surface, textvariable=self.notice, bg=colors.PANEL, fg=colors.TEXT,
                 wraplength=440, justify="left", anchor="w").pack(fill="x", padx=12, pady=8)
        self.show_dismissed = tk.BooleanVar(master=self.root)
        ttk.Checkbutton(surface, text="Include dismissed", variable=self.show_dismissed,
                        command=self.refresh).pack(anchor="w", padx=12)
        footer = tk.Frame(surface, bg=colors.PANEL)
        footer.pack(side="bottom", fill="x", padx=12, pady=10)
        ttk.Button(footer, text="Close", command=self.close).pack(side="right")
        self.dismiss_button = ttk.Button(footer, text="Dismiss", command=self.dismiss)
        self.dismiss_button.pack(side="left")
        self.retry_button = ttk.Button(footer, text="Review retry…", command=self.review_retry)
        self.retry_button.pack(side="left", padx=5)
        self.open_button = ttk.Button(footer, text="Open source", command=self.open_source)
        self.open_button.pack(side="left")
        area = tk.Frame(surface, bg=colors.PANEL)
        area.pack(fill="both", expand=True, padx=12, pady=6)
        self.results = ttk.Treeview(area, columns=("source",), show="tree headings", selectmode="browse", height=5)
        self.results.heading("#0", text="Outcome")
        self.results.heading("source", text="Source")
        self.results.column("#0", width=190, minwidth=150)
        self.results.column("source", width=240, minwidth=140)
        scroll = ttk.Scrollbar(area, command=self.results.yview)
        self.results.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.results.pack(fill="both", expand=True)
        self.details = text_box(tk, surface, bg=colors.PANEL, fg=colors.TEXT, font=("Segoe UI", 10))
        self.details.configure(height=7)
        self.results.bind("<<TreeviewSelect>>", self.selected)
        self.results.bind("<Double-1>", self.open_source)
        self.results.bind("<Return>", self.open_source)
        self.rows, self.signature, self.child = {}, None, None
        self._after = None
        self.refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.deiconify()
        self.chrome.apply_native()
        self._after = self.root.after(1000, self.tick)

    def tick(self):
        self.refresh()
        self._after = self.root.after(1000, self.tick)

    def refresh(self):
        try:
            rows = self.store.entries(self.show_dismissed.get())
        except ChatError as error:
            self.notice.set(str(error))
            return
        if rows == self.signature:
            return
        selected = self.results.selection()
        self.signature = rows
        self.rows = {e["id"]: e for e in rows}
        self.results.delete(*self.results.get_children())
        for e in rows:
            prefix = "Dismissed · " if e["dismissed"] else "New · " if not e["read"] else ""
            self.results.insert("", "end", iid=e["id"], text=prefix + LABELS[e["outcome"]], values=(e["title"],))
        if selected and selected[0] in self.rows:
            self.results.selection_set(selected[0])
        self.selected()

    def selection(self):
        selected = self.results.selection()
        return self.rows.get(selected[0]) if selected else None

    def selected(self, _=None):
        from .task_window import replace_text
        e = self.selection()
        text = "No activity selected. Outcomes appear as the companion observes its requests."
        if e:
            source = e["source"]
            when = datetime.fromtimestamp(e["at"]).astimezone().strftime("%Y-%m-%d %H:%M %Z")
            text = f"{LABELS[e['outcome']]} · {e['title']}\nRequest started: {when}\n"
            text += (f"{source['provider'].title()} conversation · {source['session_id'][:8]}"
                     if source["type"] == "chat" else "Saved research report")
            if e["outcome"] == "received":
                text += "\nA reply is visible; this is not a managed completion receipt."
            if e["outcome"] in {"failed", "interrupted", "cancelled"}:
                text += "\nCheck the original source before retrying; delivery may have been uncertain."
            try:
                actions = [a["action"] for a in self.store.load()["actions"] if a["event"] == e["id"]]
                if actions:
                    text += "\nRecent actions: " + " → ".join(actions[-6:])
            except ChatError as error:
                self.notice.set(str(error))
        replace_text(self.details, text)
        self.open_button.configure(state="normal" if e else "disabled")
        self.dismiss_button.configure(state="normal" if e else "disabled",
                                      text="Restore" if e and e["dismissed"] else "Dismiss")
        self.retry_button.configure(state="normal" if e and e["outcome"] in {"failed", "interrupted", "cancelled"} else "disabled")

    def dismiss(self):
        e = self.selection()
        if e:
            try:
                self.store.act(e["id"], "restore" if e["dismissed"] else "dismiss")
                self.refresh()
            except ChatError as error:
                self.notice.set(str(error))

    def open_source(self, _=None):
        e = self.selection()
        if not e:
            return
        try:
            source = e["source"]
            if source["type"] == "chat":
                self.manager.resume_conversation({k: v for k, v in source.items() if k != "type"})
                self.notice.set("Conversation opened. If unavailable, its saved view explains how to reconnect. Nothing was resent.")
            else:
                _, record = research_record(self.manager, source)
                self.show_review(e, record=record)
            self.store.act(e["id"], "read")
            self.refresh()
        except ChatError as error:
            self.notice.set(str(error))

    def review_retry(self):
        e = self.selection()
        if not e or e["outcome"] not in {"failed", "cancelled", "interrupted"}:
            return
        try:
            if e["source"]["type"] == "research":
                _, record = research_record(self.manager, e["source"])
                self.show_review(e, record=record, retry=True)
            else:
                view = self.manager.resume_conversation({k: v for k, v in e["source"].items() if k != "type"})
                self.show_review(e, view=view, retry=True)
        except ChatError as error:
            self.notice.set(str(error))

    def show_review(self, event, *, record=None, view=None, retry=False):
        if self.child:
            if self.child.event["id"] != event["id"] or self.child.retry != retry:
                raise ChatError("Close the current activity review before opening another. Its draft is kept.")
            self.child.root.lift()
            return
        self.child = ActivityReview(self, event, record=record, view=view, retry=retry)

    def close(self):
        if self._after:
            self.root.after_cancel(self._after)
        if self.child:
            self.child.close()
        self.manager._activity_dialog = None
        self.root.destroy()


class ActivityReview:
    def __init__(self, parent, event, *, record, view, retry):
        from tkinter import ttk
        from .task_window import text_box, replace_text
        self.parent, self.event, self.view = parent, event, view
        self.closed = False
        self.submitted = False
        self.retry = retry
        tk = parent.manager.tk
        self.root = tk.Toplevel(parent.root)
        self.root.geometry("640x520")
        self.root.transient(parent.root)
        self.root.attributes("-topmost", parent.root.attributes("-topmost"))
        self.chrome = WindowFrame(self.root, title="Review retry" if retry else "Research report",
                                  close=self.close, minimum=(480, 420))
        surface, colors = self.chrome.content, palette(parent.root)
        self.notice = tk.StringVar(master=self.root, value="Review the source first. Only Send retry creates a new request. Your conversation draft is kept." if retry else "Saved research; no new request was made.")
        tk.Label(surface, textvariable=self.notice, bg=colors.PANEL, fg=colors.TEXT,
                 wraplength=440, justify="left").pack(fill="x", padx=12, pady=10)
        footer = tk.Frame(surface, bg=colors.PANEL)
        footer.pack(side="bottom", fill="x", padx=12, pady=10)
        ttk.Button(footer, text="Close", command=self.close).pack(side="right")
        self.send_button = ttk.Button(footer, text="Send retry", command=self.send)
        if retry:
            self.send_button.pack(side="left")
        self.text = text_box(tk, surface, bg=colors.PANEL, fg=colors.TEXT, font=("Segoe UI", 10))
        if record is not None:
            replace_text(self.text, research_text(record))
        elif view:
            body = ""
            source = event["source"]
            if view.selected and view.selected.key == (source["provider"], source["session_id"]) and hasattr(view.service, "retry_body"):
                body = view.service.retry_body(view.selected, source["request_id"])
            self.text.insert("1.0", body)
            if not body:
                self.notice.set("The original text is unavailable here. Review the conversation, then enter the request to retry. Your existing draft is kept.")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.chrome.apply_native()

    def send(self):
        if self.submitted or not self.retry:
            return
        source = self.event["source"]
        try:
            if source["type"] == "chat":
                view = self.view
                if view.closed or not view.selected or view.selected.key != (source["provider"], source["session_id"]):
                    raise ChatError("The original conversation is unavailable or still loading. Refresh it before retrying.")
                body = self.text.get("1.0", "end-1c").strip()
                if not body:
                    raise ChatError("Enter and review the request before sending a retry.")
                if view.jobs - {"history", "guides"}:
                    raise ChatError("This conversation is busy. Wait before retrying.")
                self.parent.store.act(self.event["id"], "retry")
                if not view.send_message(body, clear_draft=False):
                    raise ChatError("The retry was not sent. Check the conversation status.")
                self.notice.set("Retry requested. Delivery and completion will appear in the conversation.")
            else:
                service, _ = research_record(self.parent.manager, source)
                # Reuse an existing view's worker so provider startup stays off Tk.
                views = [v for w in self.parent.manager.windows
                         for v in ([w.view] if w.view else list(getattr(w.display, "views", {}).values()))
                         if not v.closed]
                if not views:
                    raise ChatError("Open a chat or activity window before retrying research.")
                view = next((v for v in views if not v.busy), None)
                if view is None:
                    raise ChatError("The companion is busy. Wait before retrying research.")
                self.parent.store.act(self.event["id"], "retry")
                def done(result, error):
                    if not self.closed:
                        self.notice.set(error or "Research retry requested. Its outcome will appear in Activity history.")
                if not view._submit("activity-retry", lambda: service.retry(source["key"], source["attempt"]), on_result=done):
                    raise ChatError("Research retry was not started; the companion is busy.")
                self.notice.set("Requesting research retry…")
            self.submitted = True
            self.send_button.configure(state="disabled")
            self.text.configure(state="disabled")
        except ChatError as error:
            self.notice.set(str(error))

    def close(self):
        self.closed = True
        self.parent.child = None
        self.root.destroy()
