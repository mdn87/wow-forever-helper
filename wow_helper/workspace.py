"""Movable companion panels, each with its own chat connection and worker."""

import math
from pathlib import Path

from .chat import CHAT_STATE, ChatError, ChatService, identifier, read_json, write_json
from .chat_window import ACCENT, BACKGROUND, MUTED, PANEL, TEXT, ChatWindow

LAYOUT_PATH = CHAT_STATE / "workspace.json"
MIN_WIDTH, MIN_HEIGHT = 420, 460
GAP = 12
MAX_PANELS = 8


def panel_bounds(raw):
    """Keep restored and dragged panels a usable size, within a bounded canvas."""
    def number(name, default, lower, upper):
        value = raw.get(name, default)
        return max(lower, min(value, upper)) if type(value) is int else default

    return {"x": number("x", GAP, 0, 16000), "y": number("y", GAP, 0, 16000),
            "width": number("width", 620, MIN_WIDTH, 4000),
            "height": number("height", 620, MIN_HEIGHT, 3000)}


def saved_selection(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("provider"), str) or raw["provider"] not in {"codex", "claude"}:
        return None
    try:
        return raw["provider"], identifier(raw.get("id"))
    except ChatError:
        return None


class ChatPanel:
    def __init__(self, workspace, number, bounds, selection=None):
        from tkinter import ttk

        self.workspace, self.number = workspace, number
        self.bounds = panel_bounds(bounds)
        self.drag_start = None
        tk = workspace.tk
        self.frame = tk.Frame(workspace.canvas, bg=PANEL, highlightthickness=2,
                              highlightbackground="#35505e")
        self.item = workspace.canvas.create_window(self.bounds["x"], self.bounds["y"],
                                                  anchor="nw", window=self.frame,
                                                  width=self.bounds["width"], height=self.bounds["height"])
        self.bar = tk.Frame(self.frame, bg="#263d49", cursor="fleur")
        self.bar.pack(fill="x")
        self.caption = tk.StringVar(master=self.frame, value=f"Chat {number}")
        self.label = tk.Label(self.bar, textvariable=self.caption, bg="#263d49", fg=TEXT,
                              font=("Segoe UI", 10, "bold"), anchor="w", padx=10, pady=8,
                              cursor="fleur")
        self.close_button = ttk.Button(self.bar, text="Close", width=6,
                                       command=lambda: workspace.close_panel(self))
        self.close_button.pack(side="right", padx=4, pady=3)
        self.label.pack(side="left", fill="x", expand=True)
        for widget in (self.bar, self.label):
            widget.bind("<ButtonPress-1>", lambda event: self.start_drag(event, "move"))
            widget.bind("<B1-Motion>", self.drag)
            widget.bind("<ButtonRelease-1>", self.end_drag)

        self.grip = tk.Label(self.frame, text="Resize ↘", anchor="e", bg=PANEL, fg=MUTED,
                             padx=8, font=("Segoe UI", 9), cursor="bottom_right_corner")
        self.grip.pack(side="bottom", fill="x")
        self.grip.bind("<ButtonPress-1>", lambda event: self.start_drag(event, "resize"))
        self.grip.bind("<B1-Motion>", self.drag)
        self.grip.bind("<ButtonRelease-1>", self.end_drag)
        self.body = tk.Frame(self.frame, bg=PANEL)
        self.body.pack(fill="both", expand=True)
        # Never share a provider client or worker between panels: one slow session
        # must not block another, and closing one must not close another's proxy.
        self.view = ChatWindow(self.body, workspace.service_factory(), embedded=True,
                               selection=selection, on_change=lambda: workspace.panel_changed(self))
        self._bind_activation(self.frame)

    def _bind_activation(self, widget):
        widget.bind("<ButtonPress-1>", lambda _event: self.workspace.activate(self), add="+")
        for child in widget.winfo_children():
            self._bind_activation(child)

    def start_drag(self, event, kind):
        self.workspace.activate(self)
        self.drag_start = kind, event.x_root, event.y_root, dict(self.bounds)

    def drag(self, event):
        if self.drag_start is None:
            return
        kind, x, y, original = self.drag_start
        bounds = dict(original)
        first, second = ("x", "y") if kind == "move" else ("width", "height")
        bounds[first] += event.x_root - x
        bounds[second] += event.y_root - y
        self.place(bounds)
        self.workspace.schedule_save()

    def end_drag(self, _event=None):
        self.drag_start = None
        self.workspace.schedule_save()

    def place(self, bounds):
        self.bounds = panel_bounds(bounds)
        canvas = self.workspace.canvas
        canvas.coords(self.item, self.bounds["x"], self.bounds["y"])
        canvas.itemconfigure(self.item, width=self.bounds["width"], height=self.bounds["height"])
        self.workspace.update_scrollregion()

    def snapshot(self):
        selection = self.view.selection_key
        return {**self.bounds, "session": {"provider": selection[0], "id": selection[1]} if selection else None}

    def close(self):
        self.view.close()
        self.workspace.canvas.delete(self.item)
        self.frame.destroy()


