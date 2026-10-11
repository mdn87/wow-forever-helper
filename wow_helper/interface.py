"""Live interface preferences and bounded opacity for companion windows only."""

from .theme import PALETTES, palette

MIN_OPACITY = 65
INTERFACE_DEFAULTS = {"theme": "classic", "opacity": 100, "solid_when_active": True}


def interface_settings(raw):
    raw = raw if isinstance(raw, dict) else {}
    result = dict(INTERFACE_DEFAULTS)
    if isinstance(raw.get("theme"), str) and raw["theme"] in PALETTES:
        result["theme"] = raw["theme"]
    value = raw.get("opacity")
    if type(value) is int:
        result["opacity"] = max(MIN_OPACITY, min(100, value))
    if type(raw.get("solid_when_active")) is bool:
        result["solid_when_active"] = raw["solid_when_active"]
    return result


class WindowOpacity:
    """Use Tk's supported whole-window alpha; never create transparent hit holes."""

    def __init__(self, root, settings):
        self.root, self.settings = root, settings
        self.supported = True
        self.closed = False
        self._after = None
        for event in ("<FocusIn>", "<FocusOut>", "<Map>"):
            root.bind(event, self.schedule, add="+")
        self.apply()

    def schedule(self, _event=None):
        if not self.closed and self._after is None:
            self._after = self.root.after_idle(self.apply)

    def apply(self):
        import tkinter as tk
        if self.closed:
            return
        if self._after is not None:
            self.root.after_cancel(self._after)
            self._after = None
        settings = interface_settings(self.settings())
        try:
            # ttk popdowns exist in Tcl without Python widget objects, so
            # focus_displayof() can raise KeyError while the selector is open.
            focused = str(self.root.tk.call("focus", "-displayof", self.root))
            active = focused == str(self.root) or focused.startswith(str(self.root) + ".")
            opacity = 100 if settings["solid_when_active"] and active else settings["opacity"]
            self.root.attributes("-alpha", opacity / 100)
            self.supported = abs(float(self.root.attributes("-alpha")) - opacity / 100) < .01
            if not self.supported:
                self.root.attributes("-alpha", 1.0)
        except tk.TclError:
            self.supported = False
            try:
                self.root.attributes("-alpha", 1.0)
            except tk.TclError:
                pass

    def close(self):
        self.closed = True
        if self._after is not None:
            self.root.after_cancel(self._after)
            self._after = None


