"""One reviewed research request to the conversation already selected by the user."""
import uuid

from .chat import ChatError
from .model_settings import choice_summary, research_prompt
from .task_window import replace_text, text_box
from .theme import palette
from .window_frame import WindowFrame


class CommandResearchDialog:
    def __init__(self, library):
        from tkinter import ttk
        self.library, self.view = library, library.window.view
        self.closed, self.review = False, None
        tk = library.manager.tk
        self.root = tk.Toplevel(library.root)
        self.root.title('Find new commands')
        self.root.transient(library.root)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Escape>', lambda _: self.close())
        self.chrome = WindowFrame(self.root, title='Find new commands', close=self.close, minimum=(520, 610))
        self.chrome.place('720x730')
        colors = palette(self.root)
        body = tk.Frame(self.chrome.content, bg=colors.PANEL, padx=14, pady=12)
        body.pack(fill='both', expand=True)
        def label(text):
            widget = tk.Label(body, text=text, bg=colors.PANEL, fg=colors.TEXT, justify='left', anchor='w', wraplength=650)
            widget.pack(fill='x', pady=(0, 7))
            body.bind('<Configure>', lambda e: widget.configure(wraplength=max(180, e.width - 28)), add='+')
        label('Ask the selected agent session to find commands. Review the request before sending. '
              'Results appear in that conversation; suggestions are not automatically added to the library or run in WoW.')
        label('What should the command do?')
        self.query = tk.StringVar(self.root, library.query.get())
        ttk.Entry(body, textvariable=self.query).pack(fill='x', pady=(0, 8))
        label('Client / version (optional; helps avoid commands for the wrong client)')
        self.client = tk.StringVar(self.root, 'WoW Forever; exact build unknown')
        ttk.Entry(body, textvariable=self.client).pack(fill='x', pady=(0, 8))
        self.destination = tk.StringVar(self.root)
        destination_label = tk.Label(body, textvariable=self.destination, bg=colors.PANEL, fg=colors.ACCENT, wraplength=650,
                                     anchor='w', justify='left')
        destination_label.pack(fill='x', pady=(0, 8))
        body.bind('<Configure>', lambda e: destination_label.configure(wraplength=max(180, e.width - 28)), add='+')
        ttk.Button(body, text='Model & usage…', command=self.view.show_model_settings).pack(anchor='w')
        label('Short search: request up to 3 candidates, 2 searches and 400 words. '
              'The agent may use more tokens than the reply length. This is not a hard token or dollar cap. '
              'Attached sessions retain their existing permissions and provider settings.')
        footer = tk.Frame(body, bg=colors.PANEL)
        footer.pack(side='bottom', fill='x', pady=(10, 0))
        self.notice = tk.StringVar(self.root)
        notice_label = tk.Label(footer, textvariable=self.notice, bg=colors.PANEL, fg=colors.MUTED, wraplength=650,
                                justify='left', anchor='w')
        notice_label.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 8))
        footer.bind('<Configure>', lambda e: notice_label.configure(wraplength=max(180, e.width)), add='+')
        self.prepare_button = ttk.Button(footer, text='Review request', command=self.prepare)
        self.prepare_button.grid(row=1, column=0, sticky='ew', padx=2)
        self.send_button = ttk.Button(footer, text='Send one search', command=self.send, state='disabled')
        self.send_button.grid(row=1, column=1, sticky='ew', padx=2)
        ttk.Button(footer, text='Close', command=self.close).grid(row=1, column=2, sticky='ew', padx=2)
        self.renew_button = ttk.Button(footer, text='Allow 3 more searches', command=self.renew)
        self.renew_button.grid(row=2, column=0, columnspan=3, sticky='ew', pady=(8, 0))
        footer.columnconfigure((0, 1, 2), weight=1, uniform='actions')
        self.preview = text_box(tk, body, bg=colors.EDITOR, fg=colors.TEXT, font=('Segoe UI', 10))
        self.query.trace_add('write', self.invalidate)
        self.client.trace_add('write', self.invalidate)
        self.update_destination()
        self.allowance()
        self.chrome.apply_native()

    def update_destination(self):
        session = self.view.selected
        if not session:
            self.destination.set('No selected session. Choose one in the conversation first.')
            return
        try:
            self.destination.set(f'To: {session.title[:70]}\n' + choice_summary(session, self.view.model_preferences().get(session)))
        except (ChatError, OSError):
            self.destination.set('Model settings unavailable. Review cannot proceed until settings can be read.')

    def allowance(self):
        try:
            remaining = self.view.model_preferences().remaining()
            self.notice.set(f'{remaining} research sends left across companion windows. Failed or uncertain attempts also count. '
                            'Ordinary chat and activity requests are outside this allowance.')
            self.renew_button.configure(state='normal' if remaining == 0 else 'disabled')
        except (ChatError, OSError):
            self.notice.set('Research allowance unavailable. Nothing can be sent until it can be read.')
            self.renew_button.configure(state='disabled')

    def invalidate(self, *_):
        self.review = None
        self.send_button.configure(state='disabled')

    def prepare(self):
        self.invalidate()
        try:
            if self.view.closed or self.library.window.view is not self.view:
                raise ChatError('The conversation window changed. Close and reopen Find new commands.')
            self.update_destination()
            if not self.view.selected:
                raise ChatError('Choose an existing conversation before researching commands.')
            preferences = self.view.model_preferences()
            if preferences.remaining() == 0:
                self.allowance()
                return
            body = research_prompt(self.query.get(), self.client.get())
            settings = preferences.get(self.view.selected)
            self.review = (self.view.selected.key, settings, body, str(uuid.uuid4()))
            replace_text(self.preview, self.destination.get() + '\n\n' + body)
            self.send_button.configure(state='normal')
            self.allowance()
        except (ChatError, OSError) as error:
            self.notice.set(str(error) if isinstance(error, ChatError) else 'Could not prepare research. Nothing was sent.')

    def send(self):
        if not self.review:
            return
        key, settings, body, request_id = self.review
        try:
            if (self.view.closed or self.library.window.view is not self.view or not self.view.selected
                    or self.view.selected.key != key or self.view.model_preferences().get(self.view.selected) != settings):
                self.invalidate()
                raise ChatError('Conversation or model settings changed. Review the request again.')
            def delivered(result, error):
                if self.closed:
                    return
                self.allowance()
                self.notice.set((error + ' No automatic retry.') if error else
                                'Search sent once. Read the selected conversation for results; your draft was preserved.')
            if self.view.send_message(body, request_id=request_id, research_settings=settings, on_delivery=delivered):
                self.invalidate()
                self.notice.set('Attempting one search. Read the conversation for delivery and reply status.')
            else:
                self.notice.set('The conversation is busy. Wait for the current action to finish.')
        except (ChatError, OSError) as error:
            self.notice.set(str(error) if isinstance(error, ChatError) else 'Research could not be sent.')

    def renew(self):
        try:
            self.view.model_preferences().renew()
            self.invalidate()
            self.allowance()
        except (ChatError, OSError):
            self.notice.set('Could not renew the research allowance. Nothing was sent.')

    def close(self):
        self.closed = True
        self.library.research_dialog = None
        self.root.destroy()
