"""Second-screen native chat. All provider work runs off the Tk event loop."""

from concurrent.futures import ThreadPoolExecutor
import queue
import uuid

from .chat import ChatError, ChatService, claude_connection_text
from .window_state import history_state, restored_history, saved_selection

BACKGROUND = "#101820"
PANEL = "#192630"
TEXT = "#e9f0f5"
MUTED = "#a4b4c1"
ACCENT = "#80d5bf"


class ChatWindow:
    """One independent conversation, usable in a window or a workspace panel."""

    def __init__(self, root, service=None, *, embedded=False, selection=None, on_change=None, state=None):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.root = tk, root
        self.service = service or ChatService()
        self.on_change = on_change or (lambda: None)
        state = state if isinstance(state, dict) else {}
        self.desired_key = tuple(selection) if selection else saved_selection(state.get("session"))
        self.session_title = state.get("title", "") if isinstance(state.get("title"), str) else ""
        self.inflight = None
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chat")
        self.results = queue.Queue()
        self.sessions = []
        self.selected = None
        self.busy = False
        self.closed = False
        self.last_messages = None
        self.drafts = {}
        self.sent = {}
        self.history_cache = {}
        self.observed = {}
        self.confirmed = {}
        self.auto_refresh = 0
        if self.desired_key:
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
        root.configure(bg=PANEL)
        if not embedded:
            root.title("WoW Forever Helper · Companion chat")
            root.geometry("760x650")
            root.minsize(420, 420)
            root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        style.configure("TCombobox", font=("Segoe UI", 10))

        selector = tk.Frame(root, bg=PANEL, padx=12, pady=10)
        selector.pack(fill="x")
        tk.Label(selector, text="AGENT SESSION", fg=MUTED, bg=PANEL,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 5))
        self.session_picker = ttk.Combobox(selector, state="readonly", width=1)
        self.session_picker.set("Choose an open session…")
        self.session_picker.pack(fill="x")
        self.session_picker.bind("<<ComboboxSelected>>", self.select)
        controls = tk.Frame(selector, bg=PANEL)
        controls.pack(fill="x", pady=(8, 0))
        self.refresh_button = ttk.Button(controls, text="Refresh sessions", command=self.refresh)
        self.refresh_button.pack(side="left")
        self.setup_button = ttk.Button(controls, text="Connect Claude…", command=self.claude_setup, state="disabled")
        self.setup_button.pack(side="left", padx=(8, 0))

        conversation = tk.Frame(root, bg=PANEL, padx=12)
        conversation.pack(fill="both", expand=True)
        self.title = tk.StringVar(master=root, value="Choose a session")
        self.subtitle = tk.StringVar(master=root, value="Each chat connects independently.")
        self.title_label = tk.Label(conversation, textvariable=self.title, anchor="w", fg=TEXT, bg=PANEL,
                                   font=("Segoe UI", 13, "bold"))
        self.title_label.pack(fill="x")
        self.subtitle_label = tk.Label(conversation, textvariable=self.subtitle, anchor="w", fg=ACCENT,
                                      bg=PANEL, font=("Segoe UI", 9))
        self.subtitle_label.pack(fill="x", pady=(2, 8))
        transcript_frame = tk.Frame(conversation, bg=PANEL)
        transcript_frame.pack(fill="both", expand=True)
        self.transcript = tk.Text(transcript_frame, wrap="word", state="disabled", bg=PANEL,
                                  fg=TEXT, font=("Segoe UI", 11), relief="flat", padx=6,
                                  pady=6, height=1, width=1, cursor="arrow", selectbackground="#385869")
        scrollbar = ttk.Scrollbar(transcript_frame, command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.transcript.pack(side="left", fill="both", expand=True)
        self.transcript.tag_configure("role", foreground=ACCENT, font=("Segoe UI", 10, "bold"), spacing1=14)
        self.transcript.tag_configure("body", spacing1=4, spacing3=12)
        self.transcript.tag_configure("note", foreground=MUTED, spacing1=8, spacing3=8)
        self.editor = tk.Text(conversation, height=3, width=1, wrap="word", bg="#233744", fg=TEXT,
                              insertbackground=TEXT, font=("Segoe UI", 11), padx=10, pady=8,
                              relief="flat", undo=True)
        self.editor.pack(fill="x", pady=(8, 6))
        self.editor.bind("<Control-Return>", self.send)
        self.editor.bind("<<Modified>>", self._edited)
        actions = tk.Frame(conversation, bg=PANEL)
        actions.pack(fill="x")
        tk.Label(actions, text="Ctrl+Enter to send", fg=MUTED, bg=PANEL,
                 font=("Segoe UI", 9)).pack(side="left")
        self.send_button = ttk.Button(actions, text="Send message", command=self.send, state="disabled")
        self.send_button.pack(side="right")
        self.status = tk.StringVar(master=root, value="Looking for open sessions…")
        if not embedded:
            root.report_callback_exception = lambda *_: self.status.set("The window could not finish that action. Refresh and try again.")
        self.status_label = tk.Label(root, textvariable=self.status, fg=MUTED, bg=PANEL, anchor="w",
                                    justify="left", wraplength=380, padx=12, pady=8, font=("Segoe UI", 9))
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

    def _edited(self, _event=None):
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            if self.selection_key:
                self.drafts[self.selection_key] = self.editor.get("1.0", "end-1c")
            self.on_change()

    def snapshot(self, remember=True):
        key = self.selection_key
        if not key:
            return {"draft": self.editor.get("1.0", "end-1c")[:32_000]} if remember else {}
        data = {"session": {"provider": key[0], "id": key[1]}, "title": self.session_title[:100]}
        if remember:
            pending = list(self.sent.get(key, []))
            if self.inflight and self.inflight[0] == key:
                _, body, ids = self.inflight
                pending.append((body, "delivery unconfirmed", ids))
            data.update(draft=self.editor.get("1.0", "end-1c")[:32_000],
                        messages=history_state(self.history_cache.get(key, [])),
                        pending=[{"body": body, "status": status, "previous_ids": sorted(ids)[-200:]}
                                 for body, status, ids in pending[-10:]])
        return data

    def _resize(self, event):
        if event.widget is self.root:
            self.status_label.configure(wraplength=max(200, event.width - 32))

    def _submit(self, kind, action, context=None):
        if self.busy or self.closed:
            return False
        self.busy = True
        self.send_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")

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
        self.setup_button.configure(state="normal" if session.provider == "claude" else "disabled")
        self._show(self.history_cache.get(session.key, []))
        self.send_button.configure(state="disabled" if self.busy else "normal")
        self.status.set("Loading conversation…")
        self.on_change()
        self._history()

    @staticmethod
    def _description(session):
        provider = "Codex" if session.provider == "codex" else "Claude Code"
        return f"{provider} · {session.project} · {session.status} · {session.id[:8]}"

    def _history(self):
        if self.selected:
            session = self.selected
            self._submit("history", lambda: self.service.history(session), session.key)

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
        was_bottom = self.transcript.yview()[1] >= 0.98
        position = self.transcript.yview()[0]
        self.last_messages = signature
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        if not messages and not pending:
            self.transcript.insert("end", "Your conversation appears here.\n\nChoose an open session above, then write a message below.", "note")
        for message in messages:
            self.transcript.insert("end", "YOU\n" if message.role == "user" else "AGENT\n", "role")
            self.transcript.insert("end", message.text + "\n", "body")
        for body, status, _previous_ids in pending:
            self.transcript.insert("end", "YOU · " + status.upper() + "\n", "role")
            self.transcript.insert("end", body + "\n", "body")
        self.transcript.configure(state="disabled")
        if was_bottom:
            self.transcript.see("end")
        else:
            self.transcript.yview_moveto(position)
        self.on_change()

    def send(self, _event=None):
        if not self.selected or self.busy:
            return "break"
        session = self.selected
        body = self.editor.get("1.0", "end-1c").strip()
        request_id = str(uuid.uuid4())
        if not body:
            return "break"
        previous_ids = frozenset(self.observed.get(session.key, set()))
        if self._submit("send", lambda: self.service.send(session, body, request_id), (session.key, body, previous_ids)):
            self.inflight = (session.key, body, previous_ids)
            self.status.set("Sending to the selected session…")
            self.on_change()
        return "break"

    def claude_setup(self):
        if not self.selected or self.selected.provider != "claude":
            return
        from tkinter import ttk
        dialog = self.tk.Toplevel(self.root)
        dialog.title("Connect this Claude session")
        dialog.transient(self.root.winfo_toplevel())
        dialog.attributes("-topmost", self.root.winfo_toplevel().attributes("-topmost"))
        dialog.geometry("700x420")
        self.tk.Label(dialog, text="Paste these instructions into the selected, already-open Claude session.",
                      padx=16, pady=16, wraplength=650).pack(anchor="w")
        content = claude_connection_text(self.selected)
        frame = self.tk.Frame(dialog)
        frame.pack(fill="both", expand=True, padx=16)
        text = self.tk.Text(frame, wrap="word", height=1, width=1,
                            font=("Segoe UI", 10), padx=16, pady=10)
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
        ttk.Button(dialog, text="Copy connection instructions", command=copy).pack(pady=16)

    def _tick(self):
        if self.closed:
            return
        self.root.after_cancel(self._after_id)
        try:
            kind, context, result, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.refresh_button.configure(state="normal")
            if kind == "send":
                self.inflight = None
            if error:
                self.status.set(error)
                if kind == "history":
                    self.subtitle.set("Saved history · conversation could not refresh")
            elif kind == "sessions":
                self.sessions, notices = result
                previous = self.selection_key
                labels = []
                for session in self.sessions:
                    title = session.title[:45].replace("\n", " ")
                    provider = "Codex" if session.provider == "codex" else "Claude Code"
                    labels.append(f"{provider} · {title} · {session.project[:20]} · {session.id[:8]}")
                self.session_picker.configure(values=labels)
                match = next((s for s in self.sessions if s.key == previous), None)
                self.status.set(" · ".join(notices) if notices else
                                (f"{len(self.sessions)} open sessions. Choose one above." if self.sessions else "No open sessions found. Open Codex or Claude Code, then refresh."))
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
                    self.setup_button.configure(state="disabled")
                    self.on_change()
                else:
                    self.session_picker.set("Choose an open session…")
            elif kind == "history" and self.selected and context == self.selected.key:
                self._show(result)
                self.subtitle.set(self._description(self.selected))
                if self.status.get() == "Loading conversation…":
                    self.status.set("Conversation updated. Approvals and tool activity remain in the terminal.")
            elif kind == "send":
                key, body, previous_ids = context
                self.sent.setdefault(key, []).append((body, result, previous_ids))
                if self.selected and self.selected.key == key:
                    if self.editor.get("1.0", "end-1c").strip() == body:
                        self.editor.delete("1.0", "end")
                        self.drafts[key] = ""
                    self.last_messages = None
                    self._show(self.history_cache.get(key, []))
                else:
                    self.drafts[key] = ""
                self.status.set("Message " + result + ". This does not yet confirm an agent reply.")
            self.send_button.configure(state="normal" if self.selected and not self.busy else "disabled")
            self.on_change()
        self.auto_refresh += 1
        if not self.busy and self.auto_refresh % 30 == 0:
            self._history()
        self._after_id = self.root.after(100, self._tick)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.root.after_cancel(self._after_id)
        # Close the proxy after in-flight work, never the agent it connects to.
        self.worker.submit(self.service.close)
        self.worker.shutdown(wait=False)
        self.root.destroy()


def launch():
    try:
        import tkinter as tk
        root = tk.Tk()
    except (ImportError, RuntimeError):
        raise ChatError("Chat needs Python with Tk and a graphical desktop.") from None
    except Exception:
        raise ChatError("The chat window could not open on this desktop.") from None
    try:
        from .workspace import WindowManager
        WindowManager(root)
        root.mainloop()
    except ChatError:
        root.destroy()
        raise
    except Exception:
        root.destroy()
        raise ChatError("The chat window could not run on this desktop.") from None
