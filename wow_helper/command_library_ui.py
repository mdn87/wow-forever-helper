"""Searchable copy-only reference in the companion's native window style."""

import webbrowser
from urllib.parse import quote_plus

from .command_library import CATEGORIES, describe, find_commands
from .task_window import replace_text, text_box
from .theme import palette
from .window_frame import setup_dialog


class CommandLibraryDialog:
    def __init__(self, manager, window):
        from tkinter import ttk

        self.manager, self.parent = manager, window.root
        self.window, self.research_dialog = window, None
        tk = manager.tk
        self.root = tk.Toplevel(manager.root)
        self.root.withdraw()
        self.chrome = setup_dialog(self.root, self.parent, title="Command library", close=self.close,
                                   minimum=(520, 620), size=(760, 780))
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
        search = ttk.Frame(body)
        search.pack(fill="x", pady=(4, 8))
        self.query = tk.StringVar(master=self.root)
        self.entry = ttk.Entry(search, textvariable=self.query)
        self.entry.pack(side='left', fill='x', expand=True)
        self.research_button = ttk.Button(search, text='Search online…', command=self.research)
        self.research_button.pack(side='right', padx=(6, 0))
        self.entry.bind('<Return>', self.activate)
        self.entry.bind('<KP_Enter>', self.activate)
        self.entry.bind('<Control-Return>', self.research)
        self.entry.bind('<Control-KP_Enter>', self.research)
        self.root.bind('<Control-Return>', self.research)
        self.entry.bind('<Down>', lambda _: self.move(1))
        self.entry.bind('<Up>', lambda _: self.move(-1))
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
        self.results.bind("<Double-1>", lambda _: self.copy("command"))
        self.results.bind("<Return>", lambda _: self.copy("command"))

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
        self.browser_button = ttk.Button(footer, text='Search in browser', command=self.search_in_browser)
        self.browser_button.grid(row=2, column=1, sticky='ew', padx=2, pady=(6, 0))

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
        self.entry.focus_set()

    def move(self, direction):
        if self.matches:
            current = self.current()
            index = next((i for i, e in enumerate(self.matches) if current and e.key == current.key), 0)
            target = self.matches[min(len(self.matches) - 1, max(0, index + direction))].key
            self.results.selection_set(target)
            self.results.focus(target)
            self.results.see(target)
            self.selected()
        return "break"

    def activate(self, _event=None):
        if self.matches and self.current() is not None:
            self.copy("command", suffix=" (Ctrl+Enter searches online.)")
            return "break"
        return self.research(_event)

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
        if self.query.get().strip():
            self.notice.set(f"{len(self.matches)} library matches · Enter copies selected · Ctrl+Enter searches online."
                            if self.matches else "0 library matches · Enter reviews an online search with your agent.")
        else:
            self.notice.set(f"{len(self.matches)} library commands")
        self.browser_button.state(['!disabled'] if self.query.get().strip() else ['disabled'])
        self.selected()

    def selected(self, _=None):
        entry = self.current()
        replace_text(self.preview, describe(entry) if entry else
                     "No matching commands in the library. Use Search online to ask your agent to look up the answer.")
        for button, field in ((self.copy_command, "command"), (self.copy_inspect, "inspect"),
                              (self.copy_restore, "restore"), (self.source_button, "source")):
            button.configure(state="normal" if entry and getattr(entry, field) else "disabled")

    def copy(self, field, *, suffix=""):
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
        self.notice.set(f"Copied {label}. Paste it into WoW chat when ready.{suffix}")

    def open_source(self):
        entry = self.current()
        if entry:
            try:
                opened = webbrowser.open(entry.source)
            except (OSError, webbrowser.Error):
                opened = False
            self.notice.set("Opened source in your browser." if opened else "Could not open browser. The source URL is in the details.")

    def search_in_browser(self):
        from .voice_browser import SEARCH
        question = self.query.get().strip()
        if not question:
            return
        url = SEARCH['web'].format(quote_plus('World of Warcraft ' + question))
        try:
            opened = webbrowser.open(url)
        except (OSError, webbrowser.Error):
            opened = False
        self.notice.set('Opened web results in your browser.' if opened else 'Could not open your browser.')

    def research(self, _event=None):
        opening = self.research_dialog is None or self.research_dialog.view.closed
        if opening:
            from .command_research_ui import CommandResearchDialog
            if self.research_dialog:
                self.research_dialog.close()
            window = self.window
            if not window.view:
                window = next((w for w in self.manager.windows if w.kind == 'chat' and w.view), None)
                window = window or self.manager.new_window(self.window, kind='chat')
            if window is None:
                self.notice.set('Open a chat window to search online with an agent.')
                return 'break'
            self.research_dialog = CommandResearchDialog(self, window)
        dialog = self.research_dialog
        dialog.root.lift()
        question = self.query.get().strip()
        changed = question != dialog.query.get().strip()
        if changed:
            dialog.query.set(question)
        if question and dialog.view.selected and (opening or changed):
            dialog.prepare()
        dialog.query_entry.focus_set()
        return 'break'

    def close(self):
        if self.research_dialog is not None:
            self.research_dialog.close()
        self.manager._command_library_dialog = None
        self.root.destroy()
