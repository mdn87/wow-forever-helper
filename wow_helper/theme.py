"""Switchable Classic and Modern Synth styles for the companion's own windows."""

from dataclasses import dataclass
import os
import math
from pathlib import Path
import random

BACKGROUND = "#252321"
PANEL = BACKGROUND
TEXT = "#eee2c8"
MUTED = "#ad9c7e"
ACCENT = "#ffda55"
EDGE = "#8f7545"
EDITOR = "#131210"
TITLE = "#211910"
ASSETS = Path(__file__).with_name("assets")
_private_font_loaded = False


@dataclass(frozen=True)
class Palette:
    BACKGROUND: str = BACKGROUND
    PANEL: str = PANEL
    TEXT: str = TEXT
    MUTED: str = MUTED
    ACCENT: str = ACCENT
    EDGE: str = EDGE
    EDITOR: str = EDITOR
    TITLE: str = TITLE
    SELECT: str = "#554228"
    HOVER: str = "#6c211a"
    SECONDARY: str = "#d8b774"


PALETTES = {
    "classic": Palette(),
    "modern": Palette(BACKGROUND="#111722", PANEL="#111722", TEXT="#edf3ff",
                      MUTED="#a4b2ca", ACCENT="#80e5ed", EDGE="#35465f",
                      EDITOR="#1a2434", TITLE="#171f2e", SELECT="#304766",
                      HOVER="#293c55", SECONDARY="#b4a2ff"),
}


def palette(root):
    return PALETTES.get(getattr(root._root(), "_companion_theme", "classic"), PALETTES["classic"])


def is_modern(root):
    return palette(root) is PALETTES["modern"]


def display_font(root, size=12):
    if is_modern(root):
        return ("Segoe UI", size)
    return (getattr(root._root(), "_companion_font", "Georgia"), size)


def _load_font(root):
    global _private_font_loaded
    if os.name == "nt" and not _private_font_loaded:
        import ctypes
        gdi32 = ctypes.WinDLL("gdi32")
        gdi32.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        gdi32.AddFontResourceExW.restype = ctypes.c_int
        # FR_PRIVATE: available only to this process, removed by Windows on exit.
        _private_font_loaded = bool(gdi32.AddFontResourceExW(str(ASSETS / "Marcellus-Regular.ttf"), 0x10, None))
    from tkinter import font
    root._root()._companion_font = "Marcellus" if "Marcellus" in font.families(root) else "Georgia"


def _trim_image(root, vertical=False, reverse=False):
    import tkinter as tk
    bands = ["#100e0b", "#48351e", "#a78a51", "#d8b774", "#826234", "#44321c", "#15130f"]
    if reverse:
        bands.reverse()
    image = tk.PhotoImage(master=root, width=7 if vertical else 32, height=32 if vertical else 7)
    noise = random.Random(7)
    for position in range(32):
        for band, color in enumerate(bands):
            variation = noise.randrange(-13, 14)
            rgb = tuple(max(0, min(255, int(color[i:i + 2], 16) + variation)) for i in (1, 3, 5))
            image.put("#%02x%02x%02x" % rgb, to=(band, position) if vertical else (position, band))
    return image


def textures(root):
    return root._root()._companion_textures


def settings_icon(root):
    """A small pixel-sized cog avoids oversized or clipped fallback-font glyphs."""
    import tkinter as tk
    owner = root._root()
    color = palette(root).ACCENT
    icons = getattr(owner, "_companion_settings_icons", {})
    if color not in icons:
        icon = tk.PhotoImage(master=root, width=14, height=14)
        for y in range(14):
            for x in range(14):
                dx, dy = x - 6.5, y - 6.5
                radius = math.hypot(dx, dy)
                outer = 6.5 if math.cos(8 * math.atan2(dy, dx)) > 0 else 5
                if 2.5 <= radius <= outer:
                    icon.put(color, to=(x, y))
        icons[color] = icon
        owner._companion_settings_icons = icons
    return icons[color]


def _button_image(root, material, edge, *, brightness=1.0, pressed=False):
    import tkinter as tk
    image = tk.PhotoImage(master=root, width=160, height=40)
    image.put("#090806", to=(0, 0, 160, 40))
    image.put(edge, to=(1, 1, 159, 39))
    image.put("#382919" if pressed else "#b69a5e", to=(2, 2, 158, 4))
    image.put("#362316", to=(2, 36, 158, 38))
    image.put("#342115", to=(156, 4, 158, 36))
    image.put(edge, to=(2, 4, 4, 36))
    rows = []
    for y in range(32):
        colors = []
        for x in range(152):
            rgb = tuple(max(0, min(255, round(channel * brightness))) for channel in material.get(x, y))
            colors.append("#%02x%02x%02x" % rgb)
        rows.append("{" + " ".join(colors) + "}")
    image.put(" ".join(rows), to=(4, 4))
    return image


