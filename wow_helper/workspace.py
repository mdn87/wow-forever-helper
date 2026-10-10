"""Persistent, independent companion windows managed by the desktop window manager."""

from pathlib import Path
import uuid

from .chat import CHAT_STATE, ChatError, ChatService, read_json, write_json
from .chat_window import ACCENT, BACKGROUND, MUTED, PANEL, TEXT, ChatWindow
from .window_state import LayoutLock, MAX_WINDOWS, MIN_HEIGHT, MIN_WIDTH, display_workareas, window_bounds

LAYOUT_PATH = CHAT_STATE / "windows.json"


class CompanionWindow:
    def __init__(self, manager, record):
        from tkinter import ttk

        self.manager = manager
        self.id = record["id"]
        self.number = record["number"]
        self.kind = record.get("kind", "chooser")
        self.view = None
        self.closed = False
        self.bounds = window_bounds(record.get("bounds"), manager.areas)
        self.caption = ""
        tk = manager.tk
        self.root = tk.Toplevel(manager.root)
        self.root.withdraw()
        self.root.configure(bg=BACKGROUND)
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.topmost = tk.BooleanVar(master=self.root, value=record.get("topmost") is not False)
        self.remember = tk.BooleanVar(master=self.root, value=record.get("remember") is not False)
        self.root.attributes("-topmost", self.topmost.get())
        self.root.protocol("WM_DELETE_WINDOW", lambda: manager.close_window(self))
        self.root.bind("<Configure>", self._configure, add="+")
        self._place()

        bar = tk.Frame(self.root, bg=BACKGROUND, padx=10, pady=10)
        bar.pack(fill="x")
        self.new_button = ttk.Button(bar, text="+ New window", command=lambda: manager.new_window(self))
        self.new_button.pack(side="left")
        switch = ttk.Menubutton(bar, text="Windows")
        switch.pack(side="right")
        self.windows_menu = tk.Menu(switch, tearoff=False)
        switch.configure(menu=self.windows_menu)
        options = ttk.Menubutton(bar, text="Options")
        options.pack(side="right", padx=6)
        self.options_menu = tk.Menu(options, tearoff=False)
        options.configure(menu=self.options_menu)
        self.options_menu.add_checkbutton(label="Keep above other windows", variable=self.topmost,
                                          command=self.set_topmost)
        self.options_menu.add_checkbutton(label="Remember draft and recent chat", variable=self.remember,
                                          command=manager.save_layout)
        self.options_menu.add_separator()
        self.options_menu.add_command(label="Bring all windows to this screen", command=lambda: manager.arrange(self))
        self.options_menu.add_command(label="Close this window", command=lambda: manager.close_window(self))
        self.options_menu.add_separator()
        self.options_menu.add_command(label="Quit companion (keep all windows)", command=manager.close)
        self.notice = tk.StringVar(master=self.root, value="Layout and selected session save automatically.")
        self.notice_label = tk.Label(self.root, textvariable=self.notice, bg=BACKGROUND, fg=MUTED,
                                    anchor="w", justify="left", padx=12, pady=7, wraplength=400,
                                    font=("Segoe UI", 9))
        self.notice_label.pack(side="bottom", fill="x")
        self.body = tk.Frame(self.root, bg=PANEL)
        self.body.pack(fill="both", expand=True)
        if self.kind == "chat":
            self.open_chat(record.get("chat"))
        else:
            self.kind = "chooser"
            self.show_chooser()
        self.root.deiconify()

    def show_chooser(self):
        tk = self.manager.tk
        from tkinter import ttk
        chooser = tk.Frame(self.body, bg=PANEL, padx=24, pady=28)
        chooser.pack(fill="both", expand=True)
        tk.Label(chooser, text="New window", bg=PANEL, fg=TEXT, anchor="w",
                 font=("Segoe UI", 23, "bold")).pack(fill="x")
        tk.Label(chooser, text="Choose what to open here.", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 11), anchor="w").pack(fill="x", pady=(6, 28))
        self.chat_button = ttk.Button(chooser, text="Open agent chat", command=self.open_chat)
        self.chat_button.pack(fill="x")
        tk.Label(chooser, text="Connect this window to an open Codex or Claude Code session.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 10), wraplength=340,
                 justify="left", anchor="w").pack(fill="x", pady=(10, 28))
        tk.Label(chooser, text="PLANNED WINDOW TYPES", bg=PANEL, fg=ACCENT,
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", pady=(12, 10))
        tk.Label(chooser, text="Quest overview\nCharacter status\nScreenshot advice\nCharacter journal",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 11), justify="left",
                 anchor="w").pack(fill="x")
        tk.Label(chooser, text="These window types are not available yet.", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(12, 0))
        self.manager.changed(self)

    def open_chat(self, state=None):
        if self.view is not None or self.closed:
            return
        for child in self.body.winfo_children():
            child.destroy()
        self.kind = "chat"
        self.view = ChatWindow(self.body, self.manager.service_factory(), embedded=True,
                               state=state, on_change=lambda: self.manager.changed(self))
        self.manager.changed(self)

    def set_topmost(self):
        self.root.attributes("-topmost", self.topmost.get())
        self.manager.schedule_save()

    def _place(self):
        b = self.bounds
        # A leading '+' before a negative coordinate means an absolute virtual-screen
        # position in Tk; a plain '-' would anchor to the opposite screen edge.
        self.root.geometry(f"{b['width']}x{b['height']}+{b['x']}+{b['y']}")

    def _configure(self, event):
        if event.widget is not self.root or self.closed:
            return
        if hasattr(self, "notice_label"):
            self.notice_label.configure(wraplength=max(200, event.width - 24))
        if self.root.state() == "normal" and self.root.winfo_width() > 1:
            self.capture_bounds()
            self.manager.schedule_save()

    def capture_bounds(self):
        if self.root.state() == "normal" and self.root.winfo_width() > 1:
            # Top-level x/y give the outer origin, including negative monitor
            # coordinates. rootx/rooty instead include the title bar and border.
            self.bounds = {"width": self.root.winfo_width(), "height": self.root.winfo_height(),
                           "x": self.root.winfo_x(), "y": self.root.winfo_y()}
        return dict(self.bounds)

    def snapshot(self):
        return {"id": self.id, "number": self.number, "kind": self.kind,
                "bounds": self.capture_bounds(), "topmost": self.topmost.get(),
                "remember": self.remember.get(),
                "chat": self.view.snapshot(self.remember.get()) if self.view else {}}

    def dispose(self):
        if self.closed:
            return
        self.closed = True
        if self.view:
            self.view.close()
        self.root.destroy()


