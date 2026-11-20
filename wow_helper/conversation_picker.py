"""Chat selection and saved-draft recovery. These dialogs never dispatch a message."""
from collections import Counter
from pathlib import Path

from .theme import palette
from .window_frame import WindowFrame


def session_labels(sessions):
    rows = [(s.provider.title(), s.title.replace('\n', ' ')[:55],
             'Companion' if s.managed else 'External', s.status) for s in sessions]
    titles = Counter(row[:2] for row in rows)
    short = [s.id[-8:] for s in sessions]
    suffixes = Counter(short)
    labels = []
    for s, row, suffix in zip(sessions, rows, short):
        label = ' · '.join(row)
        if titles[row[:2]] > 1:
            label += ' · ' + ' · '.join(filter(None, (Path(s.project).name, s.id if suffixes[suffix] > 1 else suffix)))
        labels.append(label)
    return labels


class ConversationPicker:
    def __init__(self, view, parent, on_close):
        from tkinter import ttk
        self.view, self.on_close = view, on_close
        self.closed = self.creating = False
        tk = view.tk
        self.root = tk.Toplevel(parent)
        self.root.title('Choose a chat')
        self.root.transient(parent.winfo_toplevel())
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.chrome = WindowFrame(self.root, title='Choose a chat', close=self.close, minimum=(390, 300))
        self.chrome.place('600x360')
        colors = palette(self.root)
        body = tk.Frame(self.chrome.content, bg=colors.PANEL, padx=12, pady=10)
        body.pack(fill='both', expand=True)
        tk.Label(body, text='Start a new chat', bg=colors.PANEL, fg=colors.TEXT).pack(anchor='w')
        buttons = tk.Frame(body, bg=colors.PANEL)
        buttons.pack(fill='x', pady=(3, 9))
        self.providers = {}
        for provider in ('codex', 'claude'):
            b = ttk.Button(buttons, text=provider.title(), command=lambda p=provider: self.create(p))
            b.pack(side='left', padx=(0, 5))
            if not hasattr(view.service, 'create'):
                b.state(['disabled'])
            self.providers[provider] = b
        tk.Label(body, text='Use an existing chat', bg=colors.PANEL, fg=colors.TEXT).pack(anchor='w')
        footer = tk.Frame(body, bg=colors.PANEL)
        footer.pack(side='bottom', fill='x', pady=(6, 0))
        self.attach = ttk.Button(footer, text='Use selected chat', command=self.choose)
        self.attach.pack(side='left')
        ttk.Button(footer, text='Cancel', command=self.close).pack(side='right')
        self.notice = tk.StringVar(self.root)
        tk.Label(body, textvariable=self.notice, bg=colors.PANEL, fg=colors.MUTED, anchor='w').pack(side='bottom', fill='x')
        self.rows = tk.Listbox(body, height=4, width=1, exportselection=False, bg=colors.EDITOR,
                               fg=colors.TEXT, selectbackground=colors.ACCENT)
        self.rows.pack(fill='both', expand=True)
        self.keys = []
        self.populate()
        self.rows.bind('<Double-Button-1>', self.choose)
        self.rows.bind('<Return>', self.choose)
        self.root.bind('<Escape>', lambda _: self.close())
        for key in ('Return', 'KP_Enter'):
            self.root.bind(f'<KeyRelease-{key}>', view._release_enter)
        self.chrome.apply_native()
        self.rows.focus_set()

    def populate(self):
        selected = self.rows.curselection()
        key = self.keys[selected[0]] if selected else self.view.selection_key
        sessions = self.view.attachable_sessions()
        self.keys = [s.key for s in sessions]
        self.rows.delete(0, 'end')
        for label in session_labels(sessions):
            self.rows.insert('end', label)
        if key in self.keys:
            self.rows.selection_set(self.keys.index(key))
        self.attach.state(['!disabled'] if self.keys else ['disabled'])
        self.notice.set('Select a chat, then press Send in the composer.' if self.keys else 'No open chats found.')

    def choose(self, _event=None):
        row = self.rows.curselection()
        if row and not self.closed:
            session = next((s for s in self.view.sessions if s.key == self.keys[row[0]]), None)
            if session:
                if getattr(_event, 'keysym', '') in ('Return', 'KP_Enter'):
                    self.view._held_enter = True
                self.view._select_session(session)
                self.close()
        return 'break'

    def create(self, provider):
        if self.closed or self.creating:
            return
        self.creating = self.view.start_session(provider, picker=self)
        if self.creating:
            self.notice.set(f'Preparing a {provider.title()} chat…')
            for button in self.providers.values():
                button.state(['disabled'])

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.creating and self.view.pending_creation:
            self.view.pending_creation = None
            self.view.selection_revision += 1
            self.view.on_change()
        self.view._picker = None
        self.root.destroy()
        if not self.view.closed:
            if self.on_close:
                self.on_close()
            else:
                self.view.editor.focus_set()


class SavedDraftDialog:
    def __init__(self, view):
        from tkinter import ttk
        self.view, self.key = view, view.selection_key
        tk = view.tk
        self.root = tk.Toplevel(view.root)
        self.root.title('Saved draft')
        self.root.transient(view.root.winfo_toplevel())
        self.chrome = WindowFrame(self.root, title='Saved draft', close=self.close, minimum=(390, 260))
        self.chrome.place('540x350')
        colors = palette(self.root)
        body = tk.Frame(self.chrome.content, bg=colors.PANEL, padx=12, pady=10)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Saved draft for ' + view.session_title[:48]).pack(anchor='w')
        actions = tk.Frame(body, bg=colors.PANEL)
        actions.pack(side='bottom', fill='x', pady=(8, 0))
        for title, command in [('Use saved draft', lambda: self.apply(False)),
                               ('Append to draft', lambda: self.apply(True)), ('Close', self.close)]:
            ttk.Button(actions, text=title, command=command).pack(side='left', padx=2)
        self.preview = tk.Text(body, height=3, width=1, wrap='word', bg=colors.EDITOR, fg=colors.TEXT)
        self.preview.pack(fill='both', expand=True)
        self.preview.insert('1.0', view.saved_drafts[self.key])
        self.preview.configure(state='disabled')
        self.root.bind('<Escape>', lambda _: self.close())
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.chrome.apply_native()

    def apply(self, append):
        view = self.view
        if self.key == view.selection_key and self.key in view.saved_drafts:
            old = view.editor.get('1.0', 'end-1c')
            saved = view.saved_drafts[self.key]
            view.saved_drafts[self.key] = old
            view.replace_draft('\n'.join(filter(None, (old, saved))) if append else saved)
            view._update_controls()
            view.on_change()
        self.close()

    def close(self):
        self.view._draft_dialog = None
        self.root.destroy()
        if not self.view.closed:
            self.view.editor.focus_set()