class ChatWorkspace:
    def __init__(self, root, *, service_factory=ChatService, layout_path=LAYOUT_PATH):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.root = tk, root
        self.service_factory = service_factory
        self.layout_path = Path(layout_path) if layout_path is not None else None
        self.panels = []
        self.next_number = 1
        self.closed = False
        self._save_after = None
        self.loading = True
        layout = read_json(self.layout_path) if self.layout_path else {}
        if layout.get("version") != 1:
            layout = {}
        window = layout.get("window") if isinstance(layout.get("window"), dict) else {}
        width, height = window.get("width", 1440), window.get("height", 850)
        width = width if type(width) is int else 1440
        height = height if type(height) is int else 850
        width = max(900, min(width, root.winfo_screenwidth() - 80))
        height = max(640, min(height, root.winfo_screenheight() - 100))
        self.initial_size = width, height
        root.title("WoW Forever Helper · Companion workspace")
        root.geometry(f"{width}x{height}")
        root.minsize(900, 640)
        root.configure(bg=BACKGROUND)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))

        header = tk.Frame(root, bg=BACKGROUND, padx=20, pady=14)
        header.pack(fill="x")
        actions = tk.Frame(header, bg=BACKGROUND)
        actions.pack(side="right")
        self.add_button = ttk.Button(actions, text="+ New chat", command=self.add_chat)
        self.add_button.pack(side="left", padx=4)
        ttk.Button(actions, text="Tile chats", command=self.tile).pack(side="left", padx=4)
        menu_button = ttk.Menubutton(actions, text="Panels")
        menu_button.pack(side="left", padx=4)
        self.menu = tk.Menu(menu_button, tearoff=False)
        menu_button.configure(menu=self.menu)
        tk.Label(header, text="Companion workspace", font=("Segoe UI", 20, "bold"),
                 fg=TEXT, bg=BACKGROUND).pack(anchor="w")
        tk.Label(header, text="Drag a chat by its title bar. Resize from its lower-right corner.",
                 font=("Segoe UI", 10), fg=MUTED, bg=BACKGROUND).pack(anchor="w", pady=(4, 0))
        surface = tk.Frame(root, bg=BACKGROUND)
        surface.pack(fill="both", expand=True, padx=8)
        surface.rowconfigure(0, weight=1)
        surface.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(surface, bg=BACKGROUND, highlightthickness=0, xscrollincrement=1,
                                yscrollincrement=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(surface, orient="vertical", command=self.canvas.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(surface, orient="horizontal", command=self.canvas.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.canvas.bind("<Configure>", self._resize)
        self.empty = self.canvas.create_text(GAP * 2, GAP * 2, anchor="nw", fill=MUTED,
                                             font=("Segoe UI", 14), text="Add a chat to choose an agent session.")
        self.status = tk.StringVar(master=root, value="Each panel has its own session. Layout saves automatically.")
        tk.Label(root, textvariable=self.status, bg=BACKGROUND, fg=MUTED, anchor="w",
                 padx=20, pady=6, font=("Segoe UI", 9)).pack(fill="x")
        tk.Label(root, text="Approvals stay in the agent terminal. Chat never sends game keys.",
                 bg=BACKGROUND, fg=MUTED, padx=20, pady=4, font=("Segoe UI", 9)).pack(fill="x")
        root.report_callback_exception = lambda *_: self.status.set("The workspace could not finish that action. Try refreshing the affected chat.")
        saved = layout.get("panels")
        if isinstance(saved, list):
            for raw in saved[:MAX_PANELS]:
                if isinstance(raw, dict):
                    self.add_chat(raw, saved_selection(raw.get("session")))
        else:
            self.add_chat()
            self.add_chat()
            self.tile()
        self.loading = False
        self.update_scrollregion()

    def add_chat(self, bounds=None, selection=None):
        if self.closed or len(self.panels) >= MAX_PANELS:
            return None
        if bounds is None:
            offset = (len(self.panels) % 5) * 32
            bounds = {"x": int(self.canvas.canvasx(0)) + GAP + offset,
                      "y": int(self.canvas.canvasy(0)) + GAP + offset}
        panel = ChatPanel(self, self.next_number, bounds, selection)
        self.next_number += 1
        self.panels.append(panel)
        self.canvas.itemconfigure(self.empty, state="hidden")
        self.add_button.configure(state="disabled" if len(self.panels) >= MAX_PANELS else "normal")
        self.panel_changed(panel)
        self.activate(panel)
        self.update_scrollregion()
        return panel

    def panel_changed(self, panel):
        if self.closed:
            return
        session = panel.view.selected
        suffix = f" · {session.title[:35].replace(chr(10), ' ')}" if session else " · Choose a session"
        if not session and panel.view.selection_key:
            suffix = " · Session unavailable"
        panel.caption.set(f"Chat {panel.number}" + suffix)
        self.menu.delete(0, "end")
        for item in self.panels:
            self.menu.add_command(label=item.caption.get(), command=lambda p=item: self.activate(p, reveal=True))
        self.schedule_save()

    def activate(self, panel, *, reveal=False):
        if self.closed or panel not in self.panels:
            return
        self.canvas.tag_raise(panel.item)
        # Embedded widgets have their own stacking order above canvas graphics.
        panel.frame.lift()
        for other in self.panels:
            other.frame.configure(highlightbackground=ACCENT if other is panel else "#35505e")
        if reveal:
            _, _, width, height = map(float, self.canvas.cget("scrollregion").split())
            self.canvas.xview_moveto(max(0, panel.bounds["x"] - GAP) / width)
            self.canvas.yview_moveto(max(0, panel.bounds["y"] - GAP) / height)

    def close_panel(self, panel):
        if self.closed or panel not in self.panels:
            return
        self.panels.remove(panel)
        panel.close()
        self.add_button.configure(state="normal")
        if not self.panels:
            self.canvas.itemconfigure(self.empty, state="normal")
        self.menu.delete(0, "end")
        for item in self.panels:
            self.menu.add_command(label=item.caption.get(), command=lambda p=item: self.activate(p, reveal=True))
        self.update_scrollregion()
        self.schedule_save()

    def _dimensions(self):
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        return (width if width > 1 else self.initial_size[0] - 36,
                height if height > 1 else self.initial_size[1] - 160)

    def tile(self):
        if self.closed or not self.panels:
            return
        width, height = self._dimensions()
        columns = min(len(self.panels), max(1, (width - GAP) // (MIN_WIDTH + GAP)))
        rows = math.ceil(len(self.panels) / columns)
        panel_width = max(MIN_WIDTH, (width - GAP * (columns + 1)) // columns)
        panel_height = max(MIN_HEIGHT, (height - GAP * (rows + 1)) // rows)
        for index, panel in enumerate(self.panels):
            panel.place({"x": GAP + index % columns * (panel_width + GAP),
                         "y": GAP + index // columns * (panel_height + GAP),
                         "width": panel_width, "height": panel_height})
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.schedule_save()

    def update_scrollregion(self):
        width, height = self._dimensions()
        for panel in self.panels:
            width = max(width, panel.bounds["x"] + panel.bounds["width"] + GAP)
            height = max(height, panel.bounds["y"] + panel.bounds["height"] + GAP)
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def _resize(self, _event=None):
        self.update_scrollregion()
        self.schedule_save()

    def schedule_save(self):
        if self.loading or self.closed or self.layout_path is None:
            return
        if self._save_after is not None:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(500, self.save_layout)

    def save_layout(self):
        if self._save_after is not None:
            self.root.after_cancel(self._save_after)
            self._save_after = None
        if self.layout_path is None:
            return
        width, height = self.root.winfo_width(), self.root.winfo_height()
        if width <= 1 or height <= 1:
            width, height = self.initial_size
        data = {"version": 1, "window": {"width": width, "height": height},
                "panels": [panel.snapshot() for panel in self.panels]}
        try:
            write_json(self.layout_path, data)
        except OSError:
            self.status.set("Could not save the layout. This workspace is still usable.")

    def close(self):
        if self.closed:
            return
        self.save_layout()
        self.closed = True
        for panel in self.panels:
            panel.close()
        self.root.destroy()
