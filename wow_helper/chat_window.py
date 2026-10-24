"""Second-screen native chat. All provider work runs off the Tk event loop."""

from concurrent.futures import ThreadPoolExecutor
import queue
import uuid

from .chat import CHAT_STATE, ChatError, ChatService, MAX_MESSAGE, claude_connection_text
from .appearance import AppearanceDialog, append_turn, appearance_settings, style_text
from .window_state import history_state, restored_history, saved_selection
from .response_wait import ResponseWait, elapsed
from .activity_history import ActivityHistory
from .theme import palette, apply_theme, display_font, settings_icon, menu as themed_menu

BACKGROUND_JOBS = {"history", "guides"}


class ChatWindow:
    """One independent conversation, usable in a window or a workspace panel."""

    def __init__(self, root, service=None, *, embedded=False, selection=None, on_change=None,
                 state=None, toolbar=None, actions_menu=None, pin_advice=None):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.root = tk, root
        self.service = service or ChatService()
        self.activity_history = ActivityHistory(getattr(getattr(self, "activity", None), "storage",
                                                       getattr(self.service, "state", None)))
        self._activity_pending = {}
        self.on_change = on_change or (lambda: None)
        state = state if isinstance(state, dict) else {}
        self.default_provider = state.get("provider") if state.get("provider") in {"codex", "claude"} else "codex"
        self.pending_creation = state.get("launch") if isinstance(state.get("launch"), dict) else None
        self.selection_revision = 0
        self.appearance = appearance_settings(state.get("appearance"))
        self._appearance_dialog = None
        self._journal_dialog = None
        self._pin_dialog = None
        self.pin_advice = pin_advice
        self.reply_ranges = []
        self.selected_reply_id = None
        self.desired_key = tuple(selection) if selection else saved_selection(state.get("session"))
        if not self.desired_key and self.pending_creation:
            self.desired_key = saved_selection(self.pending_creation)
        self.session_title = state.get("title", "") if isinstance(state.get("title"), str) else ""
        self.inflight = None
        self.sending_wait = None
        self.response_waits = {}
        self._showing_wait = False
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chat")
        self.results = queue.Queue()
        self.sessions = []
        self.selected = None
        self.jobs = set()
        self.job_callbacks = {}
        self._send_callback = None
        self._clear_sent_draft = True
        self.closed = False
        self._scroll_after_id = None
        self.last_messages = None
        self.drafts = {}
        self.sent = {}
        self.history_cache = {}
        self.observed = {}
        self.confirmed = {}
        self.auto_refresh = 0
        self._history_cursor = 0
        if self.desired_key:
            waits = state.get("response_waits")
            if isinstance(waits, list):
                self.response_waits[self.desired_key] = [wait for raw in waits[-10:]
                                                       if (wait := ResponseWait.restore(raw))]
            self.history_cache[self.desired_key] = restored_history(state.get("messages"))
            draft = state.get("draft", "")
            self.drafts[self.desired_key] = draft[:32_000] if isinstance(draft, str) else ""
            pending = state.get("pending")
            if isinstance(pending, list):
                for item in pending[-10:]:
                    if not isinstance(item, dict) or not isinstance(item.get("body"), str):
                        continue
                    ids = item.get("previous_ids", [])
                    ids = frozenset(i[:200] for i in ids[:200] if isinstance(i, str)) if isinstance(ids, list) else frozenset()
                    status = item.get("status")
                    if status not in ("queued", "waiting for Claude to poll", "delivery unconfirmed"):
                        status = "delivery unconfirmed"
                    self.sent.setdefault(self.desired_key, []).append((item["body"][:6000], status, ids))
        root.configure(bg=palette(self.root).PANEL)
        if not embedded:
            root.title("WoW Forever Helper · Companion chat")
            root.geometry("760x650")
            root.minsize(420, 420)
            root.protocol("WM_DELETE_WINDOW", self.close)
        apply_theme(root)

        selector = self.selector = tk.Frame(toolbar if toolbar is not None else root, bg=palette(self.root).PANEL,
                            padx=0 if toolbar is not None else 8, pady=0 if toolbar is not None else 5)
        selector.pack(side="left" if toolbar is not None else "top", fill="x", expand=toolbar is not None)
        self.actions_menu = actions_menu if actions_menu is not None else themed_menu(selector)
        if actions_menu is None:
            self.menu_button = ttk.Menubutton(selector, text="Settings", image=settings_icon(root),
                                             style="Settings.TMenubutton", menu=self.actions_menu)
            self.menu_button.pack(side="right", padx=(4, 0))
            self.actions_menu.add_command(label="Chat appearance…", command=self.show_appearance)
            self.actions_menu.add_separator()
        else:
            self.actions_menu.add_separator()
        self.actions_menu.add_command(label="Connect selected Claude session…", command=self.claude_setup,
                                      state="disabled")
        self.setup_menu_index = self.actions_menu.index("end")
        self.refresh_button = ttk.Button(selector, text="↻", style="Window.TButton", command=self.refresh)
        self.refresh_button.pack(side="right", padx=(4, 0))
        self.provider_buttons = {}
        for provider, label in (("claude", "Claude +"), ("codex", "Codex +")):
            button = ttk.Button(selector, text=label, style="Agent.TButton",
                                command=lambda choice=provider: self.start_session(choice))
            button.pack(side="right", padx=(3, 0))
            self.provider_buttons[provider] = button
        self.actions_menu.add_command(label="Refresh open sessions", command=self.refresh)
        self.actions_menu.add_command(label="Save selected reply to Journal…", command=self.save_to_journal)
        self.actions_menu.add_command(label="Pin selected reply to Play…", command=self.pin_to_play)
        self.session_picker = ttk.Combobox(selector, state="readonly", width=1, font=("Segoe UI", 9))
        self.session_picker.set("Choose an open session…")
        self.session_picker.pack(side="left", fill="x", expand=True)
        self.session_picker.bind("<<ComboboxSelected>>", self.select)

        conversation = tk.Frame(root, bg=palette(self.root).PANEL, padx=8)
        conversation.pack(fill="both", expand=True)
        self.title = tk.StringVar(master=root, value="Choose a session")
        self.subtitle = tk.StringVar(master=root, value="Each chat connects independently.")
        self.title_label = tk.Label(conversation, textvariable=self.title, anchor="w", fg=palette(self.root).TEXT, bg=palette(self.root).PANEL,
                                   font=display_font(root, 15))
        if not embedded:
            self.title_label.pack(fill="x")
        self.subtitle_label = tk.Label(conversation, textvariable=self.subtitle, anchor="w", fg=palette(self.root).ACCENT,
                                      bg=palette(self.root).PANEL, font=("Segoe UI", 8))
        self.subtitle_label.pack(fill="x", pady=(0, 3))
        transcript_frame = tk.Frame(conversation, bg=palette(self.root).PANEL)
        transcript_frame.pack(fill="both", expand=True)
        self.transcript = tk.Text(transcript_frame, wrap="word", state="disabled", bg=palette(self.root).PANEL,
                                  fg=palette(self.root).TEXT, font=("Segoe UI", 11), relief="flat", padx=6,
                                  pady=3, height=1, width=1, cursor="arrow", selectbackground="#554228")
        scrollbar = ttk.Scrollbar(transcript_frame, command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.transcript.pack(side="left", fill="both", expand=True)
        self.transcript.bind("<Configure>", self._queue_scroll_to_bottom)
        self.transcript.bind("<Map>", self._queue_scroll_to_bottom)
        self.transcript.bind("<Control-j>", lambda _: self.save_to_journal())
        self.transcript.bind("<Control-p>", lambda _: self.pin_to_play())
        composer = tk.Frame(conversation, bg=palette(self.root).PANEL)
        composer.pack(fill="x", pady=(5, 0))
        self.send_button = ttk.Button(composer, text="Send ↵", style="Primary.TButton", command=self.send, state="disabled")
        self.send_button.pack(side="right", anchor="s", padx=(6, 0))
        self.editor = tk.Text(composer, height=2, width=1, wrap="word", bg=palette(self.root).EDITOR, fg=palette(self.root).TEXT,
                              insertbackground=palette(self.root).TEXT, font=("Segoe UI", 11), padx=8, pady=6,
                              relief="solid", borderwidth=1, undo=True)
        self.editor.pack(side="left", fill="both", expand=True)
        for key in ("Return", "KP_Enter"):
            self.editor.bind(f"<{key}>", self.send)
            self.editor.bind(f"<Control-{key}>", self.send)
            self.editor.bind(f"<Shift-{key}>", self.insert_newline)
        self.editor.bind("<<Modified>>", self._edited)
        style_text(self.transcript, self.appearance)
        style_text(self.editor, self.appearance, composer=True)
        self.status = tk.StringVar(master=root, value="Looking for open sessions…")
        if not embedded:
            root.report_callback_exception = lambda *_: self.status.set("The window could not finish that action. Refresh and try again.")
        self.status_label = tk.Label(root, textvariable=self.status, fg=palette(self.root).MUTED, bg=palette(self.root).PANEL, anchor="w",
                                    justify="left", wraplength=380, padx=8, pady=4, font=("Segoe UI", 8))
        self.status_label.pack(fill="x")
        root.bind("<Configure>", self._resize, add="+")
        self._show(self.history_cache.get(self.desired_key, []))
        if self.desired_key:
            self.title.set(self.session_title or "Saved session")
            self.subtitle.set("Saved history · checking whether this session is available")
            self.editor.insert("1.0", self.drafts.get(self.desired_key, ""))
        elif isinstance(state.get("draft"), str):
            self.editor.insert("1.0", state["draft"][:32_000])
        self._after_id = root.after(100, self._tick)
        self.refresh()

    @property
    def selection_key(self):
        return self.selected.key if self.selected else self.desired_key

    @property
    def busy(self):
        return bool(self.jobs)

    def _update_controls(self):
        foreground = bool(self.jobs - BACKGROUND_JOBS)
        can_start = not self.desired_key and hasattr(self.service, "create")
        self.send_button.configure(state="normal" if (self.selected or can_start) and not foreground else "disabled")
        self.refresh_button.configure(state="disabled" if foreground else "normal")
        for button in self.provider_buttons.values():
            button.configure(state="disabled" if foreground or not hasattr(self.service, "create") else "normal")
        self.actions_menu.entryconfigure(self.setup_menu_index,
                                         state="normal" if self.selected and self.selected.provider == "claude" and not self.selected.managed else "disabled")

    def _edited(self, _event=None):
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            if self.selection_key:
                self.drafts[self.selection_key] = self.editor.get("1.0", "end-1c")
            self.on_change()

    def snapshot(self, remember=True):
        key = self.selection_key
        data = {"appearance": dict(self.appearance), "provider": self.default_provider}
        if self.pending_creation:
            data["launch"] = self.pending_creation
        if not key:
            if remember:
                data["draft"] = self.editor.get("1.0", "end-1c")[:32_000]
            return data
        data.update(session={"provider": key[0], "id": key[1]}, title=self.session_title[:100])
        if remember:
            pending = list(self.sent.get(key, []))
            if self.inflight and self.inflight[0] == key:
                _, body, ids = self.inflight
                pending.append((body, "delivery unconfirmed", ids))
            data.update(draft=self.editor.get("1.0", "end-1c")[:32_000],
                        messages=history_state(self.history_cache.get(key, [])),
                        response_waits=[wait.snapshot() for wait in self.response_waits.get(key, [])[-10:]],
                        pending=[{"body": body, "status": status, "previous_ids": sorted(ids)[-200:]}
                                 for body, status, ids in pending[-10:]])
        return data

    def show_appearance(self):
        if self._appearance_dialog is None:
            self._appearance_dialog = AppearanceDialog(self)
        else:
            self._appearance_dialog.root.deiconify()
            self._appearance_dialog.root.lift()

    def set_appearance(self, settings):
        self.appearance = appearance_settings(settings)
        style_text(self.transcript, self.appearance)
        style_text(self.editor, self.appearance, composer=True)
        self._queue_scroll_to_bottom()
        self.on_change()

    def insert_newline(self, _event=None):
        if self.editor.tag_ranges("sel"):
            self.editor.delete("sel.first", "sel.last")
        self.editor.insert("insert", "\n")
        self.editor.see("insert")
        return "break"

    def _resize(self, event):
        if event.widget is self.root:
            self.status_label.configure(wraplength=max(200, event.width - 32))

    def _submit(self, kind, action, context=None, *, on_result=None):
        # Allow one explicit action behind a background poll. All provider work
        # remains serialized, with no duplicate sends or overlapping socket reads.
        if self.closed or kind in self.jobs or self.jobs - BACKGROUND_JOBS or (kind in BACKGROUND_JOBS and self.busy):
            return False
        self.jobs.add(kind)
        if on_result is not None:
            self.job_callbacks[kind] = on_result
        self._update_controls()

        def work():
            try:
                self.results.put((kind, context, action(), None))
            except ChatError as error:
                self.results.put((kind, context, None, str(error)))
            except Exception:
                self.results.put((kind, context, None, "Local chat data is unavailable. Check the terminal and refresh."))
        self.worker.submit(work)
        return True

    def refresh(self):
        if self._submit("sessions", self.service.discover):
            self.status.set("Refreshing open sessions…")

    def select(self, _event=None):
        index = self.session_picker.current()
        if 0 <= index < len(self.sessions):
            self._select_session(self.sessions[index])

    def _select_session(self, session):
        if self.selected and session.key == self.selected.key:
            self.selected = session
            self.subtitle.set(self._description(session))
            return
        self.selection_revision += 1
        if self.selection_key:
            self.drafts[self.selection_key] = self.editor.get("1.0", "end-1c")
        elif session.key not in self.drafts:
            self.drafts[session.key] = self.editor.get("1.0", "end-1c")
        self.selected = session
        self.desired_key = session.key
        self.session_title = session.title
        self.last_messages = None
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.drafts.get(session.key, ""))
        self.title.set(session.title[:65].replace("\n", " "))
        self.subtitle.set("Saved history · refreshing conversation" if self.history_cache.get(session.key)
                          else self._description(session))
        self._show(self.history_cache.get(session.key, []))
        self._update_controls()
        self.status.set("Loading conversation…")
        self.on_change()
        self._history()

    def create_session(self, provider, creation_id):
        return self.service.create(provider, creation_id=creation_id), None

    def session_started(self, preparation):
        """Task windows use this to display reports loaded during startup."""

    def start_session(self, provider=None, *, on_ready=None):
        if not hasattr(self.service, "create") or self.jobs - BACKGROUND_JOBS:
            return False
        provider = provider or self.default_provider
        key, revision = str(uuid.uuid4()), self.selection_revision
        def done(result, error):
            self.pending_creation = None
            if error:
                self.status.set(error)
            else:
                session, preparation = result
                self.sessions.append(session)
                self._session_labels()
                if revision != self.selection_revision:
                    self.status.set("The new conversation is available in the list. Selection changed, so nothing was sent.")
                    return
                self.session_picker.current(self.sessions.index(session))
                self._select_session(session)
                self.session_started(preparation)
                self.status.set("New " + ("Codex" if provider == "codex" else "Claude") + " conversation. The first request starts its CLI.")
                if on_ready:
                    on_ready()
            self.on_change()
        if self._submit("start", lambda: self.create_session(provider, key), on_result=done):
            self.default_provider = provider
            self.pending_creation = {"provider": provider, "id": key}
            self.status.set("Preparing a new " + ("Codex" if provider == "codex" else "Claude") + " conversation…")
            self.on_change()
            return True
        return False

    def _session_labels(self):
        self.session_picker.configure(values=[
            f"{'Codex' if s.provider == 'codex' else 'Claude'} · {s.title[:45].replace(chr(10), ' ')} · {s.project[:20]} · {s.id[:8]}"
            for s in self.sessions])

    @staticmethod
    def _description(session):
        provider = "Codex" if session.provider == "codex" else "Claude Code"
        return f"{provider} · {session.project} · {session.status} · {session.id[:8]}"

    def _history(self, *, pending=False):
        session = self.selected
        if pending:
            candidates = [s for s in self.sessions if self.response_waits.get(s.key)
                          and (not session or s.key != session.key)]
            if session:
                candidates.insert(0, session)
            if candidates:
                session = candidates[self._history_cursor % len(candidates)]
                self._history_cursor += 1
        if session:
            waits = list(self.response_waits.get(session.key, []))
            def read():
                statuses = {wait.request_id: self.service.response_status(session, wait.request_id)
                            for wait in waits} if hasattr(self.service, "response_status") else {}
                return self.service.history(session), statuses
            self._submit("history", read, session.key)

    def _record_activity(self, key, wait, outcome):
        source = {"type": "chat", "provider": key[0], "session_id": key[1], "request_id": wait.request_id}
        title = next((s.title for s in self.sessions if s.key == key), "Saved conversation")
        self._activity_pending[wait.request_id] = (source, outcome, title, wait.started)
        self._flush_activity()
        return wait.request_id not in self._activity_pending

    def _flush_activity(self):
        for request, args in list(self._activity_pending.items()):
            try:
                self.activity_history.record(*args)
            except ChatError as error:
                self.status.set(str(error))
                break
            else:
                self._activity_pending.pop(request, None)

    def _observe_responses(self, key, messages, statuses):
        waits = self.response_waits.get(key, [])
        claimed = {wait.user_id for wait in waits if wait.user_id}
        remaining = []
        changed = False
        for wait in waits:
            before = wait.user_id, wait.previous_ids
            finished = wait.observe(messages, statuses.get(wait.request_id), claimed)
            if wait.user_id:
                claimed.add(wait.user_id)
            changed |= before != (wait.user_id, wait.previous_ids) or bool(finished)
            if finished:
                if not self._record_activity(key, wait, finished):
                    remaining.append(wait)
                    continue
                if key == self.selection_key:
                    label = {"completed": "Response complete", "received": "Response received",
                             "acknowledged": "Response acknowledged",
                             "failed": "Response failed", "cancelled": "Response cancelled",
                             "interrupted": "Response interrupted"}[finished]
                    self.status.set(f"{label} · {elapsed(wait.started)}")
            else:
                remaining.append(wait)
        self.response_waits[key] = remaining
        if changed:
            self.on_change()

    def _update_response_timer(self):
        waits = self.response_waits.get(self.selection_key, [])
        if waits:
            text = "Waiting for response · " + elapsed(waits[0].started)
            if len(waits) > 1:
                text += f" · {len(waits)} requests"
            if not self.selected:
                text += " · session unavailable"
            if self.subtitle.get() != text:
                self.subtitle.set(text)
            self._showing_wait = True
        elif self._showing_wait:
            self._showing_wait = False
            if self.selected:
                self.subtitle.set(self._description(self.selected))

    def _show(self, messages):
        pending = self.sent.get(self.selection_key, [])
        if self.selected:
            key = self.selected.key
            confirmed = self.confirmed.setdefault(key, set())
            remaining = []
            for body, status, previous_ids in pending:
                match = next((message for message in messages if message.role == "user"
                              and message.text.strip() == body and message.id not in previous_ids
                              and message.id not in confirmed), None)
                if match:
                    confirmed.add(match.id)
                else:
                    remaining.append((body, status, previous_ids))
            pending = self.sent[key] = remaining
            self.history_cache[key] = messages
            self.observed.setdefault(key, set()).update(message.id for message in messages)
        signature = (messages, tuple(pending))
        if signature == self.last_messages:
            return
        self.last_messages = signature
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        if not messages and not pending:
            self.transcript.insert("end", "Your conversation appears here.\n\nChoose an existing session, or use Codex + / Claude +. "
                                   "Sending with no session selected starts a new " + self.default_provider.title() + " conversation.", "note")
        self.reply_ranges = []
        for message in messages:
            append_turn(self.transcript, message.text, message.role)
            if message.role == "assistant":
                end = self.transcript.index("end-1c")
                start = self.transcript.index(f"{end}-{len(message.text.strip(chr(10)))}c")
                self.reply_ranges.append((start, end, message))
                tag = "reply-" + str(len(self.reply_ranges))
                self.transcript.tag_add(tag, start, end)
                self.transcript.tag_bind(tag, "<ButtonRelease-1>",
                                         lambda _, key=message.id: setattr(self, "selected_reply_id", key))
        for body, status, _previous_ids in pending:
            append_turn(self.transcript, body, "user", pending=status)
        self.transcript.configure(state="disabled")
        self._queue_scroll_to_bottom()
        self.on_change()

    def selected_advice(self):
        from .journal import advice_selection
        ranges = self.transcript.tag_ranges("sel")
        selection = None
        if ranges:
            for start, end, message in self.reply_ranges:
                if self.transcript.compare(ranges[0], ">=", start) and self.transcript.compare(ranges[1], "<=", end):
                    selection = message, self.transcript.get(*ranges)
                    break
            if selection is None:
                self.status.set("Select text within a single assistant reply.")
                return None
        elif self.reply_ranges:
            message = next((m for _, _, m in self.reply_ranges if m.id == self.selected_reply_id), self.reply_ranges[-1][2])
            selection = message, message.text
        if selection is None:
            self.status.set("There is no assistant reply to save yet.")
            return None
        return advice_selection(self, *selection)

    def pin_to_play(self):
        if self._pin_dialog is not None:
            self._pin_dialog.root.lift()
            return
        if self.pin_advice is None:
            self.status.set("Open this chat in the companion workspace to pin advice.")
            return
        from .pinned_advice import PinAdviceDialog
        try:
            selection = self.selected_advice()
            if selection:
                self._pin_dialog = PinAdviceDialog(self, selection)
        except ChatError as error:
            self.status.set(str(error))

    def save_to_journal(self):
        if self._journal_dialog is not None:
            self._journal_dialog.root.lift()
            return
        from .journal_ui import SaveAdviceDialog
        from .activities import ActivityService
        if not hasattr(self, "activity"):
            self.activity = ActivityService(getattr(self.service, "state", None) or CHAT_STATE)
        try:
            selection = self.selected_advice()
            if selection:
                self._journal_dialog = SaveAdviceDialog(self, selection)
        except ChatError as error:
            self.status.set(str(error))

    def _queue_scroll_to_bottom(self, _event=None):
        # Wait for wrapping and geometry to settle, including initial mapping
        # and resizing. Unchanged history returns before requesting a scroll.
        if not self.closed and self._scroll_after_id is None:
            self._scroll_after_id = self.root.after_idle(self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        self._scroll_after_id = None
        if not self.closed:
            self.transcript.yview_moveto(1.0)

    def send(self, _event=None):
        self.send_message(self.editor.get("1.0", "end-1c").strip(), clear_draft=True)
        return "break"

    def send_message(self, body, *, request_id=None, on_delivery=None, clear_draft=False):
        """Send an explicit prepared request without replacing an unsent draft."""
        if self.jobs - BACKGROUND_JOBS:
            return False
        if not body.strip():
            return False
        if len(body) > MAX_MESSAGE or "\0" in body:
            self.status.set(f"Keep messages under {MAX_MESSAGE:,} characters, without null characters.")
            return False
        if not self.selected:
            if body.strip() and not self.desired_key:
                return self.start_session(on_ready=lambda: self.send_message(
                    body, request_id=request_id, on_delivery=on_delivery, clear_draft=clear_draft))
            return False
        session = self.selected
        request_id = request_id or str(uuid.uuid4())
        if not body:
            return False
        previous_ids = frozenset(self.observed.get(session.key, set()))
        if self._submit("send", lambda: self.service.send(session, body, request_id), (session.key, body, previous_ids)):
            self.inflight = (session.key, body, previous_ids)
            self.sending_wait = ResponseWait(request_id, body, previous_ids=previous_ids)
            self.response_waits.setdefault(session.key, []).append(self.sending_wait)
            self._update_response_timer()
            self._send_callback = on_delivery
            self._clear_sent_draft = clear_draft
            self.status.set("Sending to the selected session…")
            self.on_change()
            return True
        return False

    def claude_setup(self):
        if not self.selected or self.selected.provider != "claude":
            return
        from tkinter import ttk
        from .window_frame import WindowFrame
        dialog = self.tk.Toplevel(self.root)
        dialog.title("Connect this Claude session")
        dialog.transient(self.root.winfo_toplevel())
        dialog.attributes("-topmost", self.root.winfo_toplevel().attributes("-topmost"))
        dialog.geometry("700x460")
        dialog._companion_frame = WindowFrame(dialog, title="Connect this Claude session", minimum=(500, 400))
        surface = dialog._companion_frame.content
        self.tk.Label(surface, text="Paste these instructions into the selected, already-open Claude session.",
                      bg=palette(self.root).BACKGROUND, fg=palette(self.root).TEXT, padx=16, pady=16, wraplength=650).pack(anchor="w")
        content = claude_connection_text(self.selected)
        frame = self.tk.Frame(surface, bg=palette(self.root).BACKGROUND)
        frame.pack(fill="both", expand=True, padx=16)
        text = self.tk.Text(frame, wrap="word", height=1, width=1,
                            bg=palette(self.root).PANEL, fg=palette(self.root).TEXT, font=("Segoe UI", 10), padx=16, pady=10)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.insert("1.0", content)
        text.configure(state="disabled")

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.status.set("Connection instructions copied. Paste them into the selected Claude session.")
        ttk.Button(surface, text="Copy connection instructions", command=copy).pack(pady=16)
        dialog._companion_frame.apply_native()

    def _tick(self):
        if self.closed:
            return
        self.root.after_cancel(self._after_id)
        try:
            kind, context, result, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.jobs.discard(kind)
            if kind == "send":
                context = self.inflight or context
                self.inflight = None
                if error and self.sending_wait:
                    self._record_activity(context[0], self.sending_wait, "failed")
                    waits = self.response_waits.get(context[0], [])
                    if self.sending_wait in waits:
                        waits.remove(self.sending_wait)
                self.sending_wait = None
            if kind == "history" and not error and self.inflight and context == self.inflight[0]:
                # This read completed before the queued send started. Its user
                # messages cannot be receipts for that new outgoing message.
                key, body, previous_ids = self.inflight
                ids = previous_ids | frozenset(m.id for m in result[0])
                self.inflight = (key, body, ids)
                if self.sending_wait:
                    self.sending_wait.previous_ids = ids
            callback = self.job_callbacks.pop(kind, None)
            if callback:
                callback(result, error)
            elif error:
                if kind == "history":
                    if self.selected and context == self.selected.key:
                        self.subtitle.set("Saved history · conversation could not refresh")
                        if not self.jobs:
                            self.status.set(error)
                else:
                    self.status.set(error)
            elif kind == "sessions":
                self.sessions, notices = result
                previous = self.selection_key
                self._session_labels()
                match = next((s for s in self.sessions if s.key == previous), None)
                self.status.set(" · ".join(notices) if notices else
                                (f"{len(self.sessions)} sessions. Choose one or start a new conversation." if self.sessions else "Send a message to start a new conversation, or choose Codex + / Claude +."))
                if match:
                    self.session_picker.current(self.sessions.index(match))
                    self._select_session(match)
                elif previous:
                    if self.selected:
                        self.drafts[self.selected.key] = self.editor.get("1.0", "end-1c")
                    self.selected = None
                    self.session_picker.set("Saved session unavailable — choose another or refresh")
                    self.title.set(self.session_title or "Session disconnected")
                    self.subtitle.set("Saved history · session unavailable · sending disabled")
                    self.on_change()
                else:
                    self.session_picker.set("Choose an open session…")
            elif kind == "history":
                messages, statuses = result
                self._observe_responses(context, messages, statuses)
                if self.selected and context == self.selected.key:
                    self._show(messages)
                    self.subtitle.set(self._description(self.selected))
                    if self.status.get() == "Loading conversation…":
                        self.status.set("Enter sends · Shift+Enter adds a line · Approvals stay in the terminal.")
            elif kind == "send":
                key, body, previous_ids = context
                self.sent.setdefault(key, []).append((body, result, previous_ids))
                if self.selected and self.selected.key == key:
                    if self._clear_sent_draft and self.editor.get("1.0", "end-1c").strip() == body:
                        self.editor.delete("1.0", "end")
                        self.drafts[key] = ""
                    self.last_messages = None
                    self._show(self.history_cache.get(key, []))
                elif self._clear_sent_draft and self.drafts.get(key, "").strip() == body:
                    self.drafts[key] = ""
                self.status.set("Message " + result + ". This does not yet confirm an agent reply.")
            if kind == "send" and self._send_callback:
                delivered, self._send_callback = self._send_callback, None
                delivered(result, error)
            self._update_controls()
            if kind not in BACKGROUND_JOBS:
                self.on_change()
        self.auto_refresh += 1
        if not self.busy and self.auto_refresh % 30 == 0:
            self._flush_activity()
            self._history(pending=True)
        self.on_tick()
        self._update_response_timer()
        self._after_id = self.root.after(100, self._tick)

    def on_tick(self):
        """Additional local panels may poll lightweight work without blocking Tk."""

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.job_callbacks.clear()
        self._send_callback = None
        if self._appearance_dialog is not None:
            self._appearance_dialog.close()
        if self._pin_dialog is not None:
            self._pin_dialog.close()
        if self._journal_dialog is not None:
            self._journal_dialog.close()
        self.root.after_cancel(self._after_id)
        if self._scroll_after_id is not None:
            self.root.after_cancel(self._scroll_after_id)
            self._scroll_after_id = None
        # Close the proxy after in-flight work, never the agent it connects to.
        self.worker.submit(self.service.close)
        self.worker.shutdown(wait=False)
        self.selector.destroy()
        self.root.destroy()


def launch(*, hotkey="H", restart=False):
    from .window_access import WindowAccess, restart_existing, signal_existing
    from .workspace import LAYOUT_PATH, WindowManager

    if restart:
        restart_existing(LAYOUT_PATH)
    elif signal_existing(LAYOUT_PATH):
        return
    try:
        import tkinter as tk
        root = tk.Tk()
    except (ImportError, RuntimeError):
        raise ChatError("Chat needs Python with Tk and a graphical desktop.") from None
    except Exception:
        raise ChatError("The chat window could not open on this desktop.") from None
    manager = access = None
    try:
        manager = WindowManager(root)
        access = WindowAccess(LAYOUT_PATH, hotkey=hotkey)
        manager.enable_reopening(access)
        root.mainloop()
    except ChatError:
        root.destroy()
        # Another launch may have acquired the layout while this one opened Tk.
        if manager is None and signal_existing(LAYOUT_PATH):
            return
        raise
    except Exception:
        root.destroy()
        raise ChatError("The chat window could not run on this desktop.") from None
    finally:
        if access:
            access.close()
