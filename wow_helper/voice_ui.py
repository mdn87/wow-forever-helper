"""Session-only voice input for an explicitly chosen companion composer."""

from .chat import MAX_MESSAGE
from .journal_ui import JournalDialog
from .voice_input import Dictation, PushToTalkKey


class VoiceDialog(JournalDialog):
    def __init__(self, manager, window, *, dictation_factory=Dictation, key_factory=PushToTalkKey):
        self.manager, self.window = manager, window
        self.dictation_factory, self.key_factory = dictation_factory, key_factory
        self.dictation = self.key = None
        self.target = None
        self.after = None
        super().__init__(window.view, 'Voice input · Ctrl+Alt+V')
        self.notice.set('Voice is off. Enable for this window, then hold your Ctrl+Alt+V mouse button. '
                        'Wait for Listening, speak, and release. Text is added to the draft; nothing is sent.')
        info = self.label(self.surface, 'Local Windows dictation · default microphone\n'
                          '30 seconds maximum · no audio saved · no spoken replies\n'
                          'Enabled only while this panel remains open.\n'
                          'Mouse software must hold the chord, not play a tap macro.')
        info.configure(wraplength=390, justify='left'); info.pack(fill='x', padx=8, pady=8)
        self.enable_button = self.ttk.Button(self.surface, text='Enable for this chat window', command=self.enable)
        self.enable_button.pack(fill='x', padx=8)
        self.hold = self.ttk.Button(self.surface, text='Or hold here to talk', state='disabled')
        self.hold.pack(fill='x', padx=8, pady=6)
        self.hold.bind('<ButtonPress-1>', lambda _: self.start())
        self.hold.bind('<ButtonRelease-1>', lambda _: self.stop())
        self.hold.bind('<KeyPress-space>', lambda _: self.start())
        self.hold.bind('<KeyRelease-space>', lambda _: self.stop())
        self.ttk.Button(self.surface, text='Disable / cancel recording', command=self.disable).pack(fill='x', padx=8)
        self.label(self.surface, 'Last transcript — select and copy if the destination changed').pack(anchor='w', padx=8, pady=(8, 0))
        self.transcript = self.text(self.surface)
        self.after = self.root.after(30, self.poll)
        self.show()

    def enable(self):
        if self.dictation:
            return
        self.dictation = self.dictation_factory()
        self.key = self.key_factory()
        self.enable_button.configure(state='disabled')
        self.hold.configure(state='normal')
        self.notice.set('Voice enabled for this window. Hold Ctrl+Alt+V and wait for Listening. Microphone is off now.')
        self.window.set_notice('Voice enabled: hold Ctrl+Alt+V to dictate. Microphone off.')

    def start(self):
        if not self.dictation or self.dictation.busy:
            return
        view = self.window.view
        if self.window.closed or not view or not view.editor.winfo_exists():
            self.disable(); return
        self.target = (view, view.selection_key, view.selection_revision)
        if self.dictation.start():
            self.set_status('Starting microphone… keep holding; speak when Listening appears.')

    def stop(self):
        if self.dictation:
            self.dictation.stop()

    def set_status(self, text):
        self.notice.set(text)
        if not self.window.closed:
            self.window.set_notice(text)

    def poll(self):
        if self.after:
            self.root.after_cancel(self.after)
        self.after = None
        if self.dictation:
            for kind, text in self.dictation.poll():
                if kind == 'listening':
                    self.set_status('Listening · release Ctrl+Alt+V to finish (30 seconds maximum).')
                elif kind == 'transcribing':
                    self.set_status('Microphone off · transcribing locally…')
                elif kind == 'error':
                    self.set_status(text)
                elif kind == 'text':
                    self.deliver(text)
        if self.key:
            for event in self.key.poll():
                if event == 'press':
                    self.start()
                elif event == 'release':
                    self.stop()
                elif event == 'unavailable':
                    self.set_status('Ctrl+Alt+V is unavailable or already used. Hold the button in this panel instead.')
                elif event == 'tap':
                    self.set_status('The mouse binding sent a tap. Configure it to hold Ctrl+Alt+V while the button is held.')
        self.after = self.root.after(30, self.poll)

    def deliver(self, text):
        from .task_window import replace_text
        if not text:
            self.set_status('No speech recognized. Microphone off; hold the button longer and try again.'); return
        replace_text(self.transcript, text)
        view, selection, revision = self.target
        if (self.window.closed or self.window.view is not view or view.selection_key != selection
                or view.selection_revision != revision or not view.editor.winfo_exists()):
            self.set_status('The destination changed. Transcript kept here for copying; no draft changed.'); return
        current = view.editor.get('1.0', 'end-1c')
        addition = (' ' if current and not current[-1].isspace() else '') + text
        if len(current + addition) > MAX_MESSAGE:
            self.set_status('The draft is full. Transcript kept here for copying; existing text is unchanged.'); return
        view.editor.insert('end', addition)
        view.on_change()
        self.set_status('Voice text added to this chat draft. Review it, then Send. Microphone off.')

    def disable(self):
        if self.key:
            self.key.close(); self.key = None
        if self.dictation:
            self.dictation.close(); self.dictation = None
        self.enable_button.configure(state='normal')
        self.hold.configure(state='disabled')
        self.set_status('Voice disabled. Microphone off. Existing draft and last transcript are kept.')

    def close(self):
        if self.after:
            self.root.after_cancel(self.after)
        self.disable()
        self.manager._voice_dialog = None
        self.root.destroy()