class InterfaceDialog:
    def __init__(self, manager, parent):
        import tkinter as tk
        from tkinter import ttk
        from .window_frame import WindowFrame

        self.manager = manager
        self.parent = parent
        self.root = tk.Toplevel(manager.root)
        self.root.withdraw()
        self.root.title("Interface & transparency")
        self.root.transient(parent)
        self.root.attributes("-topmost", parent.attributes("-topmost"))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _: self.close())
        self.chrome = WindowFrame(self.root, title="Interface & transparency", close=self.close, minimum=(460, 600))
        self.chrome.place(f"500x620+{parent.winfo_x() + 24}+{parent.winfo_y() + 24}")
        colors = palette(self.root)
        surface = self.chrome.content
        body = tk.Frame(surface, bg=colors.PANEL, padx=20, pady=16)
        body.pack(fill="both", expand=True)

        def label(text, *, size=10, muted=False, pady=(0, 8)):
            item = tk.Label(body, text=text, bg=colors.PANEL, fg=colors.MUTED if muted else colors.TEXT,
                            font=("Segoe UI", size), anchor="w", justify="left", wraplength=404)
            item.pack(fill="x", pady=pady)
            return item

        label("Make it your space", size=20)
        label("One interface for all companion windows. Preview changes here, then save.", muted=True)
        self.theme = tk.StringVar(master=self.root, value=manager.interface["theme"])
        self.opacity = tk.DoubleVar(master=self.root, value=manager.interface["opacity"])
        self.solid_when_active = tk.BooleanVar(master=self.root, value=manager.interface["solid_when_active"])
        self.theme_buttons = {}
        for name, title, description in (
            ("modern", "Modern Synth", "Charcoal surfaces · cyan accents · clean typography"),
            ("classic", "Classic", "Warm panels · leather details · brass trim"),
        ):
            button = ttk.Radiobutton(body, text=title, variable=self.theme, value=name, command=self.preview)
            button.pack(anchor="w", pady=(10, 0))
            self.theme_buttons[name] = button
            label(description, muted=True, size=9, pady=(0, 4))

        tk.Frame(body, bg=colors.EDGE, height=1).pack(fill="x", pady=(18, 14))
        heading = tk.Frame(body, bg=colors.PANEL)
        heading.pack(fill="x")
        tk.Label(heading, text="Window opacity", font=("Segoe UI", 11), bg=colors.PANEL,
                 fg=colors.TEXT).pack(side="left")
        self.percent = tk.StringVar(master=self.root)
        tk.Label(heading, textvariable=self.percent, font=("Segoe UI", 11), bg=colors.PANEL,
                 fg=colors.ACCENT).pack(side="right")
        self.slider = ttk.Scale(body, from_=MIN_OPACITY, to=100, variable=self.opacity,
                                command=lambda _: self.preview(), orient="horizontal", takefocus=True)
        self.slider.pack(fill="x", pady=(12, 4))
        for event, step in (("<Left>", -1), ("<Right>", 1), ("<Down>", -1), ("<Up>", 1)):
            self.slider.bind(event, lambda _, delta=step: self.nudge(delta))
        self.slider.bind("<Home>", lambda _: self.set_opacity(MIN_OPACITY))
        self.slider.bind("<End>", lambda _: self.set_opacity(100))
        legend = tk.Frame(body, bg=colors.PANEL)
        legend.pack(fill="x", pady=(0, 8))
        for text, side in (("65% translucent", "left"), ("100% solid", "right")):
            tk.Label(legend, text=text, bg=colors.PANEL, fg=colors.MUTED,
                     font=("Segoe UI", 9)).pack(side=side)
        label("Transparency also fades text. Use 85–100% over busy backgrounds; this settings window stays solid.",
              muted=True, size=9, pady=(4, 8))
        ttk.Checkbutton(body, text="Make a window solid while I use it", variable=self.solid_when_active,
                        command=self.preview).pack(anchor="w")
        self.error = tk.StringVar(master=self.root)
        tk.Label(body, textvariable=self.error, bg=colors.PANEL, fg=colors.ACCENT,
                 wraplength=400, justify="left", anchor="w", font=("Segoe UI", 9)).pack(fill="x", pady=8)
        buttons = tk.Frame(surface, bg=colors.PANEL, padx=20, pady=12)
        buttons.pack(side="bottom", fill="x", before=body)
        ttk.Button(buttons, text="Reset", command=self.reset).pack(side="left")
        self.save_button = ttk.Button(buttons, text="Save", style="Primary.TButton", command=self.save)
        self.save_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right", padx=8)
        self.percent.set(f"{round(self.opacity.get())}%")
        self.root.deiconify()
        self.chrome.apply_native()

    def values(self):
        return interface_settings({"theme": self.theme.get(), "opacity": round(self.opacity.get()),
                                   "solid_when_active": self.solid_when_active.get()})

    def preview(self):
        settings = self.values()
        self.percent.set(f"{settings['opacity']}%")
        self.manager.preview_interface(settings)
        self.error.set("Transparency is unavailable on this desktop. Windows remain solid."
                       if any(not window.opacity.supported for window in self.manager.windows) else "")

    def set_opacity(self, value):
        self.opacity.set(max(MIN_OPACITY, min(100, value)))
        self.preview()
        return "break"

    def nudge(self, delta):
        return self.set_opacity(round(self.opacity.get()) + delta)

    def reset(self):
        self.theme.set("classic")
        self.opacity.set(100)
        self.solid_when_active.set(True)
        self.preview()

    def save(self):
        previous = self.manager.interface
        self.manager.interface = self.values()
        if not self.manager.save_layout():
            self.manager.interface = previous
            self.error.set("Could not save. Keep settings open and try again, or cancel to restore them.")
            return
        self.close()

    def close(self):
        self.manager._interface_dialog = None
        self.manager.preview_interface(None)
        self.root.destroy()
