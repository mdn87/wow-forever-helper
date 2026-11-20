"""Per-conversation effort, model selection and read-only account usage."""
from .chat import ChatError
from .model_settings import EFFORTS, choice_summary
from .theme import palette
from .window_frame import WindowFrame

PRESETS = (('Quick question', 'low', 'Look up one setting'),
           ('Everyday help', 'medium', 'Compare settings or troubleshoot'),
           ('Complex question', 'high', 'Work through conflicting evidence'))
ALIASES = {'haiku': 'Fast responses for straightforward questions.',
           'sonnet': 'A balance for everyday comparisons and troubleshooting.',
           'opus': 'For demanding reasoning. Usage can be higher.'}


class ModelSettingsDialog:
    def __init__(self, view, parent=None, on_close=None):
        from tkinter import ttk
        self.view, self.session, self.on_close = view, view.selected, on_close
        self.selection = view.selection_revision
        self.external_claude = not self.session.managed and self.session.provider == 'claude'
        self.external_codex = not self.session.managed and self.session.provider == 'codex'
        self.closed, self.models, self.reading = False, [], None
        self.known_models = set()
        self.usage_timer = None
        tk = view.tk
        self.root = tk.Toplevel(parent or view.root)
        self.root.title('Change model')
        self.root.transient((parent or view.root).winfo_toplevel())
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Escape>', lambda _: self.close())
        self.chrome = WindowFrame(self.root, title='Change model', close=self.close, minimum=(430, 475))
        self.chrome.place('620x580')
        self.colors = colors = palette(self.root)
        body = tk.Frame(self.chrome.content, bg=colors.PANEL, padx=12, pady=8)
        body.pack(fill='both', expand=True)
        self.base = view.displayed_choice
        if self.base and self.base.catalog_bound:
            self.known_models.add(self.base.model)
        self.model = tk.StringVar(self.root, self.base.model if self.base else '')
        self.effort = tk.StringVar(self.root, self.base.effort if self.base else '')
        self.timeout = tk.StringVar(self.root, str(self.base.timeout if self.base else 180))
        self.override = tk.BooleanVar(self.root, bool(self.base and self.base.model))
        self.proposal = tk.StringVar(self.root)
        self.description = tk.StringVar(self.root)
        self.usage = tk.StringVar(self.root, 'Usage unavailable. Refresh to check the provider.')
        self.notice = tk.StringVar(self.root)
        self.label(body, self.session.title[:80])
        self.label(body, variable=self.proposal)
        footer = tk.Frame(body, bg=colors.PANEL)
        footer.pack(side='bottom', fill='x')
        self.label(footer, variable=self.notice)
        self.save_button = ttk.Button(footer, text='Save for next messages', command=self.save)
        self.save_button.pack(side='left')
        ttk.Button(footer, text='Close', command=self.close).pack(side='right')
        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill='both', expand=True, pady=(2, 8))
        def page(label):
            frame = tk.Frame(self.tabs, bg=colors.PANEL, padx=10, pady=8)
            self.tabs.add(frame, text=label)
            return frame
        main = page('Next message')
        models = self.models_page = page('Models') if not self.external_claude else None
        advanced = self.advanced = page('Advanced') if not self.external_claude else None
        usage = page('Account usage')
        self.presets = {}
        self.model_choice = ttk.Combobox(models or main, textvariable=self.model, state='disabled')
        if self.external_claude:
            self.label(main, 'Model controlled in Claude. Paste a command in the connected Claude chat.')
            for command in ('/model', '/effort', '/usage'):
                ttk.Button(main, text='Copy ' + command, command=lambda c=command: self.copy(c)).pack(anchor='w', pady=3)
        else:
            self.label(main, 'Reasoning effort')
            for title, value, _ in PRESETS:
                b = ttk.Radiobutton(main, text=f'{title} · {value.capitalize()}',
                                    variable=self.effort, value=value)
                b.pack(anchor='w', pady=3)
                self.presets[value] = b
            self.preset_hint = tk.StringVar(self.root)
            self.label(main, variable=self.preset_hint)
            self.choose_model_button = ttk.Button(main, text='Choose a different model', command=self.choose_model)
            self.choose_model_button.pack(anchor='w', pady=(8, 4))
            self.label(main, 'Lower effort usually uses fewer reasoning tokens. The model, tools and chat history '
                       'also affect usage and response time. Your provider sets the limits.')
            self.label(models, 'Choose a different model')
            self.model_choice.pack(fill='x')
            self.label(models, variable=self.description)
            ttk.Button(models, text='Keep provider model', command=self.inherit).pack(anchor='w', pady=4)
            if self.external_codex:
                ttk.Checkbutton(advanced, text='Override this Codex chat', variable=self.override,
                                command=self.toggle_override).pack(anchor='w')
                self.label(advanced, 'Sending an override requires an idle thread, uses standard speed and changes '
                           'later turns in the Codex app. Inherit uses the thread’s then-current settings.')
                ttk.Button(advanced, text='Choose advertised model', command=self.choose_model).pack(anchor='w', pady=3)
            else:
                self.label(advanced, 'Manual model ID')
                ttk.Entry(advanced, textvariable=self.model).pack(fill='x')
            self.label(advanced, 'Manual effort')
            self.effort_choice = ttk.Combobox(advanced, textvariable=self.effort, state='readonly', values=EFFORTS)
            self.effort_choice.pack(fill='x')
            if self.session.managed:
                self.label(advanced, 'CLI time limit (seconds)')
                ttk.Combobox(advanced, textvariable=self.timeout, values=('90', '180', '360', '600'),
                             state='readonly').pack(fill='x')
        self.label(usage, 'Your provider account usage')
        ttk.Button(usage, text='Refresh account usage', command=self.load).pack(anchor='w', pady=(2, 6))
        frame = tk.Frame(usage, bg=colors.PANEL)
        frame.pack(fill='both', expand=True)
        self.details = tk.Text(frame, width=1, height=3, wrap='word', bg=colors.EDITOR, fg=colors.TEXT,
                               relief='flat', font=('Segoe UI', 10))
        bar = ttk.Scrollbar(frame, command=self.details.yview)
        bar.pack(side='right', fill='y')
        self.details.configure(yscrollcommand=bar.set)
        self.details.pack(fill='both', expand=True)
        for var in (self.model, self.effort, self.timeout):
            var.trace_add('write', self.changed)
        self.changed()
        self.chrome.apply_native()
        self.render_usage()
        self.load()

    def label(self, parent, text='', variable=None):
        widget = self.view.tk.Label(parent, text=text, textvariable=variable, bg=self.colors.PANEL,
                                    fg=self.colors.TEXT, anchor='w', justify='left', wraplength=350)
        widget.pack(fill='x', pady=(0, 5))
        parent.bind('<Configure>', lambda e: widget.configure(wraplength=max(140, e.width - 24)), add='+')

    def choose_model(self):
        if self.external_codex and not self.override.get():
            self.tabs.select(self.advanced)
            self.notice.set('Enable Override this Codex chat to choose its model.')
        else:
            self.tabs.select(self.models_page)
            self.model_choice.focus_set()

    def inherit(self):
        self.model.set('')
        if self.external_codex:
            self.override.set(False)
            self.effort.set('')
        self.changed()

    def toggle_override(self):
        if not self.override.get():
            self.inherit()
        else:
            self.changed()
            self.choose_model()

    def copy(self, command):
        self.root.clipboard_clear()
        self.root.clipboard_append(command)
        self.notice.set(f'Copied {command}. Paste it in Claude.')

    def changed(self, *_):
        model, effort = self.model.get().strip(), self.effort.get()
        self.proposal.set(choice_summary(self.session, {'model': model, 'effort': effort}))
        if self.external_claude:
            self.save_button.state(['disabled'])
            return
        self.preset_hint.set(next((hint for _, level, hint in PRESETS if level == effort), ''))
        selected = next((m for m in self.models if m.get('model') == model), None)
        names = tuple(m['model'] for m in self.models)
        efforts = EFFORTS
        description = 'The host chooses the model at send time.'
        if self.session.provider == 'claude':
            names, efforts = tuple(ALIASES), ('', 'low', 'medium', 'high')
            if model in ALIASES:
                description = f'{model} is a Claude CLI alias. ' + ALIASES[model]
        if selected:
            efforts = ('',) + tuple(e['reasoningEffort'] for e in selected.get('supportedReasoningEfforts', ()))
            description = selected.get('description') or model
        elif model and model not in ALIASES:
            description = 'Manual model ID. The provider confirms availability on send.'
        self.description.set(description)
        editable = not self.external_codex or self.override.get()
        for level, button in self.presets.items():
            button.state(['!disabled'] if editable and level in efforts and (model or not self.external_codex)
                         else ['disabled'])
        self.model_choice.configure(state='readonly' if editable else 'disabled', values=('', *names))
        self.effort_choice.configure(state='readonly' if editable else 'disabled', values=efforts)
        issue = ''
        if self.external_codex and not self.override.get() and model:
            issue = 'Enable Override this Codex chat before choosing a model.'
        elif self.external_codex and self.override.get() and (not model or not selected):
            issue = 'Choose an advertised model, or turn off Override to inherit the thread settings.'
        elif self.external_codex and model and not effort:
            issue = 'Choose an advertised effort for this override.'
        elif self.external_codex and not model and effort:
            issue = 'An explicit model is needed to set effort on an attached Codex chat.'
        elif model and model in self.known_models and not selected:
            issue = 'This model is no longer advertised. Choose a different model.'
        elif effort not in efforts:
            issue = 'This model does not support the selected effort. Choose a supported effort.'
        self.issue = issue
        self.notice.set(issue)
        self.save_button.state(['disabled'] if issue or self.base is None else ['!disabled'])

    def current(self):
        return (not self.closed and not self.view.closed and self.view.selection_revision == self.selection
                and self.view.selection_key == self.session.key)

    def render_usage(self):
        self.usage_timer = None
        if self.closed:
            return
        scope = getattr(self.view.service, 'usage_scope', None)
        if self.reading and scope and not scope.current(self.reading):
            self.reading = None
            self.usage.set('The provider account changed. Refresh account usage.')
        text = self.reading.describe() if self.reading else self.usage.get()
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')
        self.usage_timer = self.root.after(15000, self.render_usage)

    def load(self):
        def done(result, error):
            if not self.current():
                return
            if error:
                if self.reading:
                    self.reading = self.reading.unavailable()
                self.usage.set('Usage unavailable. Check usage with your provider.')
            else:
                self.models, usage = result
                self.known_models.update(m['model'] for m in self.models)
                if isinstance(usage, str):
                    self.usage.set(usage)
                else:
                    self.reading = usage
            self.changed()
            self.root.after_cancel(self.usage_timer)
            self.render_usage()
        if not self.view._submit('model-options', lambda: self.view.service.model_options(self.session), on_result=done):
            self.notice.set('The current request is in progress. You can refresh usage when it finishes.')

    def save(self):
        if not self.current():
            self.notice.set('The selected chat changed. Reopen Change model.')
            return
        if self.external_claude or self.issue:
            return
        try:
            model = self.model.get().strip()
            self.view.model_preferences().save(self.session, model=model, effort=self.effort.get(),
                                               timeout=int(self.timeout.get()), expected=self.base,
                                               catalog_bound=model in self.known_models)
        except (ChatError, OSError, ValueError) as error:
            self.notice.set(str(error) if isinstance(error, ChatError) else 'Could not save model settings.')
            return
        self.view.refresh_model_summary()
        self.base = self.view.displayed_choice
        self.notice.set('Saved for next messages.')

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.usage_timer:
            self.root.after_cancel(self.usage_timer)
        self.view._model_dialog = None
        self.root.destroy()
        if self.on_close and not self.view.closed:
            self.on_close()
