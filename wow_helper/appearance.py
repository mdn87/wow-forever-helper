"""Per-window chat appearance and a local preview dialog."""

import re

from .theme import ACCENT, PANEL, TEXT, palette, is_modern

DEFAULTS = {"background": PANEL, "text": TEXT, "user_text": ACCENT,
            "font_family": "Segoe UI", "font_size": 11, "use_theme_colors": True}
COLORS = (("background", "Background"), ("text", "Agent text"), ("user_text", "Your text"))
MIN_FONT_SIZE, MAX_FONT_SIZE = 8, 36


def appearance_settings(raw):
    """Keep malformed or older saved layouts usable without passing them to Tk."""
    raw = raw if isinstance(raw, dict) else {}
    settings = dict(DEFAULTS)
    for key, _ in COLORS:
        # Earlier layouts used this color for the speaker labels.
        value = raw.get(key, raw.get("labels") if key == "user_text" else None)
        if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            settings[key] = value.lower()
    family = raw.get("font_family")
    if isinstance(family, str) and 0 < len(family.strip()) <= 100 and all(ord(c) >= 32 for c in family):
        settings["font_family"] = family.strip()
    size = raw.get("font_size")
    if type(size) is int:
        settings["font_size"] = max(MIN_FONT_SIZE, min(size, MAX_FONT_SIZE))
    default_colors = all(settings[key] == DEFAULTS[key] for key, _ in COLORS)
    settings["use_theme_colors"] = default_colors and raw.get("use_theme_colors", True) is True
    return settings


def resolved_appearance(settings, root):
    if settings.get("use_theme_colors"):
        colors = palette(root)
        return {**settings, "background": colors.PANEL, "text": colors.TEXT, "user_text": colors.ACCENT}
    return settings


def style_text(widget, settings, *, composer=False):
    widget._companion_appearance = (dict(settings), composer)
    settings = resolved_appearance(settings, widget)
    family, size = settings["font_family"], settings["font_size"]
    foreground = settings["user_text"] if composer else settings["text"]
    widget.configure(bg=settings["background"], fg=foreground,
                     insertbackground=foreground, font=(family, size),
                     selectbackground=foreground, selectforeground=settings["background"])
    if composer:
        widget.configure(highlightthickness=1, highlightbackground=palette(widget).EDGE,
                         highlightcolor=palette(widget).ACCENT, borderwidth=0, relief="flat")
        if settings.get("use_theme_colors") and is_modern(widget):
            widget.configure(bg=palette(widget).EDITOR)
    widget.tag_configure("user", foreground=settings["user_text"])
    widget.tag_configure("assistant", foreground=settings["text"])
    widget.tag_configure("body", spacing1=0, spacing2=0, spacing3=0)
    widget.tag_configure("note", foreground=settings["text"], spacing1=0, spacing3=0)
    widget.tag_configure("delivery", font=(family, max(8, size - 2), "italic"))
    widget.tag_configure("divider", font=(family, 1), spacing1=1, spacing2=0, spacing3=1)
    _resize_divider(widget)


def _resize_divider(widget):
    """One shared, one-pixel rule follows the usable width and the selected colors."""
    if not hasattr(widget, "_turn_divider"):
        return
    inset = sum(int(widget.cget(name)) for name in ("padx", "borderwidth", "highlightthickness"))
    width = max(1, widget.winfo_width() - 2 * inset)
    background, foreground = (widget.winfo_rgb(widget.cget(name)) for name in ("background", "foreground"))
    color = "#%02x%02x%02x" % tuple(round((b * .78 + f * .22) / 257) for b, f in zip(background, foreground))
    if getattr(widget, "_divider_signature", None) != (width, color):
        widget._turn_divider.configure(width=width, height=1)
        widget._turn_divider.put(color, to=(0, 0, width, 1))
        widget._divider_signature = (width, color)


def _release_divider(widget):
    # Release Tk resources on the UI thread, not later in a provider worker's GC.
    if hasattr(widget, "_turn_divider"):
        del widget._turn_divider


