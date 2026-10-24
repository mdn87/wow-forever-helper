"""Two local companion displays: saved quest information and resumable activities."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import math
import time
import uuid

from .activities import FLAVORS, profile_settings
from .chat import ChatError
from .task_window import TaskWindow, replace_text
from .theme import palette, display_font

DISPLAY_TYPES = {"questlog": "Quest log", "activities": "Activity cards"}
ACTIVITIES = {
    "quests": ("Quest help", "Work through a quest and keep its conversation."),
    "character": ("Gear check", "Review equipment and discuss an upgrade."),
    "screen": ("Screen adviser", "Review an image and ask about what you see."),
    "journal": ("Journal / Resume", "Keep notes and return to saved advice."),
}


def display_state(kind, raw):
    """Refuse unsupported state before a startup save can replace it."""
    if raw is None:
        raw = {"version": 1}
    try:
        if not isinstance(raw, dict) or type(raw.get("version")) is not int or raw["version"] != 1:
            raise ValueError
        if len(json.dumps(raw, allow_nan=False).encode("utf-8")) > 2_000_000:
            raise ValueError
        state = deepcopy(raw)
        if kind == "activities":
            if state.get("active") not in (None, *ACTIVITIES) or state.get("last") not in (None, *ACTIVITIES):
                raise ValueError
            states = state.setdefault("states", {})
            if not isinstance(states, dict) or set(states) - set(ACTIVITIES):
                raise ValueError
            if any(not isinstance(v, dict) for v in states.values()):
                raise ValueError
        else:
            if state.get("flavor", "_classic_beta_") not in FLAVORS.values():
                raise ValueError
            rows = state.setdefault("rows", [])
            if not isinstance(rows, list) or len(rows) > 500:
                raise ValueError
            for row in rows:
                if (not isinstance(row, dict) or set(row) != {"title", "detail"}
                        or any(not isinstance(v, str) or len(v) > 16_000 for v in row.values())):
                    raise ValueError
            saved = state.get("saved_at")
            if saved is not None and (type(saved) not in (int, float) or not math.isfinite(saved) or saved < 0):
                raise ValueError
            if not isinstance(state.get("summary", ""), str) or len(state.get("summary", "")) > 16_000:
                raise ValueError
            if type(state.get("selected", 0)) is not int:
                raise ValueError
        return state
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ChatError("Saved companion display state is damaged or unsupported. The existing layout is kept.") from None


class ActivityDeck:
    def __init__(self, window, raw=None):
        from tkinter import ttk
        self.window, self.manager = window, window.manager
        self.root, self.tk = window.body, window.manager.tk
        self.state = display_state("activities", raw)
        self.views, self.hosts = {}, {}
        self.active, self.last = None, self.state.get("last")
        self.closed = False
        colors = palette(self.root)
        bar = self.tk.Frame(self.root, bg=colors.PANEL, padx=12, pady=10)
        bar.pack(fill="x")
        self.toggle = ttk.Button(bar, text="Activity cards", command=self.toggle_view, padding=12)
        self.toggle.pack(side="left")
        ttk.Button(bar, text="Return to Dias", command=self.manager.return_to_dias, padding=12).pack(side="right")
        self.title = self.tk.Label(self.root, text="Choose an activity", bg=colors.PANEL,
                                  fg=colors.TEXT, font=display_font(self.root, 20), anchor="w", padx=16)
        self.title.pack(fill="x")
        self.content = self.tk.Frame(self.root, bg=colors.PANEL)
        self.content.pack(fill="both", expand=True)
        self.cards = self.tk.Frame(self.content, bg=colors.PANEL, padx=12, pady=12)
        self.buttons = {}
        for n, (kind, (title, description)) in enumerate(ACTIVITIES.items()):
            button = self.tk.Button(self.cards, text=f"{title}\n\n{description}",
                                    command=lambda k=kind: self.open_activity(k),
                                    bg=colors.EDITOR, fg=colors.TEXT,
                                    activebackground=colors.HOVER, activeforeground=colors.ACCENT,
                                    relief="solid", borderwidth=1, highlightthickness=1,
                                    highlightbackground=colors.EDGE, highlightcolor=colors.ACCENT,
                                    font=("Segoe UI", 14), wraplength=200, padx=12, pady=18)
            button.grid(row=n // 2, column=n % 2, sticky="nsew", padx=6, pady=6)
            self.buttons[kind] = button
        for n in range(2):
            self.cards.columnconfigure(n, weight=1, uniform="cards")
            self.cards.rowconfigure(n, weight=1, uniform="cards")
        self.cards.bind("<Configure>", self._resize)
        if self.state.get("active"):
            self.open_activity(self.state["active"])
        else:
            self.show_cards()

    def _resize(self, event):
        for button in self.buttons.values():
            button.configure(wraplength=max(100, event.width // 2 - 62))

    def open_activity(self, kind):
        if self.closed or kind not in ACTIVITIES:
            return None
        if not self.manager.loading:
            self.manager.record_usage(kind, "open")
        if kind not in self.views:
            state = deepcopy(self.state["states"].get(kind, {}))
            # Card navigation restores work; it never starts report preparation.
            state.setdefault("activity", {})
            if kind == "quests" and "profile" not in state:
                state["profile"] = profile_settings(kind, {"guide_auto": False})
            host = self.tk.Frame(self.content, bg=palette(self.root).PANEL)
            toolbar = self.tk.Frame(host, bg=palette(self.root).PANEL, padx=8, pady=4)
            toolbar.pack(fill="x")
            body = self.tk.Frame(host, bg=palette(self.root).PANEL)
            body.pack(fill="both", expand=True)
            view = TaskWindow(body, self.manager.service_factory(), embedded=True, kind=kind,
                              activity=self.manager.activity_factory(),
                              window_id=str(uuid.uuid5(uuid.UUID(self.window.id), kind)),
                              service_factory=self.manager.service_factory,
                              resume_conversation=self.manager.resume_conversation,
                              pin_advice=self.manager.pin_advice, state=state, toolbar=toolbar,
                              on_change=lambda: self.manager.changed(self.window))
            self.views[kind], self.hosts[kind] = view, host
            cached = state.get("display_report")
            if kind in ("quests", "character") and isinstance(cached, dict) and kind in cached:
                try:
                    from . import character, quests
                    report = cached[kind]
                    saved_at = report.get("snapshot_at")
                    if type(saved_at) not in (int, float) or not math.isfinite(saved_at):
                        raise ValueError
                    report["data"]["age_seconds"] = max(0, int(time.time() - saved_at))
                    report["text"] = (quests if kind == "quests" else character).as_text(report["data"])
                    view._report_result(cached, None)
                    view.activity_notice.set("Saved report restored; Refresh reads the latest export. "
                                             f"Snapshot age: {report['data']['age_seconds'] // 60} minutes.")
                except (ValueError, TypeError, KeyError, AttributeError):
                    view.activity_notice.set("Saved report unavailable. Refresh to read it again; your drafts are kept.")
        self.cards.pack_forget()
        for host in self.hosts.values():
            host.pack_forget()
        self.hosts[kind].pack(fill="both", expand=True)
        self.active = self.last = kind
        self.title.configure(text=ACTIVITIES[kind][0])
        self.toggle.configure(text="Activity cards", state="normal")
        self.manager.changed(self.window)
        return self.views[kind]

    def show_cards(self):
        for host in self.hosts.values():
            host.pack_forget()
        self.active = None
        self.cards.pack(fill="both", expand=True)
        self.title.configure(text="Choose an activity")
        self.toggle.configure(text="Resume " + ACTIVITIES[self.last][0] if self.last else "Resume activity",
                              state="normal" if self.last else "disabled")
        for kind, button in self.buttons.items():
            title, description = ACTIVITIES[kind]
            resume = kind in self.views or kind in self.state["states"]
            button.configure(text=f"{title}\n\n{description}\n\n{'Resume' if resume else 'Open'}")
        self.manager.changed(self.window)

    def toggle_view(self):
        if self.active:
            self.show_cards()
        elif self.last:
            self.open_activity(self.last)

    def snapshot(self, remember=True):
        # Instantiate saved-but-unopened views only when selected, never on save.
        states = deepcopy(self.state["states"])
        for kind, view in self.views.items():
            states[kind] = view.snapshot(remember)
            if kind in ("quests", "character") and view.panel_report:
                states[kind]["display_report"] = deepcopy(view.panel_report)
        if not remember:
            for state in states.values():
                for key in ("draft", "messages", "pending", "response_waits"):
                    state.pop(key, None)
                if isinstance(state.get("activity"), dict):
                    state["activity"].pop("notebooks", None)
        return display_state("activities", dict(version=1, active=self.active, last=self.last, states=states))

    def close(self):
        self.closed = True
        for view in self.views.values():
            view.close()


class QuestLogDisplay:
    """A saved report browser with no provider connection or automatic research."""
    def __init__(self, window, raw=None):
        from tkinter import ttk
        self.window, self.manager = window, window.manager
        self.root, self.tk = window.body, window.manager.tk
        state = display_state("questlog", raw)
        self.activity = self.manager.activity_factory()
        self.rows, self.saved_at = state["rows"], state.get("saved_at")
        self.summary = state.get("summary", "Read a saved snapshot to see your quests.")
        self.flavor = state.get("flavor", "_classic_beta_")
        self.selected = state.get("selected", 0)
        self.closed, self.busy = False, False
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quest-display")
        self.future = None
        colors = palette(self.root)
        bar = self.tk.Frame(self.root, bg=colors.PANEL, padx=12, pady=10)
        bar.pack(fill="x")
        self.read_button = ttk.Button(bar, text="Read saved snapshot", command=self.refresh, padding=12)
        self.read_button.pack(side="left")
        ttk.Button(bar, text="Return to Dias", command=self.manager.return_to_dias, padding=12).pack(side="right")
        self.edition = self.tk.StringVar(value=next(k for k, v in FLAVORS.items() if v == self.flavor))
        self.picker = ttk.Combobox(self.root, textvariable=self.edition, values=list(FLAVORS), state="readonly")
        self.picker.pack(fill="x", padx=12, pady=5)
        self.picker.bind("<<ComboboxSelected>>", self.change_edition)
        self.age = self.tk.Label(self.root, bg=colors.PANEL, fg=colors.ACCENT,
                                 anchor="w", justify="left", padx=12, font=("Segoe UI", 12))
        self.age.pack(fill="x", pady=6)
        body = self.tk.Frame(self.root, bg=colors.PANEL)
        body.pack(fill="both", expand=True, padx=12)
        self.list = self.tk.Listbox(body, height=5, font=("Segoe UI", 17), activestyle="dotbox",
                                   bg=colors.BACKGROUND, fg=colors.TEXT, selectbackground=colors.SELECT,
                                   selectforeground=colors.TEXT, exportselection=False, selectborderwidth=9)
        scroll = ttk.Scrollbar(body, command=self.list.yview)
        scroll.pack(side="right", fill="y")
        self.list.configure(yscrollcommand=scroll.set)
        self.list.pack(fill="both", expand=True)
        self.list.bind("<<ListboxSelect>>", lambda _: self.select_row(self.list.curselection()[0])
                       if self.list.curselection() else None)
        detail_frame = self.tk.Frame(self.root, bg=colors.PANEL)
        detail_frame.pack(fill="both", expand=True, padx=12, pady=8)
        self.detail = self.tk.Text(detail_frame, height=5, width=1, wrap="word", font=("Segoe UI", 13),
                                   bg=colors.PANEL, fg=colors.TEXT, relief="flat", padx=8, pady=8)
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.detail.yview)
        detail_scroll.pack(side="right", fill="y")
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.pack(fill="both", expand=True)
        self.notice = self.tk.Label(self.root, text=self.summary, bg=colors.PANEL, fg=colors.MUTED,
                                    anchor="w", justify="left", padx=12, pady=8, wraplength=400)
        self.notice.pack(fill="x")
        self.root.bind("<Configure>", lambda e: self.notice.configure(wraplength=max(200, e.width - 30)), add="+")
        self.render()
        self._after = self.root.after(100, self.tick)

    def change_edition(self, _event=None):
        self.flavor = FLAVORS[self.edition.get()]
        self.rows, self.saved_at, self.selected = [], None, 0
        self.summary = "Edition changed. Read its saved snapshot."
        self.render()
        self.manager.changed(self.window)

    def refresh(self):
        if self.busy or self.closed:
            return
        self.busy = True
        self.read_flavor = self.flavor
        self.read_button.configure(state="disabled")
        self.notice.configure(text="Reading saved snapshot…")
        self.future = self.worker.submit(self.activity.reports, ["quests"], self.flavor)

    def tick(self):
        if self.closed:
            return
        if self.future and self.future.done():
            try:
                report = self.future.result()["quests"]
                if self.read_flavor == self.flavor:
                    self.load_report(report)
            except Exception:
                self.notice.configure(text="Could not read the snapshot. Previous data is kept with its original age; try again.")
            finally:
                self.future, self.busy = None, False
                self.read_button.configure(state="normal")
        if self.saved_at is None:
            text = "Snapshot time unknown · reload in WoW to save current data"
        else:
            minutes = max(0, int(time.time() - self.saved_at)) // 60
            text = f"Saved {minutes} minutes ago · {'stale' if minutes >= 15 else 'saved snapshot, not live'}"
        self.age.configure(text=text)
        self._after = self.root.after(250, self.tick)

    def load_report(self, report):
        data = report["data"]
        rows = []
        for quest in data["plan"][:400]:
            detail = "\n".join([quest["title"], quest.get("zone") or "Zone unknown", "",
                                 *quest.get("remaining", []), "", *quest.get("notes", [])])
            rows.append(dict(title=f"{quest['action'].title()} · {quest['title']}", detail=detail[:16_000]))
        for quest in (data.get("available") or [])[:100]:
            rows.append(dict(title="Pickup · " + quest["title"],
                             detail="Not in your saved quest log. Available in the last snapshot; current availability is unverified."))
        summary = f"{data['quest_count']} saved quests. " + " ".join(data.get("warnings", []))
        if data.get("available") is None:
            summary += " Nearby pickups are unavailable for this snapshot."
        candidate = display_state("questlog", dict(version=1, rows=rows, saved_at=report.get("snapshot_at"),
                                                   flavor=self.flavor, summary=summary, selected=0))
        self.rows, self.saved_at, self.summary = candidate["rows"], candidate["saved_at"], candidate["summary"]
        self.selected = 0
        self.render()
        self.manager.changed(self.window)

    def render(self):
        self.list.delete(0, "end")
        for row in self.rows:
            self.list.insert("end", row["title"])
        self.notice.configure(text=self.summary)
        if self.rows:
            self.select_row(max(0, min(self.selected, len(self.rows) - 1)))
        else:
            replace_text(self.detail, "No saved quest details to show. Read the selected edition's snapshot.")

    def select_row(self, index):
        if 0 <= index < len(self.rows):
            self.selected = index
            self.list.selection_clear(0, "end")
            self.list.selection_set(index)
            replace_text(self.detail, self.rows[index]["detail"])
            self.manager.changed(self.window)

    def snapshot(self, remember=True):
        return display_state("questlog", dict(version=1, rows=self.rows, saved_at=self.saved_at,
                                              flavor=self.flavor, summary=self.summary, selected=self.selected))

    def close(self):
        self.closed = True
        self.root.after_cancel(self._after)
        self.worker.shutdown(wait=False)


def show_display_setup(manager, parent):
    """Explicitly select two screens; never infer that the game monitor is free."""
    from tkinter import ttk
    from .window_state import display_workareas
    tk = manager.tk
    areas = display_workareas(manager.root)
    dialog = tk.Toplevel(parent)
    dialog.title("WoW companion displays")
    dialog.geometry("560x360")
    colors = palette(parent)
    dialog.configure(bg=colors.PANEL)
    tk.Label(dialog, text="Choose a different screen for each view.\nThese helper windows temporarily sit above Dias.",
             bg=colors.PANEL, fg=colors.TEXT, font=("Segoe UI", 12), justify="left").pack(padx=18, pady=18)
    labels = [f"Screen {n + 1} · {a[2] - a[0]} × {a[3] - a[1]}" for n, a in enumerate(areas)]
    picks = []
    for title in ("Quest log", "Activity cards"):
        tk.Label(dialog, text=title, bg=colors.PANEL, fg=colors.TEXT).pack(anchor="w", padx=18)
        picker = ttk.Combobox(dialog, values=labels, state="readonly")
        picker.pack(fill="x", padx=18, pady=(4, 12))
        picks.append(picker)
    notice = tk.Label(dialog, bg=colors.PANEL, fg=colors.ACCENT, wraplength=510)
    notice.pack(fill="x", padx=18)
    def apply():
        try:
            if any(p.current() < 0 for p in picks):
                raise ChatError("Choose both screens first.")
            manager.open_wow_displays(*(areas[p.current()] for p in picks))
        except ChatError as error:
            notice.configure(text=str(error))
        else:
            dialog.destroy()
    ttk.Button(dialog, text="Open WoW displays", command=apply, padding=10).pack(side="right", padx=18, pady=12)
    ttk.Button(dialog, text="Cancel", command=dialog.destroy, padding=10).pack(side="right", pady=12)
