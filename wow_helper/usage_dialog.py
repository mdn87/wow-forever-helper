"""One explicit decision for a provider-reported usage interruption."""
from .theme import palette
from .window_frame import WindowFrame


class UsageDialog:
    def __init__(self, view, decision, on_continue, on_keep, parent=None):
        from tkinter import ttk
        self.view, self.on_keep, self.on_continue = view, on_keep, on_continue
        self.closed = False
        tk = view.tk
        self.root = tk.Toplevel(parent or view.root)
        self.root.title('Provider usage')
        self.root.transient((parent or view.root).winfo_toplevel())
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Escape>', lambda _: self.close())
        chrome = self.chrome = WindowFrame(self.root, title='Provider usage', close=self.close, minimum=(410, 280))
        chrome.place('510x320')
        colors = palette(self.root)
        body = tk.Frame(chrome.content, bg=colors.PANEL, padx=14, pady=12)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=str(decision), wraplength=360).pack(anchor='w')
        self.keep = ttk.Button(body, text='Keep draft', command=self.close)
        self.keep.pack(fill='x', pady=(12, 3))
        ttk.Button(body, text='Choose another chat', command=self.choose).pack(fill='x', pady=3)
        self.once = None
        if decision.usage.extras and not decision.usage.hard_stop:
            ttk.Label(body, text='Extra usage may apply under the provider’s billing settings.',
                      wraplength=360).pack(anchor='w', pady=(8, 2))
            self.once = ttk.Button(body, text='Send once with provider billing settings', command=self.proceed)
            self.once.pack(fill='x')
        chrome.apply_native()
        self.keep.focus_set()

    def finish(self):
        self.closed = True
        self.view._usage_dialog = None
        self.root.destroy()
        if not self.view.closed:
            self.view.editor.focus_set()

    def close(self):
        if not self.closed:
            self.finish()
            self.on_keep()

    def choose(self):
        self.close()
        self.view.choose_chat()

    def proceed(self):
        if not self.closed and self.once is not None:
            self.finish()
            self.on_continue()
