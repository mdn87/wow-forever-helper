"""Model selection without credentials, provider configuration, or inference probes."""
from .chat import ChatError
from .model_settings import EFFORTS, choice_summary
from .task_window import replace_text, text_box
from .theme import palette
from .window_frame import WindowFrame


class ModelSettingsDialog:
    def __init__(self, view):
        from tkinter import ttk
        self.view, self.session = view, view.selected
        self.closed, self.models = False, []
        tk = view.tk
        self.root = tk.Toplevel(view.root)
        self.root.title('Model & usage')
        self.root.transient(view.root.winfo_toplevel())
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Escape>', lambda _: self.close())
        self.chrome = WindowFrame(self.root, title='Model & usage', close=self.close, minimum=(500, 600))
        self.chrome.place('680x700')
        colors = palette(self.root)
        body = tk.Frame(self.chrome.content, bg=colors.PANEL, padx=14, pady=12)
        body.pack(fill='both', expand=True)
        def label(text):
            widget = tk.Label(body, text=text, bg=colors.PANEL, fg=colors.TEXT, justify='left', anchor='w', wraplength=620)
            widget.pack(fill='x', pady=(0, 8))
            body.bind('<Configure>', lambda e: widget.configure(wraplength=max(180, e.width - 28)), add='+')
        label(f'Conversation: {self.session.title[:80]}')
        label('Choose speed and reasoning for this conversation. A subscription has limits too. '
              'Lower effort usually uses less reasoning; model prices and plan allowances vary. '
              'These controls do not set a dollar or token cap.')
        try:
            settings = view.model_preferences().get(self.session)
        except (ChatError, OSError) as error:
            settings = {'model': '', 'effort': '', 'timeout': 180}
            label(str(error))
        label('Model (blank inherits the provider/session default; not necessarily cheapest)')
        self.model = tk.StringVar(self.root, settings['model'])
        values = ('', 'haiku', 'sonnet', 'opus') if self.session.provider == 'claude' else ('',)
        self.model_choice = ttk.Combobox(body, textvariable=self.model, values=values)
        self.model_choice.pack(fill='x', pady=(0, 8))
        label('Reasoning effort (blank uses the provider/session default)')
        self.effort = tk.StringVar(self.root, settings['effort'])
        self.effort_choice = ttk.Combobox(body, textvariable=self.effort, values=EFFORTS, state='readonly')
        self.effort_choice.pack(fill='x', pady=(0, 8))
        label('Companion-owned CLI time limit in seconds (not a token limit)' if self.session.managed else
              'Time limit: controlled by the attached session; the companion cannot stop it.')
        self.timeout = tk.StringVar(self.root, str(settings['timeout']))
        self.timeout_choice = ttk.Combobox(body, textvariable=self.timeout, values=('90', '180', '360', '600'), state='readonly')
        if self.session.managed:
            self.timeout_choice.pack(fill='x', pady=(0, 8))
        if not self.session.managed:
            self.timeout_choice.configure(state='disabled')
        self.external_claude = self.session.provider == 'claude' and not self.session.managed
        if self.external_claude:
            self.model_choice.configure(state='disabled')
            self.effort_choice.configure(state='disabled')
            label('Attached Claude: use /model and /effort in that session; use /usage to check your plan. '
                  'The inbox connection cannot change these settings.')
        elif not self.session.managed:
            label('Attached Codex: choose a listed model to override settings on the next send. '
                  'The session must be idle. The choice also affects later turns in Codex. Standard speed is used.')
        else:
            label('Saved choices apply on the next companion send, including resumed conversations. '
                  'Unavailable choices fail without a companion fallback. No extra inference runs to test a model.')
        footer = tk.Frame(body, bg=colors.PANEL)
        footer.pack(side='bottom', fill='x', pady=(8, 0))
        self.notice = tk.StringVar(self.root, 'Loading available models and usage; no inference request…')
        notice_label = tk.Label(footer, textvariable=self.notice, bg=colors.PANEL, fg=colors.MUTED, wraplength=600,
                                justify='left', anchor='w')
        notice_label.pack(fill='x')
        footer.bind('<Configure>', lambda e: notice_label.configure(wraplength=max(180, e.width)), add='+')
        self.save_button = ttk.Button(footer, text='Save for next send', command=self.save,
                                      state='disabled' if self.external_claude else 'normal')
        self.save_button.pack(side='left', pady=8)
        ttk.Button(footer, text='Refresh models / usage', command=self.load).pack(side='left', padx=8)
        ttk.Button(footer, text='Close', command=self.close).pack(side='right')
        self.details = text_box(tk, body, bg=colors.EDITOR, fg=colors.TEXT, font=('Segoe UI', 10))
        self.model.trace_add('write', self.model_changed)
        self.model_changed()
        self.chrome.apply_native()
        self.load()

    def model_changed(self, *_):
        selected = next((m for m in self.models if m.get('model') == self.model.get()), None)
        efforts = ('', 'low', 'medium', 'high') if self.session.provider == 'claude' else EFFORTS
        if selected:
            efforts = ('',) + tuple(e['reasoningEffort'] for e in selected.get('supportedReasoningEfforts', []))
        self.effort_choice.configure(values=efforts)
        if self.effort.get() not in efforts:
            self.effort.set('')

    def load(self):
        def done(result, error):
            if self.closed:
                return
            if error:
                self.notice.set('Model list / quota unavailable. No inference was run. Check the provider before spending usage.')
                replace_text(self.details, 'No current quota estimate. Unknown does not mean unlimited.')
                return
            self.models, usage = result
            if self.session.provider == 'codex':
                self.model_choice.configure(values=('',) + tuple(m['model'] for m in self.models),
                                            state='normal' if self.session.managed else 'readonly')
            self.model_changed()
            descriptions = ('Claude aliases: haiku for quick, simple questions; sonnet for a balance; opus for demanding work. '
                            'Access and usage rates depend on your plan. The companion does not automatically upgrade your model.'
                            if self.session.provider == 'claude' else
                            '\n\n'.join(f'{m["model"]}: {m.get("description", "")}' for m in self.models))
            replace_text(self.details, usage + '\n\n' + descriptions + '\n\nUsage is a snapshot, not a remaining-token guarantee. '
                         'Check provider billing for paid extra usage. Research requests have a separate three-search allowance.')
            self.notice.set('Read-only provider snapshot. No model request or purchase was made.')
        if not self.view._submit('model-options', lambda: self.view.service.model_options(self.session), on_result=done):
            self.notice.set('Wait for the current action, then refresh models / usage.')

    def save(self):
        if not self.view.selected or self.view.selected.key != self.session.key:
            self.notice.set('The selected conversation changed. Reopen Model & usage for that conversation.')
            return
        try:
            model = self.model.get().strip()
            if not self.session.managed and self.session.provider == 'codex':
                if model and model not in {m['model'] for m in self.models}:
                    raise ChatError('Refresh the model list and choose an available model.')
                if not model and self.effort.get():
                    raise ChatError('Choose a model to change effort, or leave both blank to inherit Codex settings.')
            settings = self.view.model_preferences().save(self.session, model=model, effort=self.effort.get(),
                                                          timeout=int(self.timeout.get()))
        except (ChatError, OSError, ValueError) as error:
            self.notice.set(str(error) if isinstance(error, ChatError) else 'Could not save model settings. Nothing changed in the provider.')
            return
        self.view.refresh_model_summary()
        self.notice.set('Saved for next send: ' + choice_summary(self.session, settings))

    def close(self):
        self.closed = True
        self.view._model_dialog = None
        self.root.destroy()
