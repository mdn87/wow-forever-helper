"""Original fantasy textures and a privately loaded, openly licensed display font."""

import os
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


def display_font(root, size=12):
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


def apply_theme(root):
    from tkinter import ttk
    owner = root._root()
    if getattr(owner, "_companion_theme_images", None):
        return
    style = ttk.Style(root)
    style.theme_use("clam")
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
    style.layout("TMenubutton", [("Companion.button", {"sticky": "nswe", "children": [
        ("Menubutton.padding", {"sticky": "nswe", "children": [
            ("Menubutton.indicator", {"side": "right", "sticky": ""}),
            ("Menubutton.label", {"sticky": "nswe"})]})]})])
    style.configure("TMenubutton", font=display_font(root, 10), foreground=ACCENT,
                    background=BACKGROUND, arrowcolor=ACCENT, padding=(5, 1), width=0)
    style.map("TMenubutton", foreground=[("disabled", MUTED), ("active", "#ffe7a0")])
    style.layout("Settings.TMenubutton", [("Companion.button", {"sticky": "nswe", "children": [
        ("Menubutton.padding", {"sticky": "nswe", "children": [("Menubutton.label", {"sticky": "nswe"})]})]})])
    style.configure("Settings.TMenubutton", font=("Segoe UI", 11), padding=(4, 0), width=2)
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


def menu(parent):
    import tkinter as tk
    return tk.Menu(parent, tearoff=False, bg=PANEL, fg=TEXT, activebackground="#6c211a",
                   activeforeground=ACCENT, disabledforeground=MUTED, selectcolor=ACCENT,
                   font=("Segoe UI", 10), relief="raised", borderwidth=2)