def _classic_theme(root):
    from tkinter import ttk
    owner = root._root()
    if getattr(owner, "_companion_theme_images", None):
        return
    style = ttk.Style(root)
    _load_font(root)
    import tkinter as tk
    owner._companion_textures = {
        "leather": tk.PhotoImage(master=root, file=str(ASSETS / "dark-leather.png")).subsample(3),
        "red_leather": tk.PhotoImage(master=root, file=str(ASSETS / "red-leather.png")).subsample(3),
        "top": _trim_image(root), "bottom": _trim_image(root, reverse=True),
        "left": _trim_image(root, vertical=True), "right": _trim_image(root, vertical=True, reverse=True),
    }
    leather = owner._companion_textures["red_leather"]
    images = {
        "normal": _button_image(root, leather, "#967242"),
        "active": _button_image(root, leather, "#d7b561", brightness=1.3),
        "pressed": _button_image(root, leather, "#a38446", brightness=0.7, pressed=True),
        "disabled": _button_image(root, owner._companion_textures["leather"], "#5c5140", brightness=0.85),
        "focus": _button_image(root, leather, "#f2d887", brightness=1.15),
    }
    # Tk tiles the material while preserving the bevels; small title controls
    # crop it instead of stretching the grain or inheriting the asset's width.
    owner._companion_theme_images = images
    style.element_create("Companion.button", "image", images["normal"],
                         ("disabled", images["disabled"]), ("pressed", images["pressed"]),
                         ("active", images["active"]), ("focus", images["focus"]),
                         border=5, sticky="nswe", width=24, height=24)
    style.layout("TButton", [("Companion.button", {"sticky": "nswe", "children": [
        ("Button.padding", {"sticky": "nswe", "children": [("Button.label", {"sticky": "nswe"})]})]})])
    style.configure("TButton", font=display_font(root, 10), foreground=ACCENT,
                    background=BACKGROUND, padding=(6, 1), width=0, anchor="center")
    style.map("TButton", foreground=[("disabled", "#837862"), ("active", "#ffe7a0")])
    style.configure("Window.TButton", font=("Segoe UI", 9, "bold"), padding=(2, 0), width=2)
    style.configure("Agent.TButton", font=("Segoe UI", 8), padding=(3, 0), width=0)
    style.layout("TMenubutton", [("Companion.button", {"sticky": "nswe", "children": [
        ("Menubutton.padding", {"sticky": "nswe", "children": [
            ("Menubutton.indicator", {"side": "right", "sticky": ""}),
            ("Menubutton.label", {"sticky": "nswe"})]})]})])
    style.configure("TMenubutton", font=display_font(root, 10), foreground=ACCENT,
                    background=BACKGROUND, arrowcolor=ACCENT, padding=(5, 1), width=0)
    style.map("TMenubutton", foreground=[("disabled", MUTED), ("active", "#ffe7a0")])
    style.layout("Settings.TMenubutton", [("Companion.button", {"sticky": "nswe", "children": [
        ("Menubutton.padding", {"sticky": "nswe", "children": [("Menubutton.label", {"sticky": "nswe"})]})]})])
    style.configure("Settings.TMenubutton", padding=(2, 0), width=0)
    style.configure("TNotebook", background=PANEL, bordercolor=EDGE, tabmargins=(3, 2, 3, 0))
    style.configure("TNotebook.Tab", background=BACKGROUND, foreground=MUTED,
                    padding=(10, 4), font=("Segoe UI", 9))
    style.map("TNotebook.Tab", background=[("selected", PANEL), ("active", TITLE)],
              foreground=[("selected", ACCENT), ("active", TEXT)])
    style.configure("TCheckbutton", background=PANEL, foreground=TEXT, font=("Segoe UI", 10))
    style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("active", ACCENT)])
    style.configure("TRadiobutton", background=PANEL, foreground=TEXT, font=("Segoe UI", 10),
                    indicatorbackground=EDITOR, indicatorforeground=ACCENT)
    style.map("TRadiobutton", background=[("active", PANEL)], foreground=[("active", ACCENT)])
    style.configure("Horizontal.TScale", background=EDGE, troughcolor=EDITOR, bordercolor=EDGE,
                    lightcolor=EDGE, darkcolor=BACKGROUND)
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                    rowheight=24, font=("Segoe UI", 10), borderwidth=0)
    style.map("Treeview", background=[("selected", "#554228")], foreground=[("selected", ACCENT)])
    for name in ("TEntry", "TSpinbox"):
        style.configure(name, foreground=TEXT, fieldbackground=EDITOR, background=TITLE,
                        bordercolor=EDGE, arrowcolor=ACCENT, insertcolor=TEXT, padding=3)
    style.configure("TCombobox", font=("Segoe UI", 10), foreground=TEXT,
                    fieldbackground=EDITOR, background=TITLE, bordercolor=EDGE,
                    lightcolor=EDGE, darkcolor=BACKGROUND, arrowcolor=ACCENT, padding=2)
    style.map("TCombobox", fieldbackground=[("readonly", EDITOR)],
              foreground=[("readonly", TEXT)], selectbackground=[("readonly", EDITOR)],
              selectforeground=[("readonly", TEXT)], background=[("active", "#4a3724")])
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", "#6c211a")
    root.option_add("*TCombobox*Listbox.selectForeground", ACCENT)
    style.configure("Vertical.TScrollbar", background="#5c4a30", troughcolor=EDITOR,
                    bordercolor=BACKGROUND, arrowcolor=ACCENT, lightcolor=EDGE,
                    darkcolor="#302719", arrowsize=13)
    style.map("Vertical.TScrollbar", background=[("active", "#8c7043"), ("pressed", "#b49352")])