class WindowManager:
    def __init__(self, root, *, service_factory=ChatService, layout_path=LAYOUT_PATH, areas=None):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.root = tk, root
        self.service_factory = service_factory
        self.layout_path = Path(layout_path) if layout_path is not None else None
        self.lock = LayoutLock(self.layout_path)
        self.windows = []
        self.closed = False
        self.loading = True
        self._save_after = None
        self.next_number = 1
        self.areas = areas or display_workareas(root)
        root.withdraw()
        root.report_callback_exception = self._callback_error
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        try:
            layout = self._load()
            records = layout.get("windows", [])
            records = records[:MAX_WINDOWS] if isinstance(records, list) else []
            used_ids, used_numbers = set(), set()
            for raw in records:
                if not isinstance(raw, dict) or raw.get("kind") not in ("chat", "chooser"):
                    continue
                record = dict(raw)
                try:
                    record["id"] = str(uuid.UUID(str(record.get("id"))))
                except ValueError:
                    record["id"] = str(uuid.uuid4())
                if record["id"] in used_ids:
                    record["id"] = str(uuid.uuid4())
                number = record.get("number")
                if type(number) is not int or not 1 <= number <= 100_000 or number in used_numbers:
                    number = self.next_number
                record["number"] = number
                used_ids.add(record["id"])
                used_numbers.add(number)
                self.next_number = max(self.next_number, number + 1)
                self._add(record)
            if not self.windows:
                self.new_window(kind="chat")
            self.loading = False
            self.refresh_menus()
            self.schedule_save()
        except Exception:
            for window in self.windows:
                window.dispose()
            self.lock.close()
            raise

    def _load(self):
        if not self.layout_path:
            return {}
        try:
            if self.layout_path.stat().st_size > 16_000_000:
                return {}
        except OSError:
            return {}
        data = read_json(self.layout_path)
        return data if data.get("version") == 1 else {}

    def _add(self, record):
        window = CompanionWindow(self, record)
        self.windows.append(window)
        self.refresh_menus()
        self.schedule_save()
        return window

    def new_window(self, source=None, *, kind="chooser"):
        if self.closed or len(self.windows) >= MAX_WINDOWS:
            return None
        bounds = source.capture_bounds() if source else {}
        if source:
            bounds.update(x=bounds["x"] + 32, y=bounds["y"] + 32)
        record = {"id": str(uuid.uuid4()), "number": self.next_number, "kind": kind,
                  "bounds": bounds, "topmost": source.topmost.get() if source else True,
                  "remember": source.remember.get() if source else True}
        self.next_number += 1
        return self._add(record)

    def changed(self, window):
        if self.closed or window.closed:
            return
        previous = window.caption
        if window.view:
            suffix = window.view.session_title[:50].replace("\n", " ") or "Choose a session"
            if window.view.selection_key and not window.view.selected:
                suffix += " · Disconnected"
            window.caption = f"Chat {window.number} · {suffix}"
        else:
            window.caption = f"Window {window.number} · Choose a window type"
        window.root.title("WoW Companion · " + window.caption)
        if previous != window.caption:
            self.refresh_menus()
        self.schedule_save()

    def refresh_menus(self):
        for window in self.windows:
            window.new_button.configure(state="disabled" if len(self.windows) >= MAX_WINDOWS else "normal")
            window.windows_menu.delete(0, "end")
            for other in self.windows:
                window.windows_menu.add_command(label=other.caption,
                                                 command=lambda w=other: self.reveal(w))
            window.windows_menu.add_separator()
            window.windows_menu.add_command(label="Quit companion (keep all windows)", command=self.close)

    def reveal(self, window):
        if self.closed or window not in self.windows:
            return
        self.areas = display_workareas(self.root)
        window.bounds = window_bounds(window.capture_bounds(), self.areas)
        window._place()
        window.root.deiconify()
        window.root.lift()

    def arrange(self, source):
        """Recover all windows on the source monitor through an explicit menu action."""
        bounds = source.capture_bounds()
        self.areas = display_workareas(self.root)
        area = next((a for a in self.areas if a[0] <= bounds["x"] < a[2]
                     and a[1] <= bounds["y"] < a[3]), self.areas[0])
        for index, window in enumerate(self.windows):
            raw = window.capture_bounds()
            raw.update(x=area[0] + 24 + index * 32, y=area[1] + 24 + index * 32)
            window.bounds = window_bounds(raw, [area])
            window._place()
            window.root.deiconify()
        self.schedule_save()

    def close_window(self, window):
        if self.closed or window not in self.windows:
            return
        if len(self.windows) == 1:
            # The last close exits while remembering that final window.
            self.close()
            return
        self.windows.remove(window)
        window.dispose()
        self.refresh_menus()
        self.save_layout()

    def schedule_save(self):
        if self.loading or self.closed or self.layout_path is None:
            return
        if self._save_after is not None:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(500, self.save_layout)

    def save_layout(self):
        if self.closed:
            return True
        if self._save_after is not None:
            self.root.after_cancel(self._save_after)
            self._save_after = None
        if self.layout_path is None:
            return True
        data = {"version": 1, "windows": [window.snapshot() for window in self.windows]}
        try:
            write_json(self.layout_path, data)
        except OSError:
            for window in self.windows:
                window.notice.set("Could not save windows. Keep the companion open and try again.")
            return False
        else:
            for window in self.windows:
                window.notice.set("Windows saved · recent chat remembered" if window.remember.get()
                                  else "Windows saved · chat text is not remembered")
            return True

    def _callback_error(self, *_):
        for window in self.windows:
            window.notice.set("That action could not finish. Try again or refresh the chat.")

    def close(self):
        if self.closed:
            return
        if not self.save_layout():
            return
        self.closed = True
        for window in self.windows:
            window.dispose()
        self.lock.close()
        self.root.destroy()
