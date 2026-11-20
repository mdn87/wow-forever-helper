"""One reviewed research request to the conversation already selected by the user."""
import threading
import uuid

from .chat import ChatError
from .model_settings import choice_summary, research_prompt
from .task_window import replace_text, text_box
from .theme import palette
from .window_frame import WindowFrame


def research_answer(session, request, prompt, messages, status):
    """Match a finished answer to the reviewed search, even in a busy shared chat."""
    if session.managed:
        if status == 'completed':
            return next((m.text for m in messages if m.role == 'assistant' and m.id == request + ':assistant'), '')
        return ''
    marker = f'[WoW search {request}]'
    turns = {m.turn_id for m in messages if m.role == 'user' and m.text.strip() == prompt and m.turn_id}
    for message in reversed(messages):
        if message.role != 'assistant' or message.phase in ('commentary', 'partial_answer'):
            continue
        if message.turn_id and turns and message.turn_id not in turns:
            continue
        body = message.text.rstrip()
        if body.splitlines()[-1:] == [marker]:
            return body[:-len(marker)].strip()
        if message.turn_id in turns and message.phase == 'final_answer':
            return body
    return ''


class CommandResearchDialog:
    def __init__(self, library, window):
        from tkinter import ttk
        self.library, self.window, self.view = library, window, window.view
        self.tracking = self.answer_source = None
        self.closed, self.review = False, None
        self.valid = threading.Event()
        self.last_state = self.timer = None
        tk = library.manager.tk
        self.root = tk.Toplevel(library.root)
        self.root.title('Search online with your agent')
        self.root.transient(library.root)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Escape>', lambda _: self.close())
        self.chrome = WindowFrame(self.root, title='Search online with your agent', close=self.close, minimum=(520, 610))
        self.chrome.place('720x730')
        colors = palette(self.root)
        body = tk.Frame(self.chrome.content, bg=colors.PANEL, padx=14, pady=12)
        body.pack(fill='both', expand=True)
        def label(text):
            widget = tk.Label(body, text=text, bg=colors.PANEL, fg=colors.TEXT, justify='left', anchor='w', wraplength=650)
            widget.pack(fill='x', pady=(0, 7))
            body.bind('<Configure>', lambda e: widget.configure(wraplength=max(180, e.width - 28)), add='+')
        label('Ask your agent to search the web for a WoW answer and cite its sources. The reply appears here and in your chat.')
        label('Your question')
        self.query = tk.StringVar(self.root, library.query.get())
        self.query_entry = ttk.Entry(body, textvariable=self.query)
        self.query_entry.pack(fill='x', pady=(0, 8))
        label('Client / version (optional; helps avoid commands for the wrong client)')
        self.client = tk.StringVar(self.root, 'WoW Forever; exact build unknown')
        ttk.Entry(body, textvariable=self.client).pack(fill='x', pady=(0, 8))
        self.destination = tk.StringVar(self.root)
        destination_label = tk.Label(body, textvariable=self.destination, bg=colors.PANEL, fg=colors.ACCENT, wraplength=650,
                                     anchor='w', justify='left')
        destination_label.pack(fill='x', pady=(0, 8))
        body.bind('<Configure>', lambda e: destination_label.configure(wraplength=max(180, e.width - 28)), add='+')
        choices = tk.Frame(body, bg=colors.PANEL)
        choices.pack(fill='x', pady=(0, 5))
        self.chat_button = ttk.Button(choices, text='Change chat', command=self.choose_chat)
        self.chat_button.pack(side='left')
        self.model_button = ttk.Button(choices, text='Change model', command=self.choose_model)
        self.model_button.pack(side='left', padx=5)
        self.local_usage = tk.StringVar(self.root)
        tk.Label(body, textvariable=self.local_usage, bg=colors.PANEL, fg=colors.TEXT, anchor='w').pack(fill='x')
        label('One search requests up to 3 commands, 2 web searches and 400 words. Longer chats can use more '
              'context. Actual provider usage varies.')
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
        self.renew_button.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        self.view_chat = ttk.Button(footer, text='View chat', command=self.open_answer_chat, state='disabled')
        self.view_chat.grid(row=2, column=2, sticky='ew', pady=(8, 0))
        footer.columnconfigure((0, 1, 2), weight=1, uniform='actions')
        self.preview = text_box(tk, body, bg=colors.EDITOR, fg=colors.TEXT, font=('Segoe UI', 10))
        self.query.trace_add('write', self.invalidate)
        self.client.trace_add('write', self.invalidate)
        self.watch()
        self.chrome.apply_native()

    def returned(self):
        if not self.closed:
            self.sync()
            if self.view.selected and self.query.get().strip() and not self.valid.is_set():
                self.prepare()
            self.root.lift()
            self.query_entry.focus_set()

    def choose_chat(self):
        self.view.choose_chat(self.root, self.returned)

    def choose_model(self):
        self.view.show_model_settings(self.root, self.returned)

    def sync(self):
        session = self.view.selected
        prefs = self.view.model_preferences()
        try:
            remaining, epoch = prefs.allowance()
            choice = prefs.snapshot(session) if session else None
            state = self.view.selection_revision, choice, epoch, remaining == 0
            if self.last_state is not None and self.last_state != state and self.review:
                self.invalidate()
                self.notice.set('Chat, model or research allowance changed. Review the request again.')
            self.last_state = state
            self.destination.set(f'{session.title[:70]}\n' + choice_summary(session, choice.settings)
                                 if session else 'Choose the chat that should receive this search.')
            self.model_button.configure(text='Change model' if session else 'Find active sessions')
            self.local_usage.set(f'Companion research attempts · {remaining} of 3 left across windows')
            self.renew_button.state(['!disabled'] if remaining == 0 else ['disabled'])
            return choice, remaining, epoch
        except (ChatError, OSError):
            self.invalidate()
            self.local_usage.set('Companion research allowance unavailable')
            self.renew_button.state(['disabled'])
            return None, 0, None

    def watch(self):
        if not self.closed:
            self.sync()
            self.timer = self.root.after(750, self.watch)

    def stop_watching(self):
        if self.tracking:
            self.view.reply_watchers.pop(self.tracking, None)
            self.tracking = None

    def open_answer_chat(self):
        if self.answer_source:
            try:
                self.library.manager.resume_conversation(self.answer_source)
            except ChatError as error:
                self.notice.set(str(error))
                return
            self.library.close()

    def invalidate(self, *_):
        self.stop_watching()
        self.answer_source = None
        self.view_chat.configure(state='disabled')
        self.valid.clear()
        self.review = None
        self.send_button.configure(state='disabled')
        replace_text(self.preview, '')

    def prepare(self):
        self.invalidate()
        try:
            if self.view.closed or self.window.view is not self.view:
                raise ChatError('The conversation window changed. Reopen Search online.')
            settings, remaining, epoch = self.sync()
            if not self.view.selected:
                self.choose_chat()
                return
            if not remaining or not settings:
                return
            request = str(uuid.uuid4())
            body = research_prompt(self.query.get(), self.client.get(), request_id=None if self.view.selected.managed else request)
            self.valid = threading.Event()
            self.valid.set()
            self.review = (self.view.selection_revision, settings, epoch, body, request)
            replace_text(self.preview, self.destination.get() + '\n\n' + body)
            self.send_button.configure(state='normal')
            self.notice.set('Review the exact request below before sending.')
        except (ChatError, OSError) as error:
            self.notice.set(str(error) if isinstance(error, ChatError) else 'Could not prepare research. Nothing was sent.')

    def send(self):
        if not self.review:
            return
        revision, settings, epoch, body, request_id = self.review
        try:
            current, remaining, current_epoch = self.sync()
            if (self.view.closed or self.window.view is not self.view or revision != self.view.selection_revision
                    or settings != current or epoch != current_epoch or not remaining):
                self.invalidate()
                raise ChatError('Chat, model or allowance changed. Review the request again.')
            session, valid = self.view.selected, self.valid
            def delivered(result, error):
                if self.closed or not valid.is_set():
                    return
                self.sync()
                if error:
                    self.notice.set(error)
                    return
                self.answer_source = {'provider': session.provider,
                                      'session_id': session.id, 'request_id': request_id}
                self.view_chat.configure(state='normal')
                self.notice.set(f'Waiting for {session.title[:50]} to answer. You can also view the chat.')
                self.tracking = (session.key, request_id)
                def receive(messages, status):
                    if status in ('failed', 'cancelled', 'interrupted'):
                        self.stop_watching()
                        self.notice.set(f'The search was {status}. View the chat for delivery details.')
                        return
                    answer = research_answer(session, request_id, body, messages, status)
                    if answer:
                        self.stop_watching()
                        replace_text(self.preview, f'Answer from {session.provider.title()} · {session.title[:70]}\n\n{answer}')
                        self.notice.set('Research reply received.')
                self.view.reply_watchers[self.tracking] = receive
            if self.view.send_message(body, request_id=request_id, choice=settings, research_epoch=epoch,
                                      still_current=self.valid.is_set, on_delivery=delivered, decision_parent=self.root):
                self.review = None
                self.send_button.configure(state='disabled')
                self.notice.set('Checking the selected chat and provider usage…')
            else:
                self.notice.set(self.view.status.get())
        except (ChatError, OSError) as error:
            self.notice.set(str(error) if isinstance(error, ChatError) else 'Research could not be sent.')

    def renew(self):
        try:
            self.view.model_preferences().renew()
            self.invalidate()
            self.sync()
        except (ChatError, OSError):
            self.notice.set('Could not renew the research allowance. Nothing was sent.')

    def close(self):
        self.closed = True
        self.stop_watching()
        self.valid.clear()
        if self.timer:
            self.root.after_cancel(self.timer)
        for dialog in (self.view._picker, getattr(self.view, '_model_dialog', None), self.view._usage_dialog):
            if dialog and dialog.root.master is self.root:
                dialog.close()
        self.library.research_dialog = None
        self.root.destroy()
