"""Per-window chat appearance and a local preview dialog."""

import re

from .theme import ACCENT, BACKGROUND, MUTED, PANEL, TEXT

DEFAULTS = {"background": PANEL, "text": TEXT, "labels": ACCENT,
            "font_family": "Segoe UI", "font_size": 11}
COLORS = (("background", "Background"), ("text", "Text color"), ("labels", "Speaker labels"))
MIN_FONT_SIZE, MAX_FONT_SIZE = 8, 36


def appearance_settings(raw):
    """Keep malformed or older saved layouts usable without passing them to Tk."""
    raw = raw if isinstance(raw, dict) else {}
    settings = dict(DEFAULTS)
    for key, _ in COLORS:
        value = raw.get(key)
        if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            settings[key] = value.lower()
    family = raw.get("font_family")
    if isinstance(family, str) and 0 < len(family.strip()) <= 100 and all(ord(c) >= 32 for c in family):
        settings["font_family"] = family.strip()
    size = raw.get("font_size")
    if type(size) is int:
        settings["font_size"] = max(MIN_FONT_SIZE, min(size, MAX_FONT_SIZE))
    return settings


def style_text(widget, settings):
    family, size = settings["font_family"], settings["font_size"]
    widget.configure(bg=settings["background"], fg=settings["text"],
                     insertbackground=settings["text"], font=(family, size),
                     selectbackground=settings["text"], selectforeground=settings["background"])
    widget.tag_configure("role", foreground=settings["labels"], font=(family, max(8, size - 1), "bold"))
    widget.tag_configure("note", foreground=settings["text"])


class AppearanceDialog:
    def __init__(self, view):
        import tkinter as tk
        from tkinter import font, ttk
        from .window_frame import WindowFrame

        self.view = view
        self.root = tk.Toplevel(view.root)
        self.root.withdraw()
        self.root.title("Chat appearance")
        parent = view.root.winfo_toplevel()
        self.root.transient(parent)
        self.root.attributes("-topmost", parent.attributes("-topmost"))
        self.root.geometry(f"480x500+{parent.winfo_x() + 32}+{parent.winfo_y() + 32}")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _: self.close())
        self.chrome = WindowFrame(self.root, title="Chat appearance", close=self.close, minimum=(440, 480))
        surface = self.chrome.content
        tk.Label(surface, text="For this window's conversation and message box.", bg=BACKGROUND,
                 fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=14, pady=(12, 8))
        self.variables = {key: tk.StringVar(master=self.root, value=value)
                          for key, value in view.appearance.items()}
        fields = tk.Frame(surface, bg=BACKGROUND)
        fields.pack(fill="x", padx=14)
        fields.columnconfigure(1, weight=1)
        self.swatches = {}
        for row, (key, label) in enumerate(COLORS):
            tk.Label(fields, text=label, bg=BACKGROUND, fg=TEXT, font=("Segoe UI", 10),
                     anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            ttk.Entry(fields, textvariable=self.variables[key], width=12).grid(row=row, column=1, sticky="ew")
            swatch = tk.Button(fields, text="…", width=3, relief="raised", borderwidth=1,
                               command=lambda name=key: self.choose_color(name))
            swatch.grid(row=row, column=2, padx=(6, 0))
            self.swatches[key] = swatch
        self.families = sorted({name for name in font.families(self.root) if not name.startswith("@")} |
                               {view.appearance["font_family"], DEFAULTS["font_family"]}, key=str.casefold)
        tk.Label(fields, text="Font", bg=BACKGROUND, fg=TEXT, font=("Segoe UI", 10)).grid(row=3, column=0, sticky="w", pady=5)
        self.font_picker = ttk.Combobox(fields, textvariable=self.variables["font_family"],
                                        values=self.families, state="readonly", width=18, height=12)
        self.font_picker.grid(row=3, column=1, columnspan=2, sticky="ew")
        tk.Label(fields, text="Size (points)", bg=BACKGROUND, fg=TEXT,
                 font=("Segoe UI", 10)).grid(row=4, column=0, sticky="w", pady=5)
        self.size_picker = ttk.Spinbox(fields, textvariable=self.variables["font_size"],
                                       from_=MIN_FONT_SIZE, to=MAX_FONT_SIZE, width=6)
        self.size_picker.grid(row=4, column=1, sticky="w")

        buttons = tk.Frame(surface, bg=BACKGROUND)
        buttons.pack(side="bottom", fill="x", padx=14, pady=10)
        self.reset_button = ttk.Button(buttons, text="Restore defaults", command=self.reset)
        self.reset_button.pack(side="left")
        self.save_button = ttk.Button(buttons, text="Save", command=self.save)
        self.save_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right", padx=6)
        self.error = tk.StringVar(master=self.root)
        tk.Label(surface, textvariable=self.error, bg=BACKGROUND, fg=ACCENT, font=("Segoe UI", 9),
                 anchor="w", wraplength=400).pack(side="bottom", fill="x", padx=14)
        tk.Label(surface, text="PREVIEW", bg=BACKGROUND, fg=MUTED, font=("Segoe UI", 8),
                 anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        self.preview = tk.Text(surface, height=1, width=1, wrap="word", relief="flat", padx=8, pady=6)
        self.preview.pack(fill="both", expand=True, padx=14, pady=(0, 4))
        self.preview.insert("end", "YOU\n", "role")
        self.preview.insert("end", "How should this conversation look?\n\n")
        self.preview.insert("end", "AGENT\n", "role")
        self.preview.insert("end", "Choose colors and a font that are easy to read.")
        self.preview.configure(state="disabled")
        for variable in self.variables.values():
            variable.trace_add("write", self.update_preview)
        self.update_preview()
        self.root.deiconify()
        self.chrome.apply_native()

    def values(self):
        raw = {key: variable.get() for key, variable in self.variables.items()}
        for key, label in COLORS:
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", raw[key]):
                raise ValueError(f"{label}: choose a color or enter # followed by six hex digits.")
        try:
            raw["font_size"] = int(raw["font_size"])
        except ValueError:
            raise ValueError(f"Choose a whole-number size from {MIN_FONT_SIZE} to {MAX_FONT_SIZE}.") from None
        if not MIN_FONT_SIZE <= raw["font_size"] <= MAX_FONT_SIZE:
            raise ValueError(f"Choose a size from {MIN_FONT_SIZE} to {MAX_FONT_SIZE}.")
        if raw["font_family"] not in self.families:
            raise ValueError("Choose a font from the list.")
        return appearance_settings(raw)

    def update_preview(self, *_):
        try:
            settings = self.values()
        except ValueError as error:
            self.error.set(str(error))
            return
        self.error.set("")
        style_text(self.preview, settings)
        self.preview.yview_moveto(0)
        for key, swatch in self.swatches.items():
            swatch.configure(bg=settings[key], activebackground=settings[key],
                              fg="#000000" if sum(int(settings[key][i:i + 2], 16) for i in (1, 3, 5)) > 382 else "#ffffff")

    def choose_color(self, key):
        from tkinter import colorchooser
        current = appearance_settings({key: self.variables[key].get()})[key]
        _, color = colorchooser.askcolor(color=current, parent=self.root, title=dict(COLORS)[key])
        if color:
            self.variables[key].set(color)

    def reset(self):
        for key, value in DEFAULTS.items():
            self.variables[key].set(value)

    def save(self):
        try:
            settings = self.values()
        except ValueError as error:
            self.error.set(str(error))
            return
        self.view.set_appearance(settings)
        self.close()

    def close(self):
        self.view._appearance_dialog = None
        self.root.destroy()
