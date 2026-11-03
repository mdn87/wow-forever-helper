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
        super().__init__(window.view, 'Voice input · Keypad -')
        self.notice.set('Enable voice for this window, then hold Keypad - to record for this chat. '
                        'Speak when Recording appears; release to transcribe into the draft.')
        info = self.label(self.surface, 'Local Whisper · English · default microphone\n'
                          '30 seconds maximum · no audio saved · no spoken replies\n'
                          'Mic connection stays open while voice is enabled.\n'
                          'Only held speech is kept. Other apps are unaffected.')
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
        self.set_status('Connecting to microphone… other apps keep their own microphone settings.')

    def start(self):
        if not self.dictation or self.dictation.busy:
            return
        view = self.window.view
        if self.window.closed or not view or not view.editor.winfo_exists():
            self.disable(); return
        self.target = (view, view.selection_key, view.selection_revision)
        if self.dictation.start():
            self.set_status('Starting this recording… keep holding; speak when Recording appears.')

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
                if kind == 'ready' and not self.dictation.busy:
                    self.set_status('Mic connected · not recording. Hold Keypad - to record for this chat only.')
                elif kind == 'listening':
                    self.set_status('Recording for this chat · release Keypad - to finish (30 seconds maximum).')
                elif kind == 'transcribing':
                    self.set_status('Recording stopped · Whisper is transcribing locally. Mic remains connected.')
                elif kind in ('error', 'device_error'):
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
                    self.set_status('Keypad - is unavailable or already used. Hold the button in this panel instead.')
                elif event == 'tap':
                    self.set_status('Shortcut arrived as a tap; no held input detected. Hold Keypad - or the panel button to record.')
        self.after = self.root.after(30, self.poll)

    def deliver(self, text):
        from .task_window import replace_text
        if not text:
            self.set_status('No speech recognized. Mic remains connected; hold the button while speaking and try again.'); return
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
        self.set_status('Voice text added to this chat draft. Review it, then Send. Mic connected; not recording.')

    def disable(self):
        if self.key:
            self.key.close(); self.key = None
        if self.dictation:
            self.dictation.close(); self.dictation = None
        self.enable_button.configure(state='normal')
        self.hold.configure(state='disabled')
        self.set_status('Voice disabled; companion released its mic connection. Other apps are unaffected. Draft and transcript kept.')

    def close(self):
        if self.after:
            self.root.after_cancel(self.after)
        self.disable()
        self.manager._voice_dialog = None
        self.root.destroy()


class HandsFreeDialog(JournalDialog):
    """Binds one chat to Lugos Voice. Each spoken turn is sent there without draft review."""

    def __init__(self, manager, window, *, bridge_factory=None):
        from .voice_bridge import VoiceBridge
        self.manager, self.window = manager, window
        self.bridge = (bridge_factory or VoiceBridge)()
        self.target = None
        self.after = None
        super().__init__(window.view, 'Hands-free voice · Lugos Voice')
        self.notice.set('Connect this chat to send each finished Lugos Voice turn here directly, without draft review.')
        info = self.label(self.surface, 'Say the wake phrase, speak, then say "end turn".\n'
                          'Lugos Voice listens; this panel only accepts its finished turns.\n'
                          'Turns older than a minute, repeats and turns for another chat are refused.\n'
                          'Switching chats, closing this panel or the window disconnects.\n'
                          'Chat is conversation only; it never triggers game input.')
        info.configure(wraplength=390, justify='left'); info.pack(fill='x', padx=8, pady=8)
        self.bound = self.tk.StringVar(master=self.root, value='Not connected.')
        bound = self.label(self.surface, '')
        bound.configure(textvariable=self.bound); bound.pack(fill='x', padx=8, pady=(0, 6))
        self.connect_button = self.ttk.Button(self.surface, text='Connect this chat', command=self.connect)
        self.connect_button.pack(fill='x', padx=8)
        self.disconnect_button = self.ttk.Button(self.surface, text='Disconnect', command=self.disconnect, state='disabled')
        self.disconnect_button.pack(fill='x', padx=8, pady=6)
        self.label(self.surface, 'Last spoken turn').pack(anchor='w', padx=8, pady=(8, 0))
        self.transcript = self.text(self.surface)
        self.after = self.root.after(250, self.poll)
        self.show()

    def set_status(self, text):
        self.notice.set(text)
        if not self.window.closed:
            self.window.set_notice(text)

    def connect(self):
        view = self.window.view
        if self.bridge.connected or self.window.closed or not view:
            return
        session = view.selected
        if session is None:
            self.set_status('Choose an open session in this chat first.'); return
        self.target = (view, session.key, view.selection_revision)
        self.bridge.connect(session.title or 'Untitled chat', session.provider)
        self.bound.set(f'Connected to: {(session.title or "Untitled chat")[:60]} ({session.provider})')
        self.connect_button.configure(state='disabled')
        self.disconnect_button.configure(state='normal')
        self.set_status('Hands-free voice connected. Finished Lugos Voice turns send to this chat.')

    def disconnect(self, reason='Hands-free voice disconnected.'):
        was = self.bridge.connected
        self.bridge.disconnect()
        self.target = None
        self.bound.set('Not connected.')
        self.connect_button.configure(state='normal')
        self.disconnect_button.configure(state='disabled')
        if was:
            self.set_status(reason)

    def _target_changed(self):
        view, key, revision = self.target
        return (self.window.closed or self.window.view is not view or view.selection_key != key
                or view.selection_revision != revision or view.selected is None)

    def poll(self):
        self.after = None
        if self.bridge.connected:
            if self._target_changed():
                self.disconnect('The chat changed, so hands-free voice disconnected. Reconnect to choose this chat.')
            else:
                self.bridge.heartbeat()
                for request in self.bridge.pending():
                    self.deliver(request)
        self.after = self.root.after(250, self.poll)

    def deliver(self, request):
        from .task_window import replace_text
        request_id, text = request['id'], request['text']
        replace_text(self.transcript, text)
        view = self.target[0]

        def delivered(result, error):
            self.bridge.report(request_id, 'failed' if error else 'sent', error or result)

        if view.send_message(text, request_id=request_id, on_delivery=delivered):
            self.set_status('Spoken turn sent to this chat. Reply appears here as usual.')
        else:
            self.bridge.report(request_id, 'rejected', 'The chat is busy with another send.')
            self.set_status('A spoken turn arrived while this chat was busy. It was not sent; text kept in the panel.')

    def close(self):
        if self.after:
            self.root.after_cancel(self.after)
        self.disconnect()
        self.manager._handsfree_dialog = None
        self.root.destroy()
