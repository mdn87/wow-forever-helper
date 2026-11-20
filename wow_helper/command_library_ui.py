"""Searchable copy-only reference in the companion's native window style."""

import webbrowser

from .command_library import CATEGORIES, describe, find_commands
from .task_window import replace_text, text_box
from .theme import palette
from .window_frame import WindowFrame
from .window_state import display_workareas, window_bounds


class CommandLibraryDialog:
    def __init__(self, manager, window):
        from tkinter import ttk

        self.manager, self.parent = manager, window.root
        tk = manager.tk
        self.root = tk.Toplevel(manager.root)
        self.root.withdraw()
        self.root.title("Command library")
        self.root.transient(self.parent)
        self.root.attributes("-topmost", self.parent.attributes("-topmost"))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _: self.close())
        self.chrome = WindowFrame(self.root, title="Command library", close=self.close, minimum=(520, 620))
        bounds = window_bounds({"x": self.parent.winfo_x() + 24, "y": self.parent.winfo_y() + 24,
                                "width": 760, "height": 780}, display_workareas(self.root), (520, 620))
        self.chrome.place(f"{bounds['width']}x{bounds['height']}+{bounds['x']}+{bounds['y']}")
        colors = palette(self.root)
        body = tk.Frame(self.chrome.content, bg=colors.PANEL, padx=12, pady=10)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="WoW Forever commands", bg=colors.PANEL, fg=colors.TEXT,
                 font=("Segoe UI", 16), anchor="w").pack(fill="x")
        intro = tk.Label(body, text="Find a setting, copy its command, then paste it into WoW chat. "
                        "Experimental values are not verified maximums.", bg=colors.PANEL, fg=colors.MUTED,
                        wraplength=640, justify="left", anchor="w")
        intro.pack(fill="x", pady=(4, 10))
        tk.Label(body, text="Search by setting, effect, or symptom", bg=colors.PANEL,
                 fg=colors.TEXT, anchor="w").pack(fill="x")
        self.query = tk.StringVar(master=self.root)
        self.entry = ttk.Entry(body, textvariable=self.query)
        self.entry.pack(fill="x", pady=(4, 8))
        self.category = tk.StringVar(master=self.root, value=CATEGORIES[0])
        self.category_choice = ttk.Combobox(body, textvariable=self.category,
                                           values=CATEGORIES, state="readonly")
        self.category_choice.pack(fill="x", pady=(0, 8))
        listing = tk.Frame(body, bg=colors.PANEL)
        listing.pack(fill="x")
        self.results = ttk.Treeview(listing, columns=("status",), show="tree headings",
                                    height=6, selectmode="browse")
        self.results.heading("#0", text="Command")
        self.results.heading("status", text="Evidence / requirement")
        self.results.column("#0", width=300, minwidth=170)
        self.results.column("status", width=155, minwidth=115)
        scroll = ttk.Scrollbar(listing, command=self.results.yview)
        self.results.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.results.pack(fill="both", expand=True)
        self.results.bind("<<TreeviewSelect>>", self.selected)

        footer = tk.Frame(body, bg=colors.PANEL)
        footer.pack(side="bottom", fill="x", pady=(8, 0))
        self.notice = tk.StringVar(master=self.root)
        notice = tk.Label(footer, textvariable=self.notice, bg=colors.PANEL, fg=colors.MUTED,
                          anchor="w", justify="left", wraplength=640)
        notice.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        self.copy_command = ttk.Button(footer, text="Copy command", command=lambda: self.copy("command"))
        self.copy_inspect = ttk.Button(footer, text="Copy read value", command=lambda: self.copy("inspect"))
        self.copy_restore = ttk.Button(footer, text="Copy reset", command=lambda: self.copy("restore"))
        for index, button in enumerate((self.copy_command, self.copy_inspect, self.copy_restore)):
            button.grid(row=1, column=index, sticky="ew", padx=2)
        self.source_button = ttk.Button(footer, text="Open source", command=self.open_source)
        self.source_button.grid(row=2, column=0, sticky="ew", padx=2, pady=(6, 0))
        ttk.Button(footer, text="Close", command=self.close).grid(row=2, column=2, sticky="ew", padx=2, pady=(6, 0))
        footer.columnconfigure((0, 1, 2), weight=1, uniform="actions")
        preview_area = tk.Frame(body, bg=colors.PANEL)
        preview_area.pack(fill="both", expand=True, pady=(8, 0))
        self.preview = text_box(tk, preview_area, bg=colors.EDITOR, fg=colors.TEXT,
                                font=("Segoe UI", 10))
        body.bind("<Configure>", lambda event: (intro.configure(wraplength=max(200, event.width - 24)),
                                                notice.configure(wraplength=max(200, event.width - 24))))
        self.query.trace_add("write", self.refresh)
        self.category.trace_add("write", self.refresh)
        self.refresh()
        self.root.deiconify()
        self.chrome.apply_native()

    def current(self):
        selection = self.results.selection()
        return next((entry for entry in self.matches if selection and entry.key == selection[0]), None)

    def refresh(self, *_):
        current = self.current().key if hasattr(self, "matches") and self.current() else None
        self.matches = find_commands(self.query.get(), self.category.get())
        self.results.delete(*self.results.get_children())
        for entry in self.matches:
            self.results.insert("", "end", iid=entry.key, text=entry.title, values=(entry.status,))
        if self.matches:
            key = current if any(entry.key == current for entry in self.matches) else self.matches[0].key
            self.results.selection_set(key)
            self.results.see(key)
        self.notice.set(f"{len(self.matches)} commands · Copy a line to use it in game.")
        self.selected()

    def selected(self, _=None):
        entry = self.current()
        replace_text(self.preview, describe(entry) if entry else "No matching commands. Clear the search or choose another category.")
        for button, field in ((self.copy_command, "command"), (self.copy_inspect, "inspect"),
                              (self.copy_restore, "restore"), (self.source_button, "source")):
            button.configure(state="normal" if entry and getattr(entry, field) else "disabled")

    def copy(self, field):
        entry = self.current()
        value = getattr(entry, field) if entry else ""
        if not value:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
        except self.manager.tk.TclError:
            self.notice.set("Could not copy. Select the command text and copy it manually.")
            return
        label = {"command": "command", "inspect": "read-value command", "restore": "reset-to-default command"}[field]
        self.notice.set(f"Copied {label}. Paste it into WoW chat when ready.")

    def open_source(self):
        entry = self.current()
        if entry:
            try:
                opened = webbrowser.open(entry.source)
            except (OSError, webbrowser.Error):
                opened = False
            self.notice.set("Opened source in your browser." if opened else "Could not open browser. The source URL is in the details.")

    def close(self):
        self.manager._command_library_dialog = None
        self.root.destroy()
