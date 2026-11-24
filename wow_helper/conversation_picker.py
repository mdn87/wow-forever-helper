"""Chat selection and saved-draft recovery. These dialogs never dispatch a message."""
from collections import Counter
from pathlib import Path

from .theme import palette, is_modern
from .window_frame import WindowFrame, setup_dialog


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
        self.closed = self.creating = self.scanning = False
        self.generation = 0
        self.scan_timer = None
        self.selected_key = view.selection_key
        self._live_verified = False
        tk = view.tk
        self.root = tk.Toplevel(parent)
        self.chrome = setup_dialog(self.root, parent, title='Choose a chat', close=self.close,
                                   minimum=(410, 340), size=(620, 410))
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
        header = tk.Frame(body, bg=colors.PANEL)
        header.pack(fill='x')
        tk.Label(header, text='Use an existing or active chat', bg=colors.PANEL, fg=colors.TEXT).pack(side='left')
        self.active_only = tk.BooleanVar(master=self.root, value=False)
        self.refresh_button = ttk.Button(header, text='Refresh', style='Agent.TButton', command=self.scan)
        self.refresh_button.pack(side='right')
        self.active_check = ttk.Checkbutton(header, text='Active only', variable=self.active_only,
                                            command=self._filter_changed)
        self.active_check.pack(side='right', padx=(0, 8))
        footer = tk.Frame(body, bg=colors.PANEL)
        footer.pack(side='bottom', fill='x', pady=(6, 0))
        self.attach = ttk.Button(footer, text='Use selected chat', style='Primary.TButton', command=self.choose)
        self.attach.pack(side='left')
        ttk.Button(footer, text='Cancel', command=self.close).pack(side='right')
        self.notice = tk.StringVar(self.root)
        notice_label = tk.Label(body, textvariable=self.notice, bg=colors.PANEL, fg=colors.MUTED,
                                anchor='w', justify='left', wraplength=560)
        notice_label.pack(side='bottom', fill='x', pady=(4, 0))
        body.bind('<Configure>', lambda e: notice_label.configure(wraplength=max(160, e.width - 12)), add='+')
        self.rows = tk.Listbox(body, height=5, width=1, exportselection=False, bg=colors.EDITOR,
                               fg=colors.TEXT, selectbackground=colors.SELECT,
                               selectforeground=colors.TEXT if is_modern(self.root) else colors.ACCENT)
        self.rows._companion_theme_refresh = self._refresh_rows_theme
        self.rows.pack(fill='both', expand=True, pady=(4, 0))
        self.keys = []
        self._sessions_by_key = {}
        self.populate()
        self.rows.bind('<<ListboxSelect>>', self._selection_changed)
        self.rows.bind('<Double-Button-1>', self.choose)
        self.rows.bind('<Return>', self.choose)
        for key in ('Return', 'KP_Enter'):
            self.root.bind(f'<KeyRelease-{key}>', view._release_enter)
        self.chrome.apply_native()
        self.rows.focus_set()
        self._schedule_scan(1500)

    def _refresh_rows_theme(self):
        colors = palette(self.root)
        self.rows.configure(bg=colors.EDITOR, fg=colors.TEXT, selectbackground=colors.SELECT,
                            selectforeground=colors.TEXT if is_modern(self.root) else colors.ACCENT)

    def _schedule_scan(self, delay):
        if self.scan_timer is not None:
            try:
                self.root.after_cancel(self.scan_timer)
            except Exception:
                pass
            self.scan_timer = None
        if delay is not None and not self.closed:
            self.scan_timer = self.root.after(delay, self.scan)

    def _selection_changed(self, _event=None):
        row = self.rows.curselection()
        if row and 0 <= row[0] < len(self.keys):
            self.selected_key = self.keys[row[0]]
        self._update_attach_state()

    def _update_attach_state(self):
        has_valid = self.selected_key in self.keys and not self.scanning and not self.creating
        self.attach.state(['!disabled'] if has_valid else ['disabled'])

    def _filter_changed(self):
        self.populate()

    def _visible_sessions(self, discovered=None):
        if self.active_only.get():
            return self.view.active_sessions(self.view.sessions if discovered is None else discovered)
        return self.view.attachable_sessions(discovered)

    def populate(self, *, discovered=None, disappeared_notice=False):
        if not disappeared_notice:
            row = self.rows.curselection()
            if row and 0 <= row[0] < len(self.keys):
                self.selected_key = self.keys[row[0]]
        wanted = self.selected_key
        sessions = self._visible_sessions(discovered)
        self.keys = [s.key for s in sessions]
        self._sessions_by_key = {s.key: s for s in sessions}
        self.rows.delete(0, 'end')
        for label in session_labels(sessions):
            self.rows.insert('end', label)
        if wanted in self.keys:
            idx = self.keys.index(wanted)
            self.rows.selection_set(idx)
            self.rows.see(idx)
            self.notice.set('Select a chat, then press Send in the composer.')
        elif wanted is not None and disappeared_notice:
            self.selected_key = None
            self.notice.set('That chat closed or became unavailable. Choose another open chat.')
        elif not self.keys:
            self.selected_key = None
            self.notice.set(self.view.empty_active_sessions if self.active_only.get() else 'No open chats found.')
        else:
            self.selected_key = None
            self.notice.set('Select a chat, then press Send in the composer.')
        self._update_attach_state()

    def scan(self, requested=None):
        self._schedule_scan(None)
        if self.closed or self.scanning or self.creating:
            return False
        if not hasattr(self.view.service, 'discover'):
            return False
        self.generation += 1
        generation = self.generation
        self.scanning = True
        self.refresh_button.state(['disabled'])
        self._update_attach_state()
        self.notice.set('Checking open chats…')

        def done(result, error):
            if self.closed or generation != self.generation:
                return
            self.scanning = False
            self.refresh_button.state(['!disabled'])
            if error:
                self.notice.set(str(error))
                self._update_attach_state()
                self._schedule_scan(15000)
                return
            sessions, notices = result
            self._live_verified = True
            self.view.sessions = list(sessions)
            self.view._session_labels()
            if requested is not None:
                visible = self._visible_sessions(sessions)
                match = next((s for s in visible if s.key == requested), None)
                if match is not None:
                    self.view._select_session(match)
                    self.close()
                    return
                self.selected_key = requested
                self.populate(discovered=sessions, disappeared_notice=True)
                self._schedule_scan(15000)
                return
            had_selection = self.selected_key is not None
            self.populate(discovered=sessions, disappeared_notice=had_selection)
            if notices and not had_selection:
                self.notice.set(' · '.join(notices))
            self._schedule_scan(15000)

        if not self.view._submit('picker-discover', self.view.service.discover, on_result=done):
            self.scanning = False
            self.refresh_button.state(['!disabled'])
            self._update_attach_state()
            self._schedule_scan(500)
            return False
        return True

    def choose(self, _event=None):
        if self.closed or self.scanning or self.creating:
            return 'break'
        row = self.rows.curselection()
        key = self.keys[row[0]] if row and 0 <= row[0] < len(self.keys) else self.selected_key
        if key is None or key not in self.keys:
            self.notice.set('Choose an available chat first.')
            self._update_attach_state()
            return 'break'
        self.selected_key = key
        if getattr(_event, 'keysym', '') in ('Return', 'KP_Enter'):
            self.view._held_enter = True
        if self._live_verified and hasattr(self.view.service, 'discover'):
            self.scan(requested=key)
            return 'break'
        session = self._sessions_by_key.get(key) or next((s for s in self.view.sessions if s.key == key), None)
        if session is not None:
            self.view._select_session(session)
            self.close()
        else:
            self.selected_key = None
            self.populate(disappeared_notice=True)
        return 'break'

    def create(self, provider):
        if self.closed or self.creating:
            return
        self._schedule_scan(None)
        self.creating = self.view.start_session(provider, picker=self)
        if self.creating:
            self.notice.set(f'Preparing a {provider.title()} chat…')
            for button in self.providers.values():
                button.state(['disabled'])
            self._update_attach_state()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.generation += 1
        self._schedule_scan(None)
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
        self.chrome = setup_dialog(self.root, view.root, title='Saved draft', close=self.close,
                                   minimum=(390, 260), size=(540, 350))
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
