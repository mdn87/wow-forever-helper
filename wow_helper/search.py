"""Bounded search of companion-owned records and already known session labels."""

from itertools import islice
import unicodedata

from .activities import TYPES
from .chat import ChatError
from .journal import JournalService
from .journal_ui import note_summary

MAX_RESULTS = 1000
MAX_INDEX_BYTES = 8_000_000
SETTINGS_ACTIONS = (("interface", "Interface and transparency"), ("layouts", "Activity layouts"),
                    ("appearance", "Chat appearance"), ("setup", "Window setup"),
                    ("build", "Build tutor and experiments"), ("route", "Dungeon route walkthrough"),
                    ("addon", "Addon troubleshooting"),
                    ("goals", "Personal goals and wishlist"),
                    ("history", "Activity history"),
                    ("chain", "Selected quest chain and prerequisites"))


def folded(text):
    return unicodedata.normalize("NFKC", str(text)).casefold()


def matching(rows, query):
    words = folded(query).split()
    return [r for r in rows if all(w in r["search"] for w in words)]


def search_index(manager):
    rows, notices, sessions = [], [], set()

    def add(kind, title, detail, target, body=""):
        if kind != "command" and len(rows) >= MAX_RESULTS - len(TYPES) - len(SETTINGS_ACTIONS):
            notices.append("Search reached its result limit; some records are omitted.")
            return
        rows.append({"kind": kind, "title": title, "detail": detail, "target": target,
                     "body": body or detail, "search": folded(" ".join((kind, title, detail, body)))})

    for window in manager.windows:
        add("window", window.caption, f"Open window {window.number}", window.id)
        if window.card:
            add("window", window.pin["objective"], "Pinned advice", window.id, window.pin["text"])
        views = [window.view] if window.view else list(getattr(window.display, "views", {}).values())
        for view in views:
            for chat in [view, *view.quest_chats.values()]:
                known = [(s.key, s.title, s.project) for s in chat.sessions]
                if chat.selection_key:
                    known.append((chat.selection_key, chat.session_title or "Saved conversation", "Saved reference"))
                for key, title, project in known[:500]:
                    if key not in sessions:
                        sessions.add(key)
                        add("session", title, f"{key[0].title()} · {key[1][:8]} · {project}", key)
            if view.kind == "quests":
                for key, quest in list(view.quest_tree.quests.items())[:200]:
                    add("quest", quest["title"], f"{view.quest_tree.edition} · {quest.get('zone', '')} · Window {window.number}",
                        (window.id, key, view.kind) if window.display else (window.id, key), "\n".join([quest.get("action", ""), *quest.get("remaining", [])]))
    storage = manager.activity_factory().storage
    journal = JournalService(storage)
    directory = storage / "journals"
    total = 0
    for count, path in enumerate(islice(directory.glob("*.json"), 101)):
        if count == 100:
            notices.append("Only the first hundred journals are indexed; use Journal directly for others.")
            break
        if len(rows) >= MAX_RESULTS:
            notices.append("Search reached its result limit; narrow saved content or use Journal directly.")
            break
        try:
            if path.is_symlink() or path.resolve().parent != directory.resolve():
                continue
            total += path.stat().st_size
            if total > MAX_INDEX_BYTES:
                notices.append("Search reached its storage limit; some journals are omitted.")
                break
            data = journal.load(path.stem)
            for entry in data["entries"]:
                if len(rows) >= MAX_RESULTS:
                    notices.append("Some notes are omitted at the search result limit.")
                    break
                title = entry.get('goal', {}).get('title') or entry.get("next_time", {}).get("text") or entry["text"].splitlines()[0][:100]
                detail = f"{data['name']} · {entry['id'][:8]} · {entry['at']}"
                if entry.get("next_time"):
                    detail += " · Next time: " + entry["next_time"]["state"]
                if entry.get('goal'):
                    detail += ' · Manual goal: ' + entry['goal']['state']
                add("goal" if entry.get('goal') else "note", title, detail, (path.stem, entry["id"]), note_summary(entry))
        except (ChatError, OSError):
            notices.append("An unreadable journal was kept and omitted.")
    try:
        for layout in manager.saved_layouts.load()["layouts"]:
            add("layout", layout["name"], f"Saved layout · {len(layout['windows'])} windows", layout["name"])
    except ChatError:
        notices.append("Saved layouts could not be indexed; the file is kept.")
    if hasattr(manager, "activity_history"):
        from .activity_history import LABELS
        try:
            for event in manager.activity_history.entries():
                add("activity", LABELS[event["outcome"]], event["title"], event["id"])
        except ChatError:
            notices.append("Activity history could not be indexed; its file is kept.")
    for kind, (title, _) in TYPES.items():
        add("command", "Open " + title, "New companion window; no opening request", kind)
    for action, title in SETTINGS_ACTIONS:
        add("command", title, "Companion settings", action)
    return rows[:MAX_RESULTS], list(dict.fromkeys(notices))


