"""Discover open conversations while the Advanced tab is visible."""
from tkinter import ttk

from .conversation_picker import session_labels


class ActiveSessions:
    def __init__(self, dialog, page):
        self.dialog, self.view, self.page = dialog, dialog.view, page
        self.closed = self.visible = self.scanning = False
        self.timer = None
        self.generation = 0
        self.keys = []
        box = ttk.Frame(page)
        box.pack(fill='x', pady=(0, 5))
        box.columnconfigure(0, weight=1)
        ttk.Label(box, text='Active sessions').grid(row=0, column=0, sticky='w')
        self.refresh = ttk.Button(box, text='Refresh', command=self.scan)
        self.refresh.grid(row=0, column=1, sticky='e')
        self.choice = ttk.Combobox(box, width=1, state='readonly')
        self.choice.grid(row=1, column=0, sticky='ew', padx=(0, 4), pady=3)
        self.use = ttk.Button(box, text='Use session', command=self.attach)
        self.use.grid(row=1, column=1, sticky='e')
        self.notice = self.view.tk.StringVar(dialog.root)
        status = ttk.Label(box, textvariable=self.notice, wraplength=340)
        status.grid(row=2, column=0, columnspan=2, sticky='w')
        box.bind('<Configure>', lambda e: status.configure(wraplength=max(100, e.width - 2)))
        self.use.state(['disabled'])
        self.choice.bind('<<ComboboxSelected>>', self.controls)
        dialog.tabs.bind('<<NotebookTabChanged>>', self.tab_changed)

    def tab_changed(self, _=None):
        if self.closed:
            return
        visible = self.dialog.tabs.select() == str(self.page)
        if visible != self.visible:
            self.visible = visible
            self.generation += 1
            self.schedule(None)
            if visible:
                self.scan()

    def schedule(self, delay):
        if self.timer is not None:
            self.page.after_cancel(self.timer)
            self.timer = None
        if delay is not None and self.visible and not self.closed:
            self.timer = self.page.after(delay, self.scan)

    def key(self):
        index = self.choice.current()
        return self.keys[index] if 0 <= index < len(self.keys) else None

    def controls(self, _=None):
        current = self.view.selected.key if self.view.selected else None
        usable = self.key() is not None and self.key() != current and not self.scanning
        self.use.state(['!disabled'] if usable else ['disabled'])

    def attach(self):
        key = self.key()
        if key and not self.use.instate(['disabled']):
            self.scan(key)

    def scan(self, requested=None):
        self.schedule(None)
        if self.closed or not self.visible or self.scanning:
            return
        generation = self.generation
        self.scanning = True
        self.controls()
        self.refresh.state(['disabled'])
        self.notice.set('Checking open sessions…')
        if requested:
            self.choice.configure(state='disabled')

        def done(result, error):
            if self.closed:
                return
            self.scanning = False
            self.refresh.state(['!disabled'])
            self.choice.configure(state='readonly')
            if not self.visible or self.generation != generation:
                self.schedule(0)
                return
            if not self.dialog.current():
                self.dialog.show_session(advanced=True)
                return
            previous = self.key()
            sessions, notices = result if not error else ([], [error])
            active = self.view.active_sessions(sessions)
            self.keys = [s.key for s in active]
            self.choice.configure(values=session_labels(active))
            selected = previous if previous in self.keys else self.view.selection_key
            if selected in self.keys:
                self.choice.current(self.keys.index(selected))
            else:
                self.choice.set('Select a session…' if active else '')
            if requested and requested == previous and requested in self.keys:
                self.view.sessions = list(sessions)
                self.view._session_labels()
                self.view._select_session(active[self.keys.index(requested)])
                self.dialog.show_session(advanced=True)
                return
            if requested:
                self.notice.set('That session closed or became unavailable. Choose an open session.')
            elif notices:
                self.notice.set(' · '.join(notices))
            else:
                self.notice.set('' if active else self.view.empty_active_sessions)
            self.controls()
            self.schedule(30000)

        if not self.view._submit('attach-session' if requested else 'active-sessions',
                                 self.view.service.discover, on_result=done):
            self.scanning = False
            self.refresh.state(['!disabled'])
            self.choice.configure(state='readonly')
            if requested:
                self.notice.set('Another chat action is in progress. Select the session again when it finishes.')
                self.controls()
            self.schedule(250)

    def close(self):
        self.closed = True
        self.schedule(None)
