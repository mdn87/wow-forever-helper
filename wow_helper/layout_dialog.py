"""Explicit save and preview controls for named companion arrangements."""

from .chat import ChatError
from .activities import TYPES
from .theme import palette
from .window_frame import WindowFrame
from .window_state import display_workareas, window_bounds


class LayoutDialog:
    def __init__(self, manager, parent):
        import tkinter as tk
        from tkinter import ttk

        self.manager, self.parent = manager, parent
        self.plan = None
        self.root = tk.Toplevel(manager.root)
        self.root.withdraw()
        self.root.title("Activity layouts")
        self.root.transient(parent)
        self.root.attributes("-topmost", parent.attributes("-topmost"))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _: self.close())
        self.chrome = WindowFrame(self.root, title="Activity layouts", close=self.close, minimum=(480, 540))
        bounds = window_bounds({"x": parent.winfo_x() + 24, "y": parent.winfo_y() + 24,
                                "width": 540, "height": 620}, display_workareas(self.root), (480, 540))
        self.chrome.place(f"{bounds['width']}x{bounds['height']}+{bounds['x']}+{bounds['y']}")
        colors = palette(self.root)
        body = tk.Frame(self.chrome.content, bg=colors.PANEL, padx=16, pady=12)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Save a space for each activity", font=("Segoe UI", 16),
                 bg=colors.PANEL, fg=colors.TEXT, anchor="w").pack(fill="x")
        tk.Label(body, text="Restore window positions and view settings. Current conversations and drafts stay in place; other open windows stay accessible.",
                 wraplength=440, justify="left", anchor="w", font=("Segoe UI", 10),
                 bg=colors.PANEL, fg=colors.MUTED).pack(fill="x", pady=(6, 12))
        tk.Label(body, text="New layout name", bg=colors.PANEL, fg=colors.TEXT, anchor="w").pack(fill="x")
        save_row = tk.Frame(body, bg=colors.PANEL)
        save_row.pack(fill="x", pady=(4, 12))
        self.name = tk.StringVar(master=self.root)
        self.name_entry = ttk.Entry(save_row, textvariable=self.name)
        self.name_entry.pack(side="left", fill="x", expand=True)
        self.save_button = ttk.Button(save_row, text="Save new", command=self.save)
        self.save_button.pack(side="right", padx=(8, 0))
        self.name_entry.bind("<Return>", lambda _: self.save())
        tk.Label(body, text="Saved layouts", bg=colors.PANEL, fg=colors.TEXT, anchor="w").pack(fill="x")
        self.selected = tk.StringVar(master=self.root)
        self.selector = ttk.Combobox(body, textvariable=self.selected, state="readonly")
        self.selector.pack(fill="x", pady=(4, 8))
        self.selector.bind("<<ComboboxSelected>>", lambda _: self.invalidate())
        actions = tk.Frame(body, bg=colors.PANEL)
        actions.pack(fill="x")
        self.preview_button = ttk.Button(actions, text="Preview restore", command=self.preview)
        self.preview_button.pack(side="left")
        self.replace_button = ttk.Button(actions, text="Replace selected", command=lambda: self.save(replace=True))
        self.replace_button.pack(side="right")
        self.message = tk.StringVar(master=self.root)
        tk.Label(body, textvariable=self.message, wraplength=440, justify="left", anchor="w",
                 bg=colors.PANEL, fg=colors.ACCENT, font=("Segoe UI", 9)).pack(fill="x", pady=8)
        footer = tk.Frame(body, bg=colors.PANEL)
        footer.pack(side="bottom", fill="x", pady=(10, 0))
        self.restore_button = ttk.Button(footer, text="Restore", style="Primary.TButton", command=self.restore, state="disabled")
        self.restore_button.pack(side="right")
        ttk.Button(footer, text="Close", command=self.close).pack(side="left")
        preview_area = tk.Frame(body, bg=colors.PANEL)
        preview_area.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(preview_area)
        scroll.pack(side="right", fill="y")
        self.details = tk.Text(preview_area, height=8, width=1, wrap="word", state="disabled",
                               bg=colors.PANEL, fg=colors.TEXT, insertbackground=colors.TEXT,
                               font=("Segoe UI", 10), relief="flat", yscrollcommand=scroll.set)
        self.details.pack(fill="both", expand=True)
        scroll.configure(command=self.details.yview)
        self.refresh()
        self.root.deiconify()
        self.chrome.apply_native()

    def invalidate(self):
        self.plan = None
        self.restore_button.configure(state="disabled", text="Restore")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")
        self.message.set("")

    def refresh(self, selected=None):
        self.invalidate()
        try:
            names = [item["name"] for item in self.manager.saved_layouts.load()["layouts"]]
        except ChatError as exc:
            names = []
            self.message.set(str(exc))
        self.selector.configure(values=names)
        self.selected.set(selected if selected in names else names[0] if names else "")
        for button in (self.preview_button, self.replace_button):
            button.configure(state="normal" if names else "disabled")

    def save(self, *, replace=False):
        try:
            name = self.selected.get() if replace else self.name.get()
            result = self.manager.save_activity_layout(name, replace=replace)
            self.refresh(result["name"])
            self.message.set(f"Saved {result['name']}. Preview before restoring it.")
        except ChatError as exc:
            self.message.set(str(exc))

    def preview(self):
        self.invalidate()
        try:
            self.plan = self.manager.preview_activity_layout(self.selected.get())
            lines = []
            for action, records in (("Reposition", [r for _, r in self.plan["reuse"]]),
                                    ("Open", self.plan["create"]), ("Cannot fit", self.plan["skipped"])):
                for record in records:
                    title = TYPES[record["kind"]][0] if record["kind"] in TYPES else "Pinned advice" if record["kind"] == "play" else "Window chooser"
                    lines.append(f"{action}: {title}")
            lines.extend(f"Keep open: {w.caption}" for w in self.plan["keep"])
            lines.append("\nNo messages, captures, or report refreshes will start.")
            self.details.configure(state="normal")
            self.details.insert("1.0", "\n".join(lines))
            self.details.configure(state="disabled")
            partial = bool(self.plan["skipped"])
            self.message.set("Eight-window limit: some saved windows cannot fit. Restore available keeps every current window."
                             if partial else "Ready to restore. Current conversations and drafts will be kept.")
            self.restore_button.configure(state="normal", text="Restore available" if partial else "Restore")
        except ChatError as exc:
            self.message.set(str(exc))

    def restore(self):
        if self.plan is None:
            return
        try:
            count = self.manager.restore_activity_layout(self.plan, allow_partial=bool(self.plan["skipped"]))
            skipped = len(self.plan["skipped"])
            self.invalidate()
            self.message.set(f"Restored {count} windows. {skipped} could not fit. Other windows and drafts are kept.")
        except ChatError as exc:
            self.invalidate()
            self.message.set(str(exc))

    def close(self):
        self.manager._layouts_dialog = None
        self.root.destroy()