def _modern_theme(root):
    from tkinter import ttk
    style, colors = ttk.Style(root), palette(root)
    style.configure(".", font=("Segoe UI", 10), background=colors.PANEL, foreground=colors.TEXT,
                    bordercolor=colors.EDGE, lightcolor=colors.EDGE, darkcolor=colors.EDGE,
                    troughcolor=colors.EDITOR, selectbackground=colors.SELECT, selectforeground=colors.TEXT)
    style.configure("TButton", font=("Segoe UI", 9), padding=(8, 3), width=0,
                    anchor="center", background=colors.EDITOR, foreground=colors.TEXT,
                    borderwidth=1, relief="flat", focusthickness=1, focuscolor=colors.ACCENT)
    style.map("TButton", background=[("disabled", colors.TITLE), ("pressed", colors.SELECT),
                                     ("active", colors.HOVER)],
              foreground=[("disabled", "#748299"), ("active", colors.ACCENT)],
              bordercolor=[("focus", colors.ACCENT), ("active", colors.ACCENT)])
    style.configure("Primary.TButton", background=colors.ACCENT, foreground="#111722")
    style.map("Primary.TButton", background=[("disabled", colors.EDITOR), ("pressed", "#54bccb"),
                                             ("active", "#a4f3f5")],
              foreground=[("disabled", "#748299"), ("!disabled", "#111722")])
    style.configure("Window.TButton", font=("Segoe UI", 9), padding=(2, 0), width=2)
    style.configure("Agent.TButton", font=("Segoe UI", 8), padding=(4, 1), width=0)
    style.configure("TMenubutton", padding=(6, 3), background=colors.EDITOR,
                    arrowcolor=colors.ACCENT, relief="flat")
    style.map("TMenubutton", background=[("active", colors.HOVER)])
    style.layout("Settings.TMenubutton", [("Menubutton.border", {"sticky": "nswe", "children": [
        ("Menubutton.padding", {"sticky": "nswe", "children": [("Menubutton.label", {"sticky": "nswe"})]})]})])
    style.configure("Settings.TMenubutton", padding=(5, 2), width=0)
    style.configure("TNotebook", background=colors.PANEL, borderwidth=0, tabmargins=(0, 4, 0, 2))
    style.configure("TNotebook.Tab", background=colors.TITLE, foreground=colors.MUTED,
                    font=("Segoe UI", 9), padding=(10, 5))
    style.map("TNotebook.Tab", background=[("selected", colors.SELECT), ("active", colors.HOVER)],
              foreground=[("selected", colors.ACCENT), ("active", colors.TEXT)])
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=colors.PANEL, foreground=colors.TEXT,
                        indicatorbackground=colors.EDITOR, indicatorforeground=colors.ACCENT,
                        padding=(0, 3), focuscolor=colors.ACCENT)
        style.map(name, background=[("active", colors.PANEL)], foreground=[("active", colors.ACCENT)],
                  indicatorbackground=[("selected", colors.SELECT)])
    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(name, foreground=colors.TEXT, fieldbackground=colors.EDITOR,
                        background=colors.EDITOR, arrowcolor=colors.ACCENT,
                        insertcolor=colors.TEXT, padding=3)
        style.map(name, fieldbackground=[("readonly", colors.EDITOR)],
                  foreground=[("readonly", colors.TEXT)], selectbackground=[("readonly", colors.SELECT)],
                  selectforeground=[("readonly", colors.TEXT)], bordercolor=[("focus", colors.ACCENT)],
                  background=[("active", colors.HOVER)])
    style.configure("Treeview", background=colors.PANEL, fieldbackground=colors.PANEL,
                    foreground=colors.TEXT, font=("Segoe UI", 10), rowheight=26, borderwidth=0)
    style.map("Treeview", background=[("selected", colors.SELECT)], foreground=[("selected", colors.TEXT)])
    style.configure("Vertical.TScrollbar", background=colors.EDGE, troughcolor=colors.PANEL,
                    arrowcolor=colors.MUTED, borderwidth=0, arrowsize=12)
    style.map("Vertical.TScrollbar", background=[("active", colors.MUTED), ("pressed", colors.ACCENT)])
    import tkinter as tk
    thumb = tk.PhotoImage(master=root, width=16, height=20)
    thumb.put(colors.ACCENT, to=(2, 2, 14, 18))
    thumb.put(colors.TEXT, to=(4, 4, 12, 16))
    root._root()._companion_scale_thumb = thumb
    style.element_create("Modern.Scale.slider", "image", thumb, sticky="")
    style.layout("Horizontal.TScale", [("Horizontal.Scale.trough", {"sticky": "we", "children": [
        ("Modern.Scale.slider", {"side": "left", "sticky": ""})]})])
    style.configure("Horizontal.TScale", troughcolor=colors.EDITOR, borderwidth=1,
                    bordercolor=colors.EDGE, lightcolor=colors.EDGE, darkcolor=colors.EDGE)


