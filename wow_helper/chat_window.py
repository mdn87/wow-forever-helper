"""Second-screen native chat. All provider work runs off the Tk event loop."""

from concurrent.futures import ThreadPoolExecutor
import queue
import uuid

from .chat import ChatError, ChatService, claude_connection_text

BACKGROUND = "#101820"
PANEL = "#192630"
TEXT = "#e9f0f5"
MUTED = "#a4b4c1"
ACCENT = "#80d5bf"


class ChatWindow:
    def __init__(self, root, service=None):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.root = tk, root
        self.service = service or ChatService()
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
        root.title("WoW Forever Helper · Companion chat")
        root.geometry("1080x760")
        root.minsize(760, 540)
        root.configure(bg=BACKGROUND)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 8))
        style.configure("Chat.Treeview", background=PANEL, foreground=TEXT,
                        fieldbackground=PANEL, rowheight=72, borderwidth=0, font=("Segoe UI", 10))
        style.map("Chat.Treeview", background=[("selected", "#304d59")])

        header = tk.Frame(root, bg=BACKGROUND, padx=24, pady=18)
        header.pack(fill="x")
        tk.Label(header, text="WOW FOREVER", fg=ACCENT, bg=BACKGROUND,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(header, text="Companion chat", fg=TEXT, bg=BACKGROUND,
                 font=("Segoe UI", 24, "bold")).pack(anchor="w")
        tk.Label(header, text="Talk to an agent session you already have open.",
                 fg=MUTED, bg=BACKGROUND, font=("Segoe UI", 11)).pack(anchor="w", pady=(4, 0))

        panes = tk.PanedWindow(root, orient="horizontal", bg=BACKGROUND,
                               sashwidth=10, bd=0, height=1)
        panes.pack(fill="both", expand=True, padx=20)
        sidebar = tk.Frame(panes, bg=PANEL, padx=12, pady=12)
        panes.add(sidebar, minsize=220, width=275)
        tk.Label(sidebar, text="OPEN SESSIONS", fg=MUTED, bg=PANEL,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 10))
        self.tree = ttk.Treeview(sidebar, show="tree", height=3, selectmode="browse", style="Chat.Treeview")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.select)
        self.refresh_button = ttk.Button(sidebar, text="Refresh sessions", command=self.refresh)
        self.refresh_button.pack(fill="x", pady=(12, 0))
        self.setup_button = ttk.Button(sidebar, text="Connect Claude…", command=self.claude_setup, state="disabled")
        self.setup_button.pack(fill="x", pady=(8, 0))

        conversation = tk.Frame(panes, bg=PANEL, padx=18, pady=12)
        panes.add(conversation, minsize=420)
        self.title = tk.StringVar(value="Choose a session")
        self.subtitle = tk.StringVar(value="Codex sends directly. Claude uses a polling connection.")
        tk.Label(conversation, textvariable=self.title, anchor="w", fg=TEXT, bg=PANEL,
                 font=("Segoe UI", 15, "bold")).pack(fill="x")
        tk.Label(conversation, textvariable=self.subtitle, anchor="w", fg=ACCENT, bg=PANEL,
                 font=("Segoe UI", 10)).pack(fill="x", pady=(4, 12))
        transcript_frame = tk.Frame(conversation, bg=PANEL)
        transcript_frame.pack(fill="both", expand=True)
        self.transcript = tk.Text(transcript_frame, wrap="word", state="disabled", bg=PANEL,
                                  fg=TEXT, font=("Segoe UI", 11), relief="flat", padx=8,
                                  pady=8, height=1, width=1, cursor="arrow", selectbackground="#385869")
        scrollbar = ttk.Scrollbar(transcript_frame, command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.transcript.pack(side="left", fill="both", expand=True)
        self.transcript.tag_configure("role", foreground=ACCENT, font=("Segoe UI", 10, "bold"), spacing1=14)
        self.transcript.tag_configure("body", spacing1=4, spacing3=12)
        self.transcript.tag_configure("note", foreground=MUTED, spacing1=8, spacing3=8)
        self.editor = tk.Text(conversation, height=4, wrap="word", bg="#233744", fg=TEXT,
                              insertbackground=TEXT, font=("Segoe UI", 11), padx=10, pady=10,
                              relief="flat", undo=True)
        self.editor.pack(fill="x", pady=(12, 8))
        self.editor.bind("<Control-Return>", self.send)
        actions = tk.Frame(conversation, bg=PANEL)
        actions.pack(fill="x")
        tk.Label(actions, text="Ctrl+Enter to send · Enter for a new line", fg=MUTED, bg=PANEL,
                 font=("Segoe UI", 9)).pack(side="left")
        self.send_button = ttk.Button(actions, text="Send message", command=self.send, state="disabled")
        self.send_button.pack(side="right")
        self.status = tk.StringVar(value="Looking for open sessions…")
        root.report_callback_exception = lambda *_: self.status.set("The window could not finish that action. Refresh and try again.")
        tk.Label(root, textvariable=self.status, fg=MUTED, bg=BACKGROUND, anchor="w",
                 wraplength=980, padx=24, pady=10, font=("Segoe UI", 10)).pack(fill="x")
        tk.Label(root, text="Messages use the selected agent's existing permissions. Approvals stay in its terminal. Chat never sends game keys.",
                 fg=MUTED, bg=BACKGROUND, padx=24, pady=4, font=("Segoe UI", 9)).pack(fill="x")
        self._show([])
        self._after_id = root.after(100, self._tick)
        self.refresh()

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
        selection = self.tree.selection()
        if not selection:
            return
        session = next((s for s in self.sessions if self._iid(s) == selection[0]), None)
        if session is None or session == self.selected:
            return
        if self.selected:
            self.drafts[self.selected.key] = self.editor.get("1.0", "end-1c")
        self.selected = session
        self.last_messages = None
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.drafts.get(session.key, ""))
        self.title.set(session.title[:65].replace("\n", " "))
        self.subtitle.set(self._description(session))
        self.setup_button.configure(state="normal" if session.provider == "claude" else "disabled")
        self._show([])
        self.send_button.configure(state="disabled" if self.busy else "normal")
        self.status.set("Loading conversation…")
        self._history()

    @staticmethod
    def _iid(session):
        return session.provider + ":" + session.id

    @staticmethod
    def _description(session):
        provider = "Codex" if session.provider == "codex" else "Claude Code"
        return f"{provider} · {session.project} · {session.status} · {session.id[:8]}"

    def _history(self):
        if self.selected:
            session = self.selected
            self._submit("history", lambda: self.service.history(session), session.key)

    def _show(self, messages):
        pending = self.sent.get(self.selected.key, []) if self.selected else []
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
            self.transcript.insert("end", "Your conversation appears here.\n\nChoose an open session on the left, then write a message below.", "note")
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
            self.status.set("Sending to the selected session…")
        return "break"

    def claude_setup(self):
        if not self.selected or self.selected.provider != "claude":
            return
        from tkinter import ttk
        dialog = self.tk.Toplevel(self.root)
        dialog.title("Connect this Claude session")
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
            if error:
                self.status.set(error)
            elif kind == "sessions":
                self.sessions, notices = result
                previous = self.selected.key if self.selected else None
                self.tree.delete(*self.tree.get_children())
                for session in self.sessions:
                    title = session.title[:30].replace("\n", " ")
                    provider = "Codex" if session.provider == "codex" else "Claude Code"
                    label = f"{title}\n{provider} · {session.project[:16]}\n{session.status} · {session.id[:8]}"
                    self.tree.insert("", "end", iid=self._iid(session), text=label)
                match = next((s for s in self.sessions if s.key == previous), None)
                if match:
                    self.selected = match
                    self.subtitle.set(self._description(match))
                    self.tree.selection_set(self._iid(match))
                elif self.selected:
                    self.drafts[self.selected.key] = self.editor.get("1.0", "end-1c")
                    self.selected = None
                    self.title.set("Session disconnected")
                    self.subtitle.set("Refresh after reopening the session.")
                    self.setup_button.configure(state="disabled")
                self.status.set(" · ".join(notices) if notices else
                                (f"{len(self.sessions)} open sessions. Select one to chat." if self.sessions else "No open sessions found. Open Codex or Claude Code, then refresh."))
            elif kind == "history" and self.selected and context == self.selected.key:
                self._show(result)
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
            self.send_button.configure(state="normal" if self.selected else "disabled")
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
        ChatWindow(root)
        root.mainloop()
    except Exception:
        root.destroy()
        raise ChatError("The chat window could not run on this desktop.") from None
