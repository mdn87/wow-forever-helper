"""Companion reports, local journals, image previews, and explicit agent setup."""

from datetime import datetime
from collections import deque
from pathlib import Path
import re
import uuid

from .activities import FLAVORS, SKILLS, STEPS, TYPES, ActivityService, packet_preview, profile_settings
from .appearance import style_text
from .chat import ChatError, ChatService, read_json, write_json
from .chat_window import ChatWindow, BACKGROUND_JOBS
from .guidance import guidance, quest_tier
from .theme import ACCENT, BACKGROUND, EDGE, MUTED, PANEL, TEXT
from .quest_chat import MAX_QUEST_CHATS, OPENING, QuestChat, quest_context, quest_identity
from .window_frame import WindowFrame


def text_box(tk, parent, **options):
    from tkinter import ttk
    frame = tk.Frame(parent, bg=PANEL)
    frame.pack(fill="both", expand=True)
    text = tk.Text(frame, wrap="word", width=1, height=1, relief="flat", padx=8, pady=5, **options)
    scroll = ttk.Scrollbar(frame, command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    return text


def replace_text(widget, body):
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", body)
    widget.configure(state="disabled")


class TaskWindow(ChatWindow):
    def __init__(self, root, service, *, kind="chat", activity=None, window_id=None,
                 service_factory=ChatService, **kwargs):
        import tkinter as tk
        from tkinter import ttk
        state = kwargs.get("state")
        state = state if isinstance(state, dict) else {}
        self.kind = kind
        self.activity = activity or ActivityService()
        self.profile = profile_settings(kind, state.get("profile"))
        raw = state.get("activity")
        raw = raw if isinstance(raw, dict) else {}
        self.journal_id = str(uuid.UUID(raw.get("journal_id", window_id))) if self._valid_id(raw.get("journal_id", window_id)) else str(uuid.uuid4())
        self.image_name = raw.get("image") if isinstance(raw.get("image"), str) else None
        self.last_setup = raw.get("last_setup") if isinstance(raw.get("last_setup"), str) else ""
        pending = raw.get("pending_note")
        self.pending_note = (pending if isinstance(pending, dict) and self._valid_id(pending.get("id"))
                             and isinstance(pending.get("body"), str) and isinstance(pending.get("name"), str) else None)
        self._setup_dialog = self._request_dialog = None
        self._preview_image = None
        self._source_image = None
        self._image_after = None
        self.buttons = []
        self.quest_chats = {}
        self.service_factory = service_factory
        self.shared_toolbar = kwargs.get("toolbar")
        self._saved_quest_chats = {}
        self.panel_report = {}
        self._panel_base = ""
        self._view_ready = False
        self._fresh_refresh = "activity" not in state and self.profile["refresh_on_open"] and kind in {"quests", "character"}
        self._guide_queue = deque()
        self._guidance = guidance(self.activity.storage)
        self.guide_keys = {k: v for k, v in raw.get("guide_keys", {}).items()
                           if isinstance(k, str) and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)} if isinstance(raw.get("guide_keys"), dict) else {}
        self.gear_key = raw.get("gear_key") if isinstance(raw.get("gear_key"), str) and re.fullmatch(r"[0-9a-f]{64}", raw["gear_key"]) else None
        self._gear_guide = None
        self._report_generation = 0
        self.book = None
        self.outer = root
        self.activity_notice = tk.StringVar(master=root, value=self.last_setup)
        self.journal_name = tk.StringVar(master=root, value="My journal")
        chat_root = root
        if kind != "chat":
            self.book = ttk.Notebook(root)
            self.book.pack(fill="both", expand=True)
            self.panel = tk.Frame(self.book, bg=PANEL)
            chat_root = tk.Frame(self.book, bg=PANEL)
            self.book.add(self.panel, text=TYPES[kind][0])
            self.book.add(chat_root, text="Chat")
        super().__init__(chat_root, service, **kwargs)
        self.actions_menu.add_separator()
        self.actions_menu.add_command(label="Window setup…", command=self.show_setup)
        self.actions_menu.add_command(label="Prepare opening request…", command=self.prepare_request)
        self.actions_menu.add_command(label="Save window preset…", command=self.save_preset)
        self.actions_menu.add_command(label="Load window preset…", command=self.load_preset)
        if self.book is not None:
            self._build_panel(raw)
            if kind == "quests":
                self._restore_quest_chats(raw.get("quest_chats"))
            index = raw.get("tab", 0)
            self.book.select(index if type(index) is int and 0 <= index < len(self.book.tabs()) else 0)
            self.book.bind("<<NotebookTabChanged>>", self._tab_changed)
            self.book.bind("<Configure>", lambda _: self._quest_tab_labels(), add="+")
        self._view_ready = True
        self._tab_changed()

    @staticmethod
    def _valid_id(raw):
        try:
            uuid.UUID(raw)
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    def _button(self, parent, label, command):
        from tkinter import ttk
        button = ttk.Button(parent, text=label, command=command)
        button.pack(side="left", padx=(0, 4))
        self.buttons.append(button)
        return button

    def _build_panel(self, raw):
        from tkinter import ttk
        tk = self.tk
        actions = tk.Frame(self.panel, bg=PANEL, padx=8, pady=5)
        actions.pack(fill="x")
        if self.kind == "screen":
            self.capture_button = self._button(actions, "Capture WoW", self.capture)
            self.import_button = self._button(actions, "Open image", self.open_image)
            self.paste_button = self._button(actions, "Paste", self.paste_image)
        else:
            self.report_button = self._button(actions, "Refresh", self.refresh_panel)
        if self.kind == "character":
            self.gear_button = self._button(actions, "Find better gear", self.find_gear)
        if self.kind == "quests":
            self.quest_chat_button = self._button(actions, "Quest chat", self.open_quest_chat)
        self.ask_button = self._button(actions, "Ask agent", lambda: self.prepare_request(review=False))
        self.setup_button = self._button(actions, "Setup", self.show_setup)
        footer = tk.Label(self.panel, textvariable=self.activity_notice, bg=PANEL, fg=ACCENT,
                          anchor="w", justify="left", wraplength=370, padx=8, pady=5, font=("Segoe UI", 9))
        footer.pack(side="bottom", fill="x")
        self.panel.bind("<Configure>", lambda e: footer.configure(wraplength=max(220, e.width - 24)), add="+")
        if self.kind == "journal":
            choices = tk.Frame(self.panel, bg=PANEL, padx=8, pady=3)
            choices.pack(fill="x")
            name = ttk.Entry(choices, textvariable=self.journal_name, width=12)
            name.pack(side="left", fill="x", expand=True)
            name.bind("<KeyRelease>", lambda _: self.on_change())
            self._button(choices, "Open journal", self.open_journal)
            self._button(choices, "New", self.new_journal)
            composer = tk.Frame(self.panel, bg=PANEL, padx=8, pady=5)
            composer.pack(side="bottom", fill="x")
            self.note_button = ttk.Button(composer, text="Add note", command=self.add_note)
            self.note_button.pack(side="right", padx=(5, 0))
            self.buttons.append(self.note_button)
            self.note = tk.Text(composer, height=3, width=1, wrap="word", relief="flat", borderwidth=0,
                                highlightthickness=1, highlightbackground=EDGE, highlightcolor=ACCENT)
            self.note.pack(side="left", fill="x", expand=True)
            style_text(self.note, self.appearance, composer=True)
            self.note.insert("1.0", raw.get("note_draft", "") if isinstance(raw.get("note_draft"), str) else "")
            self.note.bind("<<Modified>>", self._note_edited)
            self.actions_menu.add_command(label="Copy latest agent reply into note", command=self.reply_to_note)
        if self.kind == "quests":
            from .quest_tree import QuestTree
            options = tk.Frame(self.panel, bg=PANEL, padx=8, pady=3)
            options.pack(fill="x")
            self.guide_auto = tk.BooleanVar(master=self.root, value=self.profile["guide_auto"])
            ttk.Checkbutton(options, text="Guide on expand", variable=self.guide_auto,
                            command=self._guide_settings).pack(side="left")
            self.guide_tier = tk.StringVar(master=self.root, value=self.profile["guide_tier"].title())
            tier = ttk.Combobox(options, values=["Auto", "Obvious", "Easy", "Complicated"], width=11,
                               state="readonly", textvariable=self.guide_tier)
            tier.pack(side="left", padx=5)
            tier.bind("<<ComboboxSelected>>", lambda _: self._guide_settings())
            self._button(options, "Retry guide", self.retry_guide)
            opened = raw.get("opened_quests") if isinstance(raw.get("opened_quests"), list) else []
            self.quest_tree = QuestTree(self.panel, on_expand=self._expand_quest, on_change=self.on_change, opened=opened)
            self.quest_tree.set_appearance(self.appearance)
            self.activity_notice.set("Refresh reads the saved quest log. Expanding a quest can start web research.")
        elif self.kind == "screen":
            self.image_label = tk.Label(self.panel, bg=PANEL, fg=MUTED,
                                       text="Capture WoW or open an image.\nReview it before asking the agent.")
            self.image_label.pack(fill="both", expand=True, padx=8, pady=8)
            self.image_label.bind("<Configure>", self.queue_image)
            self.image_label.bind("<Destroy>", lambda _: setattr(self, "_preview_image", None), add="+")
            self.activity_notice.set("Capture is manual. Nothing is recorded or sent in the background.")
            self.render_image()
        else:
            if self.kind == "character":
                from .character import SLOTS, COSMETIC
                options = tk.Frame(self.panel, bg=PANEL, padx=8, pady=3)
                options.pack(fill="x")
                slots = ["All gear"] + list(dict.fromkeys(v for k, v in SLOTS.items() if k not in COSMETIC))
                self.gear_slot = tk.StringVar(master=self.root, value=raw.get("gear_slot") if raw.get("gear_slot") in slots else "All gear")
                ttk.Combobox(options, values=slots, textvariable=self.gear_slot, state="readonly", width=11).pack(side="left")
                tk.Label(options, text="Build / goal", bg=PANEL, fg=MUTED).pack(side="left", padx=5)
                self.gear_goal = tk.StringVar(master=self.root, value=raw.get("gear_goal", "Leveling") if isinstance(raw.get("gear_goal", ""), str) else "Leveling")
                ttk.Entry(options, textvariable=self.gear_goal, width=8).pack(side="left", fill="x", expand=True)
                self.gear_goal.trace_add("write", lambda *_: self.on_change())
                self.gear_slot.trace_add("write", lambda *_: self.on_change())
            self.report_text = text_box(tk, self.panel)
            style_text(self.report_text, self.appearance)
            replace_text(self.report_text, "Press Refresh to read the selected edition's saved snapshot.\n\n"
                         "For current data, /reload in WoW first. No agent connection is needed to view this report.")
            if self.kind == "journal":
                try:
                    journal = self.activity.journal(self.journal_id)
                    self.show_journal(journal)
                    if self.pending_note and any(e.get("id") == self.pending_note["id"] for e in journal["entries"]):
                        if self.note.get("1.0", "end-1c") == self.pending_note["body"]:
                            self.note.delete("1.0", "end")
                        self.pending_note = None
                except ChatError as error:
                    self.activity_notice.set(str(error))
                if isinstance(raw.get("journal_name"), str):
                    self.journal_name.set(raw["journal_name"][:80])
        self._update_controls()

    def _update_controls(self):
        super()._update_controls()
        if self.active_quest_chat():
            self.actions_menu.entryconfigure(self.setup_menu_index, state="disabled")
        for button in self.buttons:
            button.configure(state="disabled" if self.jobs - BACKGROUND_JOBS else "normal")

    def set_appearance(self, settings):
        super().set_appearance(settings)
        for name in ("report_text", "note"):
            if hasattr(self, name):
                style_text(getattr(self, name), self.appearance, composer=name == "note")
        if hasattr(self, "quest_tree"):
            self.quest_tree.set_appearance(self.appearance)
        for view in self.quest_chats.values():
            view.set_appearance(self.appearance)

    def snapshot(self, remember=True):
        data = super().snapshot(remember)
        data["profile"] = self.profile
        data["activity"] = {"journal_id": self.journal_id, "image": self.image_name,
                            "last_setup": self.last_setup}
        if self.book:
            data["activity"]["tab"] = self.book.index("current")
        if self.kind == "journal":
            data["activity"]["note_draft"] = self.note.get("1.0", "end-1c")
            data["activity"]["journal_name"] = self.journal_name.get()[:80]
            data["activity"]["pending_note"] = self.pending_note
        if self.kind == "quests" and hasattr(self, "quest_tree"):
            data["activity"].update(opened_quests=self.quest_tree.open_ids(), guide_keys=self.guide_keys)
            # Separate bounded files keep multi-tab histories out of the layout's size limit.
            data["activity"]["quest_chats"] = list(self.quest_chats)
            for tab_id, view in self.quest_chats.items():
                saved = view.snapshot(remember)
                if saved != self._saved_quest_chats.get(tab_id):
                    write_json(self._quest_chat_path(tab_id), saved)
                    self._saved_quest_chats[tab_id] = saved
        if self.kind == "character" and hasattr(self, "gear_goal"):
            data["activity"].update(gear_key=self.gear_key, gear_goal=self.gear_goal.get()[:200], gear_slot=self.gear_slot.get())
        return data

    def _quest_chat_path(self, tab_id):
        return self.activity.storage / "quest-chats" / (str(uuid.UUID(tab_id)) + ".json")

    def active_quest_chat(self):
        if self.book:
            selected = self.book.select()
            return next((view for view in self.quest_chats.values() if str(view.root) == selected), None)
        return None

    def _tab_changed(self, _event=None):
        if not self._view_ready:
            return
        if self.shared_toolbar is not None:
            active = self.active_quest_chat() or self
            for view in [self, *self.quest_chats.values()]:
                view.selector.pack_forget()
            active.selector.pack(side="left", fill="x", expand=True)
        self._update_controls()
        self._quest_tab_labels()
        self.on_change()

    def _quest_tab_labels(self):
        if self.book and self.quest_chats:
            available = max(200, self.book.winfo_width() - 155)
            length = max(6, min(24, int(available / len(self.quest_chats) / 8) - 3))
            for view in self.quest_chats.values():
                title = view.quest_title
                self.book.tab(view.root, text=title if len(title) <= length else title[:length - 1] + "…")

    def _add_quest_chat(self, tab_id, context, state=None):
        from tkinter import ttk
        surface = self.tk.Frame(self.book, bg=PANEL)
        self.book.add(surface, text=str(context["quest"]["title"])[:18])
        state = state or {"provider": self.selected.provider if self.selected else self.default_provider,
                          "appearance": self.appearance}
        view = QuestChat(surface, self.service_factory(), activity=self.activity, context=context,
                         profile=state.get("profile", self.profile), state=state, embedded=True,
                         on_change=self.on_change, toolbar=self.shared_toolbar)
        self.quest_chats[tab_id] = view
        if self.shared_toolbar is not None:
            view.menu_button.pack_forget()  # The window's cog controls appearance for all its tabs.
            view.selector.pack_forget()
        view.close_tab_button = ttk.Button(view.selector, text="×", style="Window.TButton",
                                           command=lambda: self.close_quest_chat(tab_id))
        view.close_tab_button.pack(side="right", before=view.refresh_button, padx=(3, 0))
        view.actions_menu.add_command(label="Close quest chat tab", command=lambda: self.close_quest_chat(tab_id))
        return view

    def _restore_quest_chats(self, raw):
        if not isinstance(raw, list):
            return
        for tab_id in raw[:MAX_QUEST_CHATS]:
            if not self._valid_id(tab_id) or tab_id in self.quest_chats:
                continue
            try:
                path = self._quest_chat_path(tab_id)
                saved = read_json(path) if path.stat().st_size <= 2_000_000 else {}
            except OSError:
                saved = {}
            context = saved.get("context")
            if (not isinstance(context, dict) or not isinstance(context.get("quest"), dict)
                    or not isinstance(context["quest"].get("title"), str)
                    or not isinstance(context.get("edition"), str) or context["edition"] not in FLAVORS):
                self.activity_notice.set("A saved quest tab could not be loaded. Its local file has been kept.")
                continue
            self._add_quest_chat(tab_id, context, saved)
            self._saved_quest_chats[tab_id] = saved

    def open_quest_chat(self):
        key = self.quest_tree.selected()
        if key is None:
            self.activity_notice.set("Select a quest, then click Quest chat.")
            return
        quest = self.quest_tree.quests[key]
        edition = next(k for k, v in FLAVORS.items() if v == self.quest_tree.edition)
        identity = quest_identity(quest, edition)
        for view in self.quest_chats.values():
            if quest_identity(view.context["quest"], view.context["edition"]) == identity:
                self.book.select(view.root)
                return
        if len(self.quest_chats) >= MAX_QUEST_CHATS:
            self.activity_notice.set("Four quest chats are open. Use × in a quest chat's toolbar to close a tab first.")
            return
        context = quest_context(quest, self.quest_tree.report, self.quest_tree.guides.get(key, {}), edition,
                                self.panel_report.get("quests", {}).get("snapshot_at"))
        view = self._add_quest_chat(str(uuid.uuid4()), context)
        self.book.select(view.root)
        # Wait for initial session discovery, then perform this explicit request once.
        # The callback is deliberately not persisted or replayed after a restart.
        def opened(_result, _error):
            view.send_message(OPENING)
        view.job_callbacks["sessions"] = opened
        self.on_change()

    def close_quest_chat(self, tab_id):
        view = self.quest_chats.pop(tab_id, None)
        if view is None:
            return
        self.book.forget(view.root)
        view.close()
        self._saved_quest_chats.pop(tab_id, None)
        self._tab_changed()

    def refresh(self):
        active = self.active_quest_chat()
        if active:
            active.refresh()
        else:
            super().refresh()

    def create_session(self, provider, creation_id):
        profile = profile_settings(self.kind, self.profile)
        kind = self.kind
        if not profile["startup_context"]:
            profile.update(steps=[], skills=[], skill_files=[], context_files=[])
            kind = "chat"
        elif kind == "screen" and not self.image_name:
            kind = "chat"
        task = None if profile["startup_opening"] else "Use this context to answer the user's message."
        packet = self.activity.prepare(kind, profile, journal_id=self.journal_id, image=self.image_name, task=task)
        startup = self.activity.request_message(packet, creation_id)
        startup = "Startup context for the user's first request; do not run a separate turn:\n" + startup
        return self.service.create(provider, title=TYPES[self.kind][0], startup=startup, creation_id=creation_id), packet

    def session_started(self, preparation):
        if preparation and self.kind in preparation.get("reports", {}):
            self._fresh_refresh = False
            self._report_result(preparation["reports"], None)

    def on_tick(self):
        if not self._view_ready or self.closed:
            return
        if self._fresh_refresh and not self.busy:
            self._fresh_refresh = False
            self.refresh_panel()
        if self._guide_queue and not self.busy:
            key, quest, retry = self._guide_queue.popleft()
            self._request_quest(key, quest, retry)
        if self.auto_refresh % 10 == 0 and not self.busy and (self.guide_keys or self.gear_key):
            keys, gear = dict(self.guide_keys), self.gear_key
            def read():
                self._guidance.poll()
                return {key: self._guidance.get(value) for key, value in keys.items()}, self._guidance.get(gear) if gear else None
            def done(result, error):
                if error:
                    self.activity_notice.set(error)
                    return
                guides, equipment = result
                if self.kind == "quests":
                    for key, record in guides.items():
                        if self.guide_keys.get(key) == keys[key]:
                            self.quest_tree.set_guide(key, record)
                elif self.kind == "character" and self.gear_key == gear and equipment != self._gear_guide:
                    self._gear_guide = equipment
                    self._render_gear()
            self._submit("guides", read, on_result=done)

    def _guide_settings(self):
        self.profile["guide_auto"] = self.guide_auto.get()
        self.profile["guide_tier"] = self.guide_tier.get().lower()
        self.quest_tree.tier = self.profile["guide_tier"]
        self.on_change()

    def _expand_quest(self, key, quest):
        if not self.profile["guide_auto"]:
            return
        if key not in self.guide_keys and not any(item[0] == key for item in self._guide_queue):
            if len(self._guide_queue) >= 8:
                self.activity_notice.set("Eight quests are waiting. Expand this one again after a guide starts.")
                return
            self._guide_queue.append((key, quest, False))
            self.quest_tree.set_guide(key, {"status": "queued", "tier": quest_tier(quest, self.profile["guide_tier"])})

    def retry_guide(self):
        key = self.quest_tree.selected()
        if key and not any(item[0] == key for item in self._guide_queue):
            if len(self._guide_queue) >= 8:
                self.activity_notice.set("Eight quests are waiting. Retry after a guide starts.")
                return
            self._guide_queue.append((key, self.quest_tree.quests[key], True))

    def _request_quest(self, key, quest, retry=False):
        context = {"quest": quest, "player": self.quest_tree.report.get("player", {})}
        edition = next(k for k, v in FLAVORS.items() if v == self.profile["flavor"])
        tier = quest_tier(quest, self.profile["guide_tier"])
        provider = self.selected.provider if self.selected else self.default_provider
        generation = self._report_generation
        def done(result, error):
            if error:
                self.quest_tree.set_guide(key, {"status": "failed", "error": error, "tier": tier})
            elif generation == self._report_generation:
                self.guide_keys[key] = result
                self.quest_tree.set_guide(key, {"status": "queued", "tier": tier})
                self.on_change()
        self._submit("research", lambda: self._guidance.request("quest", context, edition, tier, provider, retry=retry), on_result=done)

    def find_gear(self):
        flavor, slot, goal = self.profile["flavor"], self.gear_slot.get(), self.gear_goal.get()[:200]
        provider = self.selected.provider if self.selected else self.default_provider
        def prepare():
            reports = self.activity.reports(["character"], flavor)
            data = dict(reports["character"]["data"])
            data.pop("age_seconds", None)
            context = {"character": data, "slot": slot, "build_or_goal": goal}
            edition = next(k for k, v in FLAVORS.items() if v == flavor)
            key = self._guidance.request("gear", context, edition, "complicated", provider, retry_failed=True)
            return reports, key
        def done(result, error):
            if error:
                self.activity_notice.set(error)
            else:
                self._report_result(result[0], None)
                self.gear_key, self._gear_guide = result[1], None
                self.activity_notice.set("Researching upgrades, requirements, and where to obtain them…")
                self.on_change()
        self._submit("research", prepare, on_result=done)

    def _render_gear(self):
        record = self._gear_guide or {}
        guide = record.get("guide")
        lines = [self._panel_base, "", "GEAR RESEARCH"]
        if guide:
            lines += [guide["summary"]] + [f"{i}. {step}" for i, step in enumerate(guide["steps"], 1)]
            lines += ["Note: " + c for c in guide["caveats"]]
            lines += [source["title"] + "\n" + source["url"] for source in guide["sources"]]
        else:
            lines += [record.get("error") or record.get("notice") or "Researching upgrades on the web…"]
        replace_text(self.report_text, "\n\n".join(lines))

    def refresh_panel(self):
        if self.kind == "journal":
            self._submit("activity", lambda: self.activity.journal(self.journal_id), on_result=self._journal_result)
            return
        flavor = self.profile["flavor"]
        if self._submit("activity", lambda: self.activity.reports([self.kind], flavor), on_result=self._report_result):
            self.activity_notice.set("Reading snapshot…")

    def _report_result(self, result, error):
        if error:
            self.activity_notice.set(error)
            return
        self.panel_report = result
        self._report_generation += 1
        report = result[self.kind]
        if self.kind == "quests":
            self._guide_queue.clear()
            self.quest_tree.load(report["data"], self.profile["flavor"], self.profile["guide_tier"])
            self.guide_keys = {key: value for key, value in self.guide_keys.items() if key in self.quest_tree.quests}
            self.activity_notice.set(f"{report['data']['quest_count']} quests · snapshot {report['data']['age_seconds']}s old. "
                                     + " ".join(report["data"]["warnings"]))
            self.on_change()
            return
        body = report["text"]
        if self.kind == "character":
            body += "\n\nEQUIPMENT\n" + "\n".join(
                f"{item['slot'].title()}: item {item['id']} · level {item['ilvl'] or 'unknown'} · "
                f"durability {str(item['durability_percent']) + '%' if item['durability_percent'] is not None else 'unknown'}"
                for item in report["data"]["gear"])
        replace_text(self.report_text, body)
        self._panel_base = body
        if self.kind == "character" and self._gear_guide:
            self._render_gear()
        self.activity_notice.set(next(k for k, v in FLAVORS.items() if v == self.profile["flavor"]) +
                                 " · /reload in game, then Refresh for current data.")

    def _journal_result(self, result, error):
        if error:
            self.activity_notice.set(error)
        else:
            self.show_journal(result)

    def show_journal(self, data):
        self.journal_name.set(data["name"])
        def date(raw):
            try:
                return datetime.fromisoformat(raw).astimezone().strftime("%b %d, %H:%M")
            except ValueError:
                return "Saved note"
        replace_text(self.report_text, "\n\n".join(date(e["at"]) + "\n" + e["text"] for e in data["entries"])
                     or "Add your first note below. Notes remain on this machine when this window closes.")
        self.report_text.see("end")
        self.activity_notice.set(f"{len(data['entries'])} notes · Saved locally · Ask agent prepares a summary request.")

    def _note_edited(self, _=None):
        if self.note.edit_modified():
            self.note.edit_modified(False)
            self.on_change()

    def add_note(self):
        body, name, journal_id = self.note.get("1.0", "end-1c"), self.journal_name.get(), self.journal_id
        pending = self.pending_note
        request_id = pending["id"] if pending and pending["body"] == body and pending["name"] == name else str(uuid.uuid4())
        def done(result, error):
            if error:
                self.activity_notice.set(error)
            else:
                self.pending_note = None
                if self.note.get("1.0", "end-1c") == body:
                    self.note.delete("1.0", "end")
                self.show_journal(result)
                self.on_change()
        if self._submit("activity", lambda: self.activity.add_note(journal_id, name, body, request_id), on_result=done):
            self.pending_note = {"id": request_id, "body": body, "name": name}
            self.activity_notice.set("Saving note…")
            self.on_change()

    def _can_switch_journal(self):
        if self.note.get("1.0", "end-1c").strip():
            self.activity_notice.set("Add your current note before switching journals.")
            return False
        return not self.jobs - BACKGROUND_JOBS

    def new_journal(self):
        if self._can_switch_journal():
            self.journal_id = str(uuid.uuid4())
            self.show_journal({"name": "My journal", "entries": []})
            self.on_change()

    def open_journal(self):
        if not self._can_switch_journal():
            return
        from tkinter import filedialog
        folder = self.activity.storage / "journals"
        path = filedialog.askopenfilename(parent=self.root, initialdir=folder, title="Open a saved journal",
                                          filetypes=[("Journal", "*.json")])
        if path:
            try:
                if Path(path).resolve().parent != folder.resolve():
                    raise ChatError("Choose a journal from the companion's journals folder.")
                data = self.activity.journal(Path(path).stem)
            except ChatError as error:
                self.activity_notice.set(str(error))
                return
            self.journal_id = Path(path).stem
            self.show_journal(data)
            self.on_change()

    def reply_to_note(self):
        replies = [m for m in self.history_cache.get(self.selection_key, []) if m.role == "assistant"]
        if replies:
            self.note.insert("end", ("\n\n" if self.note.get("1.0", "end-1c") else "") + replies[-1].text)
            self.book.select(self.panel)
        else:
            self.status.set("There is no agent reply to copy yet.")

    def capture(self):
        from .screen_capture import capture_game
        flavor = self.profile["flavor"]
        if self._submit("activity", lambda: capture_game(self.activity.storage, flavor), on_result=self._image_result):
            self.activity_notice.set("Capturing the selected edition's game window…")

    def open_image(self):
        from tkinter import filedialog
        from .screen_capture import import_image
        path = filedialog.askopenfilename(parent=self.root, title="Choose an image to discuss",
                                          filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if path:
            self._submit("activity", lambda: import_image(self.activity.storage, path), on_result=self._image_result)

    def paste_image(self):
        from .screen_capture import paste_image
        self._submit("activity", lambda: paste_image(self.activity.storage), on_result=self._image_result)

    def _image_result(self, result, error):
        if error:
            self.activity_notice.set(error)
            return
        self.image_name = result
        self._source_image = None
        self._render_size = None
        self.render_image()
        self.activity_notice.set("Review this image, then Ask agent. Nothing has been sent yet.")
        self.on_change()

    def queue_image(self, _event=None):
        if self._image_after is not None:
            self.root.after_cancel(self._image_after)
        self._image_after = self.root.after(100, self.render_image)

    def render_image(self, _event=None):
        if self._image_after is not None:
            self.root.after_cancel(self._image_after)
        self._image_after = None
        if not self.image_name:
            return
        from PIL import Image, ImageTk
        from .screen_capture import saved_image
        size = (max(100, self.image_label.winfo_width() - 12), max(100, self.image_label.winfo_height() - 12))
        if getattr(self, "_render_size", None) == (self.image_name, size):
            return
        try:
            path = saved_image(self.activity.storage, self.image_name)
            if self._source_image is None:
                with Image.open(path) as image:
                    if image.width * image.height > 40_000_000:
                        raise ChatError("Saved image exceeds the preview size limit.")
                    self._source_image = image.copy()
            image = self._source_image.copy()
            image.thumbnail(size)
            self._preview_image = ImageTk.PhotoImage(image, master=self.root)
            self.image_label.configure(image=self._preview_image, text="")
            self._render_size = (self.image_name, size)
        except (OSError, ChatError, Image.DecompressionBombError):
            self.image_label.configure(image="", text="The saved image is unavailable. Open or capture it again.")

    def show_setup(self):
        if self._setup_dialog is None:
            self._setup_dialog = SetupDialog(self)
        else:
            self._setup_dialog.root.lift()

    def prepare_request(self, *, review=True):
        if self._request_dialog is not None:
            self._request_dialog.root.lift()
            return
        if not self.selected:
            if self.desired_key:
                self.activity_notice.set("The saved session is unavailable. Choose a session or use Codex + / Claude +.")
            elif self.kind == "screen" and not self.image_name:
                self.activity_notice.set("Capture, paste, or open an image first.")
            else:
                self.start_session(on_ready=lambda: self.prepare_request(review=review))
            return
        profile = profile_settings(self.kind, self.profile)
        key, journal_id, image = self.selected.key, self.journal_id, self.image_name
        def done(result, error):
            if error:
                self.activity_notice.set(error)
                self.status.set(error)
            elif self.selection_key != key or self.profile != profile:
                self.activity_notice.set("Setup changed during preparation. Prepare the request again.")
            else:
                if review:
                    self._request_dialog = RequestDialog(self, result, key)
                    self.activity_notice.set("Prepared for review. No message has been sent.")
                else:
                    self.send_prepared(result, key, str(uuid.uuid4()))
        if self._submit("activity", lambda: self.activity.prepare(self.kind, profile, journal_id=journal_id, image=image),
                        on_result=done):
            self.activity_notice.set("Running preparation steps…")
            self.status.set("Preparing this window's opening request…")

    def send_prepared(self, packet, session_key, request_id):
        if not self.selected or self.selected.key != session_key:
            self.activity_notice.set("The selected session changed. Prepare a new request.")
            return False
        if self.jobs - BACKGROUND_JOBS:
            self.activity_notice.set("Wait for the current action to finish, then try again.")
            return False
        try:
            message = self.activity.request_message(packet, request_id)
        except (OSError, ValueError):
            self.activity_notice.set("The preparation bundle could not be saved. Nothing was sent.")
            return False
        def delivered(result, error):
            self.last_setup = ("Delivery uncertain. Check the original session before sending again." if error
                               else "Request " + result + ". Waiting for the agent's reply.")
            self.activity_notice.set(self.last_setup)
            self.on_change()
        if self.send_message(message, request_id=request_id, on_delivery=delivered):
            self.last_setup = "Request attempted. Check the original session if delivery is interrupted."
            self.activity_notice.set(self.last_setup)
            self.on_change()
            if self.book:
                self.book.select(self.root)
            return True
        return False

    def sync_profile_controls(self):
        if self.kind == "quests":
            self.guide_auto.set(self.profile["guide_auto"])
            self.guide_tier.set(self.profile["guide_tier"].title())
            self.quest_tree.tier = self.profile["guide_tier"]
        self.on_change()

    def save_preset(self):
        from tkinter import simpledialog
        name = simpledialog.askstring("Save window preset", "Preset name:", parent=self.root)
        if name and name.strip():
            try:
                label = re.sub(r'[^\w .-]', '_', name).strip('. ')[:60] or "Preset"
                path = self.activity.storage / "presets" / (label + "-" + uuid.uuid4().hex[:8] + ".json")
                write_json(path, {"version": 1, "name": name.strip()[:80], "kind": self.kind, "profile": self.profile})
                self.status.set("Window preset saved locally. Load it from another window's cog menu.")
            except OSError:
                self.status.set("The preset could not be saved. Your window settings remain available.")

    def load_preset(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, initialdir=self.activity.storage / "presets",
                                          title="Load window preset", filetypes=[("Window presets", "*.json")])
        if path:
            try:
                if Path(path).stat().st_size > 256_000:
                    raise ChatError("That preset is too large.")
                data = read_json(Path(path))
                if data.get("version") != 1 or data.get("kind") != self.kind:
                    raise ChatError("Choose a preset for this window type.")
                self.profile = profile_settings(self.kind, data.get("profile"))
                self.sync_profile_controls()
                if self._setup_dialog is not None:
                    self._setup_dialog.close()
                self.show_setup()
            except (OSError, ChatError) as error:
                self.status.set(str(error) if isinstance(error, ChatError) else "The preset could not be read.")

    def close(self):
        self._view_ready = False
        for view in self.quest_chats.values():
            view.close()
        if hasattr(self, "quest_tree"):
            self.quest_tree.close()
        for dialog in (self._setup_dialog, self._request_dialog):
            if dialog is not None:
                dialog.close()
        self._preview_image = None
        self._source_image = None
        if self._image_after is not None:
            self.root.after_cancel(self._image_after)
            self._image_after = None
        super().close()


class SetupDialog:
    def __init__(self, view):
        from tkinter import ttk
        self.view = view
        tk = view.tk
        self.root = tk.Toplevel(view.root)
        self.root.withdraw()
        self.root.title("Window setup")
        self.root.minsize(460, 480)
        self.chrome = WindowFrame(self.root, close=self.close, minimum=(460, 480))
        self.chrome.caption.set("Window setup · " + TYPES[view.kind][0])
        self.chrome.place("620x650")
        surface = self.chrome.content
        buttons = tk.Frame(surface, bg=PANEL, padx=10, pady=10)
        buttons.pack(side="bottom", fill="x")
        self.save_button = ttk.Button(buttons, text="Save setup", command=self.save)
        self.save_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right", padx=6)
        tk.Label(surface, text="Per-window settings. Ask agent sends; use the cog menu to preview.",
                 wraplength=420, bg=PANEL, fg=MUTED, justify="left", padx=10, pady=8).pack(fill="x")
        book = ttk.Notebook(surface)
        self.book = book
        book.pack(fill="both", expand=True, padx=10)
        startup, prompts, prep, skills = [tk.Frame(book, bg=PANEL, padx=10, pady=10) for _ in range(4)]
        for pane, name in ((startup, "Startup"), (prompts, "Prompts"), (prep, "Preparation"), (skills, "Skills")):
            book.add(pane, text=name)
        self.startup = {}
        for key, label in (("refresh_on_open", "Refresh reports when creating a window"),
                           ("startup_context", "Load preparation, skills and context for new chats"),
                           ("startup_opening", "Include the opening request in new chats")):
            variable = tk.BooleanVar(master=self.root, value=view.profile[key])
            ttk.Checkbutton(startup, text=label, variable=variable).pack(anchor="w", pady=5)
            self.startup[key] = variable
        tk.Label(startup, text="New chat sequence\n\n1. Read selected reports and local files.\n"
                 "2. Load skills and standing instructions.\n3. Include the opening request, if enabled.\n"
                 "4. Start the CLI with your first request.\n\n"
                 "Restore never resends requests.\n/reload in WoW saves current snapshot data.",
                 bg=PANEL, fg=MUTED, justify="left", wraplength=390).pack(fill="x", pady=12)
        self.fields = {}
        for key, label in (("instructions", "Standing instructions"), ("opening", "Opening request")):
            tk.Label(prompts, text=label, bg=PANEL, fg=TEXT, anchor="w").pack(fill="x", pady=(4, 2))
            field = text_box(tk, prompts, undo=True)
            style_text(field, view.appearance, composer=True)
            field.insert("1.0", view.profile[key])
            self.fields[key] = field
        self.flavor = tk.StringVar(master=self.root, value=next(k for k, v in FLAVORS.items() if v == view.profile["flavor"]))
        tk.Label(prep, text="Game edition", bg=PANEL, fg=TEXT).pack(anchor="w")
        ttk.Combobox(prep, values=list(FLAVORS), textvariable=self.flavor, state="readonly").pack(fill="x", pady=(3, 10))
        self.steps, self.skills = {}, {}
        for key, label in STEPS.items():
            variable = tk.BooleanVar(master=self.root, value=key in view.profile["steps"])
            ttk.Checkbutton(prep, text=label, variable=variable).pack(anchor="w", pady=3)
            self.steps[key] = variable
        tk.Label(prep, text="These preparation steps read snapshots; they do not reload the game.\n"
                 "They run for new chats when enabled, or when you prepare a request.",
                 bg=PANEL, fg=MUTED, justify="left", wraplength=400).pack(fill="x", pady=8)
        self.files = {key: list(view.profile[key]) for key in ("context_files", "skill_files")}
        self.file_lists = {}
        self.file_buttons = {}
        self._file_picker(prep, "context_files", "Context files")
        for key, label in SKILLS.items():
            variable = tk.BooleanVar(master=self.root, value=key in view.profile["skills"])
            ttk.Checkbutton(skills, text=label, variable=variable).pack(anchor="w", pady=2)
            self.skills[key] = variable
        tk.Label(skills, text="Skills accompany this request; they are not installed.\n"
                 "Custom skills: self-contained UTF-8 text, up to 64 KB.",
                 bg=PANEL, fg=MUTED, justify="left", wraplength=400).pack(fill="x", pady=5)
        self._file_picker(skills, "skill_files", "Additional skill files")
        self.root.deiconify()
        self.chrome.apply_native()

    def _file_picker(self, parent, key, title):
        from tkinter import ttk
        tk = self.view.tk
        tk.Label(parent, text=title, bg=PANEL, fg=TEXT, anchor="w").pack(fill="x", pady=(10, 3))
        holder = tk.Frame(parent, bg=PANEL)
        holder.pack(fill="both", expand=True)
        actions = tk.Frame(holder, bg=PANEL)
        actions.pack(side="bottom", fill="x", pady=5)
        add = ttk.Button(actions, text="Add…", command=lambda: self.add_files(key))
        add.pack(side="left")
        remove = ttk.Button(actions, text="Remove selected", command=lambda: self.remove_file(key))
        remove.pack(side="left", padx=5)
        self.file_buttons[key] = (add, remove)
        box = tk.Listbox(holder, height=4, width=1, bg=BACKGROUND, fg=TEXT, selectbackground="#554228")
        box.pack(fill="both", expand=True)
        self.file_lists[key] = box
        for path in self.files[key]:
            box.insert("end", Path(path).name)

    def add_files(self, key):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(parent=self.root, title="Select local text files",
                                            filetypes=[("Text", "*.md *.txt *.json")])
        for path in paths:
            if path not in self.files[key] and len(self.files[key]) < 8:
                self.files[key].append(path)
                self.file_lists[key].insert("end", Path(path).name)

    def remove_file(self, key):
        selection = self.file_lists[key].curselection()
        if selection:
            self.files[key].pop(selection[0])
            self.file_lists[key].delete(selection[0])

    def save(self):
        raw = {**self.view.profile, "flavor": FLAVORS[self.flavor.get()], "steps": [k for k, v in self.steps.items() if v.get()],
               "skills": [k for k, v in self.skills.items() if v.get()], **self.files,
               **{k: v.get() for k, v in self.startup.items()},
               **{k: field.get("1.0", "end-1c") for k, field in self.fields.items()}}
        if any(len(raw[k]) > 8000 for k in self.fields):
            from tkinter import messagebox
            messagebox.showerror("Setup too long", "Keep each prompt under 8,000 characters.", parent=self.root)
            return
        self.view.profile = profile_settings(self.view.kind, raw)
        self.view.sync_profile_controls()
        self.view.status.set("Setup saved for the next new chat or prepared request.")
        self.close()

    def close(self):
        self.view._setup_dialog = None
        self.root.destroy()


class RequestDialog:
    def __init__(self, view, packet, session_key):
        from tkinter import ttk
        self.view, self.packet, self.session_key = view, packet, session_key
        self.request_id = str(uuid.uuid4())
        self.attempted = False
        tk = view.tk
        self.root = tk.Toplevel(view.root)
        self.root.withdraw()
        self.root.title("Review agent request")
        self.root.minsize(440, 420)
        self.chrome = WindowFrame(self.root, close=self.close, minimum=(440, 420))
        self.chrome.caption.set("Review agent request")
        self.chrome.place("640x660")
        surface = self.chrome.content
        self.notice = tk.StringVar(master=self.root, value="Prepared for " + view.session_title + ". Nothing has been sent.")
        tk.Label(surface, textvariable=self.notice, bg=PANEL, fg=ACCENT, justify="left", wraplength=400,
                 padx=10, pady=8).pack(fill="x")
        actions = tk.Frame(surface, bg=PANEL, padx=10, pady=10)
        actions.pack(side="bottom", fill="x")
        self.send_button = ttk.Button(actions, text="Send request", command=self.send)
        self.send_button.pack(side="right")
        ttk.Button(actions, text="Cancel", command=self.close).pack(side="right", padx=6)
        self.preview = text_box(tk, surface)
        style_text(self.preview, view.appearance)
        replace_text(self.preview, packet_preview(packet))
        self.root.deiconify()
        self.chrome.apply_native()

    def send(self):
        view = self.view
        if self.attempted:
            return
        if not view.selected or view.selected.key != self.session_key:
            self.notice.set("The selected session changed. Close this preview and prepare a new request.")
            return
        if view.jobs - BACKGROUND_JOBS:
            self.notice.set("Wait for the current action to finish, then send this request.")
            return
        if view.send_prepared(self.packet, self.session_key, self.request_id):
            self.attempted = True
            self.close()
        else:
            self.notice.set(view.activity_notice.get())

    def close(self):
        self.view._request_dialog = None
        self.root.destroy()