def apply_theme(root, name=None):
    """Switch in place so draft widgets, workers and sessions keep their identity."""
    from tkinter import ttk
    owner = root._root()
    old = palette(root)
    name = name if name in PALETTES else getattr(owner, "_companion_theme", "classic")
    owner._companion_theme = name
    style = ttk.Style(root)
    theme_name = "companion_" + name
    if style.theme_use() == theme_name:
        return
    if theme_name not in style.theme_names():
        style.theme_create(theme_name, parent="clam")
        style.theme_use(theme_name)
        (_modern_theme if name == "modern" else _classic_theme)(root)
    else:
        style.theme_use(theme_name)
    colors = palette(root)
    for option, value in (("background", colors.PANEL), ("foreground", colors.TEXT),
                          ("selectBackground", colors.SELECT), ("selectForeground", colors.TEXT)):
        root.option_add("*TCombobox*Listbox." + option, value)
    if old != colors:
        _recolor(owner, old, colors)


def _recolor(widget, old, new):
    """Update native Tk controls; ttk controls inherit the active named theme."""
    from tkinter import font
    mapping = {getattr(old, key): getattr(new, key) for key in old.__dataclass_fields__}
    options = widget.keys()
    for key in ("background", "foreground", "activebackground", "activeforeground", "disabledforeground",
                "highlightbackground", "highlightcolor", "insertbackground", "selectbackground",
                "selectforeground", "selectcolor"):
        if key in options:
            color = str(widget.cget(key))
            if color in mapping:
                widget.configure(**{key: mapping[color]})
    if "font" in options and widget.winfo_class() == "Label":
        current = font.Font(root=widget, font=widget.cget("font"))
        if current.actual("family") in ("Marcellus", "Georgia", "Segoe UI"):
            # Only display-sized labels change family; body copy stays sans serif.
            if current.actual("size") >= 12:
                widget.configure(font=display_font(widget, current.actual("size")))
    if "image" in options:
        images = widget.tk.splitlist(widget.cget("image"))
        icons = getattr(widget._root(), "_companion_settings_icons", {}).values()
        if len(images) == 1 and str(images[0]) in {str(icon) for icon in icons}:
            widget.configure(image=settings_icon(widget))
    if hasattr(widget, "_companion_appearance"):
        from .appearance import style_text
        settings, composer = widget._companion_appearance
        style_text(widget, settings, composer=composer)
    if hasattr(widget, "_companion_theme_refresh"):
        widget._companion_theme_refresh()
    for child in widget.winfo_children():
        _recolor(child, old, new)


def menu(parent):
    import tkinter as tk
    colors = palette(parent)
    return tk.Menu(parent, tearoff=False, bg=colors.PANEL, fg=colors.TEXT, activebackground=colors.HOVER,
                   activeforeground=colors.ACCENT, disabledforeground=colors.MUTED, selectcolor=colors.ACCENT,
                   font=("Segoe UI", 10), relief="flat", borderwidth=1)


class BusyBar:
    """An indeterminate bar shown only while slow local work runs, so a pending read looks pending."""

    def __init__(self, parent, **pack):
        from tkinter import ttk
        self.bar = ttk.Progressbar(parent, mode="indeterminate")
        self.pack, self.shown = pack, False

    def set(self, busy):
        if busy and not self.shown:
            self.bar.pack(**self.pack)
            self.bar.start(15)
        elif not busy and self.shown:
            self.bar.stop()
            self.bar.pack_forget()
        self.shown = busy