class SearchDialog:
    def __init__(self, manager, window):
        from tkinter import ttk
        from .theme import palette
        from .window_frame import WindowFrame
        from .task_window import text_box
        self.manager, self.window, self.parent = manager, window, window.root
        tk = manager.tk
        self.root = tk.Toplevel(manager.root)
        self.root.withdraw()
        self.root.title("Search companion")
        self.root.transient(window.root)
        self.root.attributes("-topmost", window.topmost.get())
        self.chrome = WindowFrame(self.root, title="Search companion", close=self.close, minimum=(480, 540))
        self.chrome.place("680x660")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _: self.close())
        surface = self.chrome.content
        colors = palette(self.root)
        bar = tk.Frame(surface, bg=colors.PANEL, padx=12, pady=10)
        bar.pack(fill="x")
        self.query = tk.StringVar(master=self.root)
        self.entry = ttk.Entry(bar, textvariable=self.query)
        self.entry.pack(side="left", fill="x", expand=True)
        ttk.Button(bar, text="Refresh index", command=self.refresh).pack(side="right", padx=(8, 0))
        self.notice = tk.StringVar(master=self.root)
        tk.Label(surface, textvariable=self.notice, bg=colors.PANEL, fg=colors.MUTED,
                 wraplength=440, justify="left", anchor="w").pack(fill="x", padx=12)
        footer = tk.Frame(surface, bg=colors.PANEL, padx=12, pady=10)
        footer.pack(side="bottom", fill="x")
        ttk.Button(footer, text="Close", command=self.close).pack(side="left")
        self.open_button = ttk.Button(footer, text="Open selected", command=self.activate)
        self.open_button.pack(side="right")
        result_area = tk.Frame(surface, bg=colors.PANEL)
        result_area.pack(fill="both", expand=True, padx=12, pady=8)
        self.results = ttk.Treeview(result_area, columns=("context",), show="tree headings", height=8, selectmode="browse")
        self.results.heading("#0", text="Result")
        self.results.heading("context", text="Context")
        self.results.column("#0", width=230)
        self.results.column("context", width=210)
        scroll = ttk.Scrollbar(result_area, command=self.results.yview)
        self.results.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.results.pack(fill="both", expand=True)
        preview_area = tk.Frame(surface, bg=colors.PANEL, height=140)
        preview_area.pack(fill="both", expand=True, padx=12)
        self.preview = text_box(tk, preview_area, bg=colors.PANEL, fg=colors.TEXT, font=("Segoe UI", 10))
        self.preview.configure(height=8)
        self.results.bind("<<TreeviewSelect>>", self.selected)
        self.results.bind("<Double-1>", self.activate)
        self.results.bind("<Return>", self.activate)
        self.entry.bind("<Return>", self.activate)
        self.entry.bind("<Down>", lambda _: self.move(1))
        self.entry.bind("<Up>", lambda _: self.move(-1))
        self.query.trace_add("write", lambda *_: self.filter())
        self.rows, self.matches = [], []
        self.refresh()
        self.root.deiconify()
        self.chrome.apply_native()
        self.entry.focus_set()

    def refresh(self):
        self.rows, notices = search_index(self.manager)
        self.notice.set(" ".join(notices) or "Search saved notes and next steps, known quests and conversations, layouts, or settings.")
        self.filter()

    def filter(self):
        self.matches = matching(self.rows, self.query.get())
        self.results.delete(*self.results.get_children())
        for index, row in enumerate(self.matches):
            self.results.insert("", "end", iid=str(index), text=row["title"], values=(row["detail"],))
        if self.matches:
            self.results.selection_set("0")
            self.results.focus("0")
        self.selected()

    def move(self, direction):
        if self.matches:
            selected = self.results.selection()
            index = min(len(self.matches) - 1, max(0, (int(selected[0]) if selected else 0) + direction))
            self.results.selection_set(str(index))
            self.results.focus(str(index))
            self.results.see(str(index))
            self.selected()
        return "break"

    def note(self, row):
        journal_id, entry_id = row["target"]
        journal = JournalService(self.manager.activity_factory().storage)
        entry = next((e for e in journal.load(journal_id)["entries"] if e["id"] == entry_id), None)
        if entry is None:
            raise ChatError("That note is no longer available. Refresh the index.")
        return entry

    def selected(self, _=None):
        from .task_window import replace_text
        selected = self.results.selection()
        row = self.matches[int(selected[0])] if selected else None
        text, enabled, label = (row["body"], True, "Open selected") if row else ("No matching results.", False, "Open selected")
        if row and row["kind"] == "note":
            try:
                entry = self.note(row)
                text, enabled = note_summary(entry), bool(entry.get("source"))
                label = "Open conversation" if enabled else "Source unavailable"
            except ChatError as error:
                text, enabled = str(error), False
        elif row and row['kind'] == 'goal':
            label = 'Open goal'
        replace_text(self.preview, text)
        self.open_button.configure(text=label, state="normal" if enabled else "disabled")

    def activate(self, _=None):
        selected = self.results.selection()
        if selected:
            try:
                self.open_result(self.matches[int(selected[0])])
            except ChatError as error:
                self.notice.set(str(error))
        return "break"

    def open_result(self, row):
        kind, target = row["kind"], row["target"]
        manager = self.manager
        if kind == "activity":
            manager.show_activity_history(self.window, target)
        elif kind == 'goal':
            if not self.note(row).get('goal'):
                raise ChatError('That goal is no longer available. Refresh the index.')
            view = self.window.view or getattr(self.window.display, 'views', {}).get(getattr(self.window.display, 'active', None))
            if view is None:
                view = manager.open_search_window('journal').view
            view.show_goals(*target)
        elif kind == "note":
            source = self.note(row).get("source")
            if not source:
                raise ChatError("This saved note has no source conversation. Its text remains readable here.")
            manager.resume_conversation(source)
        elif kind == "session":
            manager.resume_conversation({"provider": target[0], "session_id": target[1]})
        elif kind in {"window", "quest"}:
            window_id = target if kind == "window" else target[0]
            window = next((w for w in manager.windows if w.id == window_id), None)
            if window is None:
                raise ChatError("That window is closed. Refresh the index.")
            if kind == "quest":
                view = window.view
                if len(target) > 2:
                    if target[2] not in getattr(window.display, "views", {}):
                        raise ChatError("That activity is closed. Refresh the index.")
                    view = window.display.open_activity(target[2])
                tree = view.quest_tree
                if target[1] not in tree.quests:
                    raise ChatError("That quest changed with the snapshot. Refresh the index.")
                view.book.select(view.panel)
                tree.tree.selection_set(target[1]); tree.tree.focus(target[1]); tree.tree.see(target[1])
            manager.reveal(window)
        elif kind == "layout":
            manager.saved_layouts.get(target)
            manager.show_activity_layouts(self.window)
            manager._layouts_dialog.selected.set(target)
            manager._layouts_dialog.preview()
        elif kind == "command":
            view = self.window.view or getattr(self.window.display, "views", {}).get(getattr(self.window.display, "active", None))
            if target in TYPES:
                manager.open_search_window(target)
            elif target == "interface":
                manager.show_interface(self.window)
            elif target == "layouts":
                manager.show_activity_layouts(self.window)
            elif target == "history":
                manager.show_activity_history(self.window)
            elif target in {"appearance", "setup"} and view:
                (view.show_appearance if target == "appearance" else view.show_setup)()
            elif target in {"build", "route", "addon", "chain", "goals"} and view:
                if target == "chain" and (view.kind != "quests" or view.quest_tree.selected() is None):
                    raise ChatError("Select a quest in a Quest guide window before opening its chain.")
                {"build": view.show_build_tutor, "route": view.show_route_notebook,
                 "addon": view.show_addon_troubleshooting,
                 "chain": view.show_quest_chain, "goals": view.show_goals}[target]()
            else:
                raise ChatError("Open a chat or activity window to use that setting.")
        else:
            raise ChatError("That companion action is unavailable.")
        self.close()

    def close(self):
        self.manager._search_dialog = None
        self.root.destroy()
