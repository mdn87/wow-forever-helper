"""The companion's own title bar, with normal Windows resizing and taskbar behavior."""

import os

from .theme import ACCENT, BACKGROUND, EDGE, TITLE, apply_theme, display_font, textures


def hide_native_caption(root):
    """Change only this process's Tk window style; never install a window hook."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    root.update_idletasks()
    handle = int(root.frame(), 0)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    owner = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
    if owner.value != os.getpid():
        return False
    suffix = "PtrW" if ctypes.sizeof(ctypes.c_void_p) == 8 else "W"
    get_style = getattr(user32, "GetWindowLong" + suffix)
    set_style = getattr(user32, "SetWindowLong" + suffix)
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_style.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL

    def move(x, y):
        current_owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(current_owner))
        if current_owner.value != os.getpid():
            return False
        # NOSIZE | NOZORDER | NOACTIVATE. Tk's geometry path briefly recalculates
        # the old caption height even on a move, needlessly resizing the content.
        return bool(user32.SetWindowPos(handle, None, x, y, 0, 0, 0x0015))

    root._companion_move = move
    original = get_style(handle, -16)  # GWL_STYLE only; no window-procedure changes.
    # A caption requires WS_BORDER | WS_DLGFRAME. Keep WS_BORDER and the native
    # sizing/minimize/maximize styles so Tk's client-size calculations stay correct.
    if not original & 0x00400000:
        return True
    geometry = root.geometry()
    ctypes.set_last_error(0)
    if not set_style(handle, -16, original & ~0x00400000) and ctypes.get_last_error():
        return False
    # FRAMECHANGED, NOMOVE, NOSIZE, NOZORDER, NOACTIVATE: no focus or stacking change.
    if not user32.SetWindowPos(handle, None, 0, 0, 0, 0, 0x0037):
        set_style(handle, -16, original)
        return False
    # Tk still uses its old caption height for the first minimum-size check.
    # Temporarily release that constraint while it measures the new client area.
    minimum = root.minsize()
    try:
        root.minsize(1, 1)
        root.geometry(geometry)
        root.update_idletasks()
    finally:
        root.minsize(*minimum)
        root.update_idletasks()
    return True


class WindowFrame:
    def __init__(self, root, *, title="WoW Companion", close=None, minimum=(440, 580)):
        import tkinter as tk
        from tkinter import font, ttk

        apply_theme(root)
        self.root = root
        self.minimum = minimum
        self.drag_start = None
        self.native_caption_hidden = False
        self._shown_state = None
        root.configure(bg=BACKGROUND)
        root.minsize(*minimum)
        self.shell = tk.Canvas(root, bg=BACKGROUND, highlightthickness=0, borderwidth=0)
        self.shell.pack(fill="both", expand=True)
        self.shell.bind("<Configure>", self._draw_frame)
        inner = tk.Frame(self.shell, bg=BACKGROUND)
        inner.pack(fill="both", expand=True, padx=7, pady=7)
        self.titlebar = tk.Canvas(inner, bg=TITLE, height=30, borderwidth=0,
                                  highlightthickness=1, highlightbackground=EDGE, cursor="fleur")
        self.titlebar.pack(fill="x")
        self.close_button = ttk.Button(self.titlebar, text="×", style="Window.TButton",
                                        command=close or root.destroy)
        self.close_button.pack(side="right", padx=(3, 5), pady=2)
        self.maximize_button = ttk.Button(self.titlebar, text="□", style="Window.TButton", command=self.maximize)
        self.maximize_button.pack(side="right", padx=(3, 0), pady=2)
        if os.name != "nt":
            self.maximize_button.configure(state="disabled")
        self.minimize_button = ttk.Button(self.titlebar, text="−", style="Window.TButton", command=root.iconify)
        self.minimize_button.pack(side="right", padx=(3, 0), pady=2)
        self.caption = tk.StringVar(master=root, value=title)
        self.title_font = font.Font(root=root, font=display_font(root, 12))
        self.caption.trace_add("write", self._draw_title)
        self.titlebar.bind("<Configure>", self._draw_title)
        self.titlebar.bind("<ButtonPress-1>", lambda event: self.begin(event, "move"))
        self.titlebar.bind("<B1-Motion>", self.drag)
        self.titlebar.bind("<ButtonRelease-1>", self.end)
        self.titlebar.bind("<Double-Button-1>", self.maximize)
        bottom = tk.Frame(inner, bg=BACKGROUND, height=12)
        bottom.pack(side="bottom", fill="x")
        self.grip = tk.Label(bottom, text="◢", bg=BACKGROUND, fg=EDGE,
                             font=("Segoe UI", 11), cursor="bottom_right_corner", padx=2)
        self.grip.pack(side="right")
        self.grip.bind("<ButtonPress-1>", lambda event: self.begin(event, "resize"))
        self.grip.bind("<B1-Motion>", self.drag)
        self.grip.bind("<ButtonRelease-1>", self.end)
        self.content = tk.Frame(inner, bg=BACKGROUND)
        self.content.pack(fill="both", expand=True)
        root.bind("<Configure>", self._state_changed, add="+")

    def _draw_frame(self, _event=None):
        width, height = self.shell.winfo_width(), self.shell.winfo_height()
        self.shell.delete("trim")
        material = textures(self.root)
        for x in range(0, width, 32):
            self.shell.create_image(x, 0, image=material["top"], anchor="nw", tags="trim")
            self.shell.create_image(x, height - 7, image=material["bottom"], anchor="nw", tags="trim")
        for y in range(0, height, 32):
            self.shell.create_image(0, y, image=material["left"], anchor="nw", tags="trim")
            self.shell.create_image(width - 7, y, image=material["right"], anchor="nw", tags="trim")

    def _draw_title(self, *_):
        width, height = self.titlebar.winfo_width(), self.titlebar.winfo_height()
        if width <= 1:
            return
        leather = textures(self.root)["leather"]
        self.titlebar.delete("decoration")
        for x in range(0, width, leather.width()):
            self.titlebar.create_image(x, 0, image=leather, anchor="nw", tags="decoration")
        controls = sum(button.winfo_reqwidth() for button in
                       (self.close_button, self.maximize_button, self.minimize_button)) + 14
        available = max(1, width - controls - 24)
        caption = self.caption.get()
        if self.title_font.measure(caption) > available:
            while caption and self.title_font.measure(caption + "…") > available:
                caption = caption[:-1]
            caption += "…"
        x, y = 12 + available / 2, height / 2
        self.titlebar.create_text(x + 1, y + 1, text=caption, font=self.title_font,
                                  fill="#080604", tags="decoration")
        self.titlebar.create_text(x, y, text=caption, font=self.title_font, fill=ACCENT, tags="decoration")

    def apply_native(self):
        self.native_caption_hidden = hide_native_caption(self.root)

    def place(self, geometry):
        """Restore a client size without Tk's obsolete native caption minimum."""
        minimum = self.root.minsize()
        try:
            if self.native_caption_hidden:
                self.root.minsize(1, 1)
            self.root.geometry(geometry)
            self.root.update_idletasks()
        finally:
            self.root.minsize(*minimum)
            self.root.update_idletasks()

    def maximize(self, _event=None):
        self.drag_start = None
        if self.root.state() == "zoomed":
            self.root.state("normal")
        elif os.name == "nt":
            self.root.state("zoomed")

    def _state_changed(self, event):
        if event.widget is self.root:
            state = self.root.state()
            if state != self._shown_state:
                self._shown_state = state
                self.maximize_button.configure(text="❐" if state == "zoomed" else "□")

    def begin(self, event, kind):
        if self.root.state() != "normal":
            return
        self.drag_start = (kind, event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y(),
                           self.root.winfo_width(), self.root.winfo_height())

    def drag(self, event):
        if not self.drag_start:
            return
        kind, mx, my, x, y, width, height = self.drag_start
        dx, dy = event.x_root - mx, event.y_root - my
        if kind == "move":
            x, y = x + dx, y + dy
            move = getattr(self.root, "_companion_move", None)
            if move and move(x, y):
                return
            self.root.geometry(f"+{x}+{y}")
        else:
            width = max(self.minimum[0], width + dx)
            height = max(self.minimum[1], height + dy)
            self.place(f"{width}x{height}+{x}+{y}")

    def end(self, _event=None):
        self.drag_start = None