def append_turn(widget, body, role, *, pending=""):
    """Render message colors without adding speaker rows or paragraph padding."""
    if widget.index("end-1c") != "1.0":
        if not hasattr(widget, "_turn_divider"):
            import tkinter as tk
            widget._turn_divider = tk.PhotoImage(master=widget, width=1, height=1)
            widget.bind("<Configure>", lambda _: _resize_divider(widget), add="+")
            widget.bind("<Destroy>", lambda _: _release_divider(widget), add="+")
            _resize_divider(widget)
        widget.insert("end", "\n", "body")
        start = widget.index("end-1c")
        widget.image_create("end", image=widget._turn_divider)
        widget.insert("end", "\n", "divider")
        widget.tag_add("divider", start, "end-1c")
    role = "user" if role == "user" else "assistant"
    widget.insert("end", body.strip("\n"), ("body", role))
    if pending:
        widget.insert("end", "  · " + pending.upper(), ("delivery", role))


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
        tk.Label(surface, text="For this window's conversation and message box.", bg=palette(self.root).BACKGROUND,
                 fg=palette(self.root).MUTED, font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=14, pady=(12, 8))
        current = resolved_appearance(view.appearance, self.root)
        self.variables = {key: tk.StringVar(master=self.root, value=value)
                          for key, value in current.items() if key != "use_theme_colors"}
        fields = tk.Frame(surface, bg=palette(self.root).BACKGROUND)
        fields.pack(fill="x", padx=14)
        fields.columnconfigure(1, weight=1)
        self.swatches = {}
        for row, (key, label) in enumerate(COLORS):
            tk.Label(fields, text=label, bg=palette(self.root).BACKGROUND, fg=palette(self.root).TEXT, font=("Segoe UI", 10),
                     anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            ttk.Entry(fields, textvariable=self.variables[key], width=12).grid(row=row, column=1, sticky="ew")
            swatch = tk.Button(fields, text="…", width=3, relief="raised", borderwidth=1,
                               command=lambda name=key: self.choose_color(name))
            swatch.grid(row=row, column=2, padx=(6, 0))
            self.swatches[key] = swatch
        self.families = sorted({name for name in font.families(self.root) if not name.startswith("@")} |
                               {view.appearance["font_family"], DEFAULTS["font_family"]}, key=str.casefold)
        tk.Label(fields, text="Font", bg=palette(self.root).BACKGROUND, fg=palette(self.root).TEXT, font=("Segoe UI", 10)).grid(row=3, column=0, sticky="w", pady=5)
        self.font_picker = ttk.Combobox(fields, textvariable=self.variables["font_family"],
                                        values=self.families, state="readonly", width=18, height=12)
        self.font_picker.grid(row=3, column=1, columnspan=2, sticky="ew")
        tk.Label(fields, text="Size (points)", bg=palette(self.root).BACKGROUND, fg=palette(self.root).TEXT,
                 font=("Segoe UI", 10)).grid(row=4, column=0, sticky="w", pady=5)
        self.size_picker = ttk.Spinbox(fields, textvariable=self.variables["font_size"],
                                       from_=MIN_FONT_SIZE, to=MAX_FONT_SIZE, width=6)
        self.size_picker.grid(row=4, column=1, sticky="w")
        self.use_theme_colors = tk.BooleanVar(master=self.root, value=view.appearance["use_theme_colors"])
        ttk.Checkbutton(fields, text="Use interface colors", variable=self.use_theme_colors,
                        command=self.update_preview).grid(row=5, column=0, columnspan=3, sticky="w", pady=5)

        buttons = tk.Frame(surface, bg=palette(self.root).BACKGROUND)
        buttons.pack(side="bottom", fill="x", padx=14, pady=10)
        self.reset_button = ttk.Button(buttons, text="Restore defaults", command=self.reset)
        self.reset_button.pack(side="left")
        self.save_button = ttk.Button(buttons, text="Save", command=self.save)
        self.save_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right", padx=6)
        self.error = tk.StringVar(master=self.root)
        tk.Label(surface, textvariable=self.error, bg=palette(self.root).BACKGROUND, fg=palette(self.root).ACCENT, font=("Segoe UI", 9),
                 anchor="w", wraplength=400).pack(side="bottom", fill="x", padx=14)
        tk.Label(surface, text="PREVIEW", bg=palette(self.root).BACKGROUND, fg=palette(self.root).MUTED, font=("Segoe UI", 8),
                 anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        self.preview = tk.Text(surface, height=1, width=1, wrap="word", relief="flat", padx=8, pady=6)
        self.preview.pack(fill="both", expand=True, padx=14, pady=(0, 4))
        append_turn(self.preview, "How should this conversation look?", "user")
        append_turn(self.preview, "Choose colors and a font that are easy to read.", "assistant")
        self.preview.configure(state="disabled")
        self._traces = [(variable, variable.trace_add("write", lambda *_, name=key: self._changed(name)))
                        for key, variable in self.variables.items()]
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
        raw["use_theme_colors"] = self.use_theme_colors.get()
        if raw["use_theme_colors"]:
            # Store stable default tokens; the active interface resolves their colors.
            raw.update({key: DEFAULTS[key] for key, _ in COLORS})
        return appearance_settings(raw)

    def _changed(self, name):
        if name in dict(COLORS):
            self.use_theme_colors.set(False)
        self.update_preview()

    def update_preview(self, *_):
        try:
            settings = self.values()
        except ValueError as error:
            self.error.set(str(error))
            return
        self.error.set("")
        style_text(self.preview, settings)
        self.preview.yview_moveto(0)
        settings = resolved_appearance(settings, self.root)
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
        for key, value in resolved_appearance(DEFAULTS, self.root).items():
            if key in self.variables:
                self.variables[key].set(value)
        self.use_theme_colors.set(True)
        self.update_preview()

    def save(self):
        try:
            settings = self.values()
        except ValueError as error:
            self.error.set(str(error))
            return
        self.view.set_appearance(settings)
        self.close()

    def close(self):
        for variable, callback in self._traces:
            variable.trace_remove("write", callback)
        self._traces.clear()
        self.view._appearance_dialog = None
        self.root.destroy()
