"""Persistent, independent companion windows managed by the desktop window manager."""

from pathlib import Path
import os
from copy import deepcopy
import uuid

from .chat import CHAT_STATE, ChatError, ChatService, read_json, write_json
from .task_window import TaskWindow
from .activities import ActivityService, TYPES, profile_settings
from .window_state import LayoutLock, MAX_WINDOWS, MIN_HEIGHT, MIN_WIDTH, display_workareas, window_bounds
from .theme import palette, apply_theme, display_font, settings_icon, menu as themed_menu
from .window_frame import WindowFrame
from .window_access import start_restart
from .interface import InterfaceDialog, WindowOpacity, interface_settings
from .pinned_advice import AdviceCard, PLAY_MINIMUM, pinned_selection, validate_pin
from .activity_layouts import SavedLayouts, layout_record
from .wow_displays import DISPLAY_TYPES, ActivityDeck, QuestLogDisplay, display_state, show_display_setup

LAYOUT_PATH = CHAT_STATE / "windows.json"


class CompanionWindow:
    def __init__(self, manager, record):
        from tkinter import ttk

        self.manager = manager
        self.id = record["id"]
        self.layout_key = record.get("layout_key", self.id)
        self.number = record["number"]
        self.kind = record.get("kind", "chooser")
        self.view = None
        self.display = None
        self.display_area = tuple(record["display_area"]) if isinstance(record.get("display_area"), list) else None
        self.card = None
        self.pin = validate_pin(record.get("pin")) if self.kind == "play" else None
        self.mode = "desk" if record.get("mode") == "desk" else "play"
        self.mode_bounds = dict(record.get("mode_bounds")) if isinstance(record.get("mode_bounds"), dict) else {}
        self.closed = False
        self.bounds = window_bounds(record.get("bounds"), manager.areas, self.minimum)
        self.caption = ""
        tk = manager.tk
        self.root = tk.Toplevel(manager.root)
        self.root.withdraw()
        self.root.configure(bg=palette(self.root).BACKGROUND)
        self.root.minsize(*self.minimum)
        self.topmost = tk.BooleanVar(master=self.root, value=record.get("topmost") is not False)
        self.remember = tk.BooleanVar(master=self.root, value=record.get("remember") is not False)
        self.root.attributes("-topmost", self.topmost.get())
        self.root.protocol("WM_DELETE_WINDOW", lambda: manager.close_window(self))
        self.root.bind("<Configure>", self._configure, add="+")
        self.root.bind("<Control-k>", lambda _: manager.show_search(self))
        self.search_tag = "CompanionSearch" + self.id.replace("-", "")
        self.root.bind_class(self.search_tag, "<Control-k>", lambda _: manager.show_search(self))
        self.root.bind("<Map>", self._bind_search, add="+")
        self._place()
        self.chrome = WindowFrame(self.root, close=lambda: manager.close_window(self),
                                  minimum=self.minimum)
        surface = self.chrome.content

        bar = self.toolbar = tk.Frame(surface, bg=palette(self.root).BACKGROUND, padx=8, pady=5)
        bar.pack(fill="x")
        self.new_button = ttk.Button(bar, text="+ New", command=lambda: manager.new_window(self))
        self.new_button.pack(side="left", padx=(0, 4))
        options = self.menu_button = ttk.Menubutton(bar, text="Settings", image=settings_icon(self.root),
                                                   style="Settings.TMenubutton")
        options.pack(side="right", padx=(4, 0))
        self.options_menu = themed_menu(options)
        self.windows_menu = themed_menu(self.options_menu)
        options.configure(menu=self.options_menu)
        self.options_menu.add_checkbutton(label="Keep above other windows", variable=self.topmost,
                                          command=self.set_topmost)
        self.options_menu.add_checkbutton(label="Remember draft and recent chat", variable=self.remember,
                                          command=manager.save_layout)
        if self.kind == "play":
            self.options_menu.entryconfigure("end", label="Pinned advice is always saved", state="disabled")
        self.options_menu.add_command(label="Interface & transparency…", command=lambda: manager.show_interface(self))
        self.options_menu.add_command(label="Activity layouts…", command=lambda: manager.show_activity_layouts(self))
        self.options_menu.add_command(label="Activity history…", command=lambda: manager.show_activity_history(self))
        self.options_menu.add_command(label="Usage study…", command=lambda: manager.show_usage_study(self))
        self.options_menu.add_command(label="Voice input…  Keypad -", command=lambda: manager.show_voice_input(self))
        self.options_menu.add_command(label="Search companion…  Ctrl+K", command=lambda: manager.show_search(self))

        self.options_menu.add_command(label="WoW companion displays…", command=lambda: show_display_setup(manager, self.root))
        self.options_menu.add_command(label="Chat appearance…", command=lambda: self.view.show_appearance(),
                                      state="disabled")
        self.appearance_menu_index = self.options_menu.index("end")
        self.options_menu.add_separator()
        self.options_menu.add_cascade(label="Windows", menu=self.windows_menu)
        self.options_menu.add_command(label="New window", command=lambda: manager.new_window(self))
        self.options_menu.add_command(label="Bring all windows to this screen", command=lambda: manager.arrange(self))
        self.options_menu.add_command(label="Hide all windows", command=manager.hide_all, state="disabled")
        self.hide_menu_index = self.options_menu.index("end")
        self.options_menu.add_command(label="Close this window", command=lambda: manager.close_window(self))
        self.options_menu.add_separator()
        self.options_menu.add_command(label="Restart companion (load updates)", command=manager.restart, state="disabled")
        self.restart_menu_index = self.options_menu.index("end")
        self.options_menu.add_command(label="Quit companion (stops shortcut)", command=manager.close)
        self.notice = tk.StringVar(master=self.root)
        self.notice_label = tk.Label(surface, textvariable=self.notice, bg=palette(self.root).BACKGROUND, fg=palette(self.root).MUTED,
                                    anchor="w", justify="left", padx=8, pady=3, wraplength=400,
                                    font=("Segoe UI", 8))
        self.body = tk.Frame(surface, bg=palette(self.root).PANEL)
        self.body.pack(fill="both", expand=True)
        if self.kind == "play":
            self.card = AdviceCard(self)
            self.manager.changed(self)
        elif self.kind in DISPLAY_TYPES:
            self.open_display(self.kind, record.get("display"))
        elif self.kind in TYPES:
            self.open_kind(self.kind, record.get("chat"))
        else:
            self.kind = "chooser"
            self.show_chooser()
        hidden = self.display and (record.get("display_hidden") or
                                  self.display_area is not None and self.display_area not in manager.areas)
        if not hidden:
            self.root.deiconify()
        self.chrome.apply_native()
        if not hidden and self.display:
            # Maximize after the custom caption is applied; with the native caption
            # Windows limits the window to the work area and Dias shows below it.
            self.fill_display()
        # Display windows cover Dias's whole screen, so translucency would mix the two UIs.
        self.opacity = WindowOpacity(self.root, lambda: {**manager.display_settings, "opacity": 100}
                                     if self.display else manager.display_settings)

    @property
    def minimum(self):
        return PLAY_MINIMUM if self.kind == "play" and self.mode == "play" else (MIN_WIDTH, MIN_HEIGHT)

    def _bind_search(self, event):
        # Run before Text/Entry class bindings, which otherwise edit the draft
        # on Ctrl+K. Map also covers quest tabs created after this window opens.
        widget = event.widget
        if hasattr(widget, "bindtags"):
            tags = widget.bindtags()
            if self.search_tag not in tags:
                widget.bindtags((self.search_tag, *tags))

    def toggle_play(self):
        self.mode_bounds[self.mode] = self.capture_bounds()
        self.mode = "desk" if self.mode == "play" else "play"
        self.root.minsize(*self.minimum)
        self.chrome.minimum = self.minimum
        default = dict(self.bounds, width=380, height=340) if self.mode == "play" else dict(self.bounds, width=620, height=700)
        self.bounds = window_bounds(self.mode_bounds.get(self.mode, default), self.manager.areas, self.minimum)
        self._place()
        self.card.render()
        self.manager.changed(self)

    def show_chooser(self):
        tk = self.manager.tk
        from tkinter import ttk
        chooser = tk.Frame(self.body, bg=palette(self.root).PANEL, padx=20, pady=16)
        chooser.pack(fill="both", expand=True)
        tk.Label(chooser, text="New window", bg=palette(self.root).PANEL, fg=palette(self.root).TEXT, anchor="w",
                 font=display_font(self.root, 21)).pack(fill="x")
        tk.Label(chooser, text="Choose what to open here.", bg=palette(self.root).PANEL, fg=palette(self.root).MUTED,
                 font=("Segoe UI", 10), anchor="w").pack(fill="x", pady=(4, 10))
        self.type_buttons = {}
        for kind, (title, description) in TYPES.items():
            button = ttk.Button(chooser, text="Open agent chat" if kind == "chat" else title,
                                command=lambda choice=kind: self.open_kind(choice))
            button.pack(fill="x", pady=(4, 0))
            self.type_buttons[kind] = button
            tk.Label(chooser, text=description, bg=palette(self.root).PANEL, fg=palette(self.root).MUTED, font=("Segoe UI", 9),
                     wraplength=340, justify="left", anchor="w").pack(fill="x", pady=(3, 6))
        self.chat_button = self.type_buttons["chat"]
        ttk.Button(chooser, text="Set up two WoW displays…",
                   command=lambda: show_display_setup(self.manager, self.root)).pack(fill="x", pady=(4, 0))
        ttk.Button(chooser, text="Open saved preset…", command=self.open_preset).pack(fill="x", pady=(8, 0))
        self.manager.changed(self)

    def open_chat(self, state=None):
        self.open_kind("chat", state)

    def open_display(self, kind, state=None):
        self.kind = kind
        self.display = (ActivityDeck if kind == "activities" else QuestLogDisplay)(self, state)
        self.manager.changed(self)

    def open_kind(self, kind, state=None):
        if self.view is not None or self.closed:
            return
        for child in self.body.winfo_children():
            child.destroy()
        self.kind = kind
        if not self.manager.loading:
            self.manager.record_usage(kind, "open")
        self.view = TaskWindow(self.body, self.manager.service_factory(), embedded=True, kind=kind,
                               activity=self.manager.activity_factory(), window_id=self.id,
                               service_factory=self.manager.service_factory,
                               resume_conversation=self.manager.resume_conversation,
                               pin_advice=self.manager.pin_advice,
                               state=state, on_change=lambda: self.manager.changed(self),
                               toolbar=self.toolbar, actions_menu=self.options_menu)
        self.options_menu.entryconfigure(self.appearance_menu_index, state="normal")
        self.manager.changed(self)

    def open_preset(self):
        from tkinter import filedialog
        activity = self.manager.activity_factory()
        selected = filedialog.askopenfilename(parent=self.root, initialdir=activity.storage / "presets",
                                               title="Open saved window preset", filetypes=[("Window presets", "*.json")])
        if not selected:
            return
        try:
            if Path(selected).stat().st_size > 256_000:
                raise ValueError
            data = read_json(Path(selected))
            if data.get("version") != 1 or data.get("kind") not in TYPES:
                raise ValueError
            self.open_kind(data["kind"], {"profile": profile_settings(data["kind"], data.get("profile"))})
        except (OSError, ValueError):
            self.set_notice("That window preset could not be opened.")

    def set_topmost(self):
        self.root.update_idletasks()
        self.root.attributes("-topmost", self.topmost.get())
        self.manager.schedule_save()

    def set_notice(self, message):
        self.notice.set(message)
        if message:
            self.notice_label.pack(side="bottom", fill="x", before=self.body)
        else:
            self.notice_label.pack_forget()

    def _place(self):
        b = self.bounds
        # A leading '+' before a negative coordinate means an absolute virtual-screen
        # position in Tk; a plain '-' would anchor to the opposite screen edge.
        geometry = f"{b['width']}x{b['height']}+{b['x']}+{b['y']}"
        if hasattr(self, "chrome"):
            self.chrome.place(geometry)
        else:
            self.root.geometry(geometry)

    def fill_display(self):
        """Cover the whole selected screen; a margin would leave Dias showing at the edges."""
        if self.root.state() == "zoomed":
            self.root.state("normal")
        self._place()
        if os.name == "nt" and self.display:
            self.root.state("zoomed")

    def _configure(self, event):
        if event.widget is not self.root or self.closed:
            return
        if hasattr(self, "notice_label") and getattr(self, "_wrap_width", None) != event.width:
            self._wrap_width = event.width
            self.notice_label.configure(wraplength=max(200, event.width - 24))
        if self.root.state() == "normal" and self.root.winfo_width() > 1:
            self.capture_bounds()
            self.manager.schedule_save()

    def capture_bounds(self):
        if self.root.state() == "normal" and self.root.winfo_width() > 1:
            # Top-level x/y give the outer origin, including negative monitor
            # coordinates. rootx/rooty instead include the title bar and border.
            self.bounds = {"width": self.root.winfo_width(), "height": self.root.winfo_height(),
                           "x": self.root.winfo_x(), "y": self.root.winfo_y()}
        return dict(self.bounds)

    def snapshot(self):
        extra = {"pin": self.pin, "mode": self.mode, "mode_bounds": self.mode_bounds} if self.pin else {}
        if self.display:
            extra.update(display=self.display.snapshot(self.remember.get()),
                         display_area=list(self.display_area) if self.display_area else None,
                         display_hidden=self.root.state() == "withdrawn")
        return {**extra,"id": self.id, "layout_key": self.layout_key, "number": self.number, "kind": self.kind,
                "bounds": self.capture_bounds(), "topmost": self.topmost.get(),
                "remember": self.remember.get(),
                "chat": self.view.snapshot(self.remember.get()) if self.view else {}}

    def dispose(self):
        if self.closed:
            return
        self.closed = True
        if self.manager._voice_dialog and self.manager._voice_dialog.window is self:
            self.manager._voice_dialog.close()
        self.root.unbind_class(self.search_tag, "<Control-k>")
        if self.manager._interface_dialog and self.manager._interface_dialog.parent is self.root:
            self.manager._interface_dialog.close()
        if self.manager._layouts_dialog and self.manager._layouts_dialog.parent is self.root:
            self.manager._layouts_dialog.close()
        if self.manager._search_dialog and self.manager._search_dialog.parent is self.root:
            self.manager._search_dialog.close()
        if self.manager._activity_dialog and self.manager._activity_dialog.parent is self.root:
            self.manager._activity_dialog.close()
        if self.manager._usage_dialog and self.manager._usage_dialog.parent is self.root:
            self.manager._usage_dialog.close()
        if self.card:
            self.card.close()
        self.opacity.close()
        if self.view:
            self.view.close()
        if self.display:
            self.display.close()
        self.root.destroy()


class WindowManager:
    def __init__(self, root, *, service_factory=ChatService, activity_factory=None, layout_path=LAYOUT_PATH, areas=None):
        import tkinter as tk

        self.tk, self.root = tk, root
        self.service_factory = service_factory
        self.layout_path = Path(layout_path) if layout_path is not None else None
        self.saved_layouts = SavedLayouts(self.layout_path.with_name("activity-layouts.json") if self.layout_path else None)
        self.activity_factory = activity_factory or (lambda: ActivityService(self.layout_path.parent if self.layout_path else CHAT_STATE))
        from .activity_history import ActivityHistory
        self.activity_history = ActivityHistory(self.activity_factory().storage)
        self.lock = LayoutLock(self.layout_path)
        self.windows = []
        self.closed = False
        self.loading = True
        self._save_after = None
        self.access = None
        self._access_after = None
        self._display_after = None
        self._restart_process = None
        self._interface_dialog = None
        self._layouts_dialog = None
        self._search_dialog = None
        self._activity_dialog = None
        self._usage_dialog = None
        self._voice_dialog = None
        self._interface_preview = None
        self.interface = interface_settings(None)
        self.next_number = 1
        self.areas = areas or display_workareas(root)
        root.withdraw()
        root.report_callback_exception = self._callback_error
        try:
            layout = self._load()
            self.interface = interface_settings(layout.get("interface"))
            apply_theme(root, self.interface["theme"])
            records = layout.get("windows", [])
            records = records[:MAX_WINDOWS] if isinstance(records, list) else []
            used_ids, used_numbers = set(), set()
            for raw in records:
                if not isinstance(raw, dict) or raw.get("kind") not in (*TYPES, *DISPLAY_TYPES, "chooser", "play"):
                    continue
                record = dict(raw)
                try:
                    record["id"] = str(uuid.UUID(str(record.get("id"))))
                except ValueError:
                    record["id"] = str(uuid.uuid4())
                if record["id"] in used_ids:
                    record["id"] = str(uuid.uuid4())
                number = record.get("number")
                if type(number) is not int or not 1 <= number <= 100_000 or number in used_numbers:
                    number = self.next_number
                record["number"] = number
                used_ids.add(record["id"])
                used_numbers.add(number)
                self.next_number = max(self.next_number, number + 1)
                self._add(record)
            if not self.windows:
                self.new_window(kind="chat")
            self.loading = False
            self.record_usage("companion", "start")
            self.refresh_menus()
            self.schedule_save()
            self._display_after = self.root.after(1000, self._check_display_connections)
        except Exception:
            for window in self.windows:
                window.dispose()
            self.lock.close()
            raise

    def show_voice_input(self, window):
        from .voice_ui import VoiceDialog
        if self._voice_dialog:
            self._voice_dialog.root.lift()
            self._voice_dialog.notice.set('Voice belongs to its original chat window. Close this panel before choosing another.')
        elif window.view and hasattr(window.view, 'editor'):
            self._voice_dialog = VoiceDialog(self, window)
        else:
            window.set_notice('Open a chat window to use voice input.')

    @property
    def display_settings(self):
        return self._interface_preview or self.interface

    def show_interface(self, window):
        if self._interface_dialog is None:
            self._interface_dialog = InterfaceDialog(self, window.root)
        else:
            self._interface_dialog.root.deiconify()
            self._interface_dialog.root.lift()

    def show_activity_layouts(self, window):
        self.record_usage("layouts", "open")
        from .layout_dialog import LayoutDialog
        if self._layouts_dialog is None:
            self._layouts_dialog = LayoutDialog(self, window.root)
        else:
            self._layouts_dialog.root.deiconify()
            self._layouts_dialog.root.lift()

    def show_search(self, window):
        self.record_usage("search", "open")
        from .search import SearchDialog
        if self._search_dialog is None:
            self._search_dialog = SearchDialog(self, window)
        else:
            self._search_dialog.refresh()
            self._search_dialog.root.deiconify()
            self._search_dialog.root.lift()
        return "break"

    def show_activity_history(self, window, event_id=None):
        self.record_usage("activity_history", "open")
        from .activity_ui import ActivityDialog
        if self._activity_dialog is None:
            self._activity_dialog = ActivityDialog(self, window)
        else:
            self._activity_dialog.refresh()
            self._activity_dialog.root.deiconify()
            self._activity_dialog.root.lift()
        if event_id:
            dialog = self._activity_dialog
            dialog.show_dismissed.set(True)
            dialog.refresh()
            if event_id in dialog.rows:
                dialog.results.selection_set(event_id)
                dialog.results.see(event_id)
                dialog.selected()

    def record_usage(self, feature, action):
        from .usage_study import record
        record(self.activity_factory().storage, feature, action)

    def show_usage_study(self, window):
        from .usage_ui import UsageDialog
        if self._usage_dialog is None:
            self._usage_dialog = UsageDialog(self, window)
        else:
            self._usage_dialog.refresh()
            self._usage_dialog.root.lift()

    def open_search_window(self, kind):
        if self.closed or len(self.windows) >= MAX_WINDOWS:
            raise ChatError("Eight windows are open or the companion is closing. Your drafts are kept.")
        record = {"id": str(uuid.uuid4()), "number": self.next_number, "kind": kind,
                  "chat": {"activity": {}}}
        self.next_number += 1
        return self._add(record)

    def open_wow_displays(self, quest_area, activity_area):
        areas = display_workareas(self.root)
        quest_area, activity_area = tuple(quest_area), tuple(activity_area)
        if quest_area == activity_area or quest_area not in areas or activity_area not in areas:
            raise ChatError("Choose two different connected screens. Reopen setup if the displays changed.")
        existing = {w.kind: w for w in self.windows if w.kind in DISPLAY_TYPES}
        if len(self.windows) + 2 - len(existing) > MAX_WINDOWS:
            raise ChatError("Eight windows would be exceeded. Close a window before opening both displays.")
        self.areas = areas
        previous = [(w, w.capture_bounds(), w.display_area, w.root.state()) for w in existing.values()]
        created, pair = [], []
        self.loading = True
        try:
            for kind, area in (("questlog", quest_area), ("activities", activity_area)):
                window = existing.get(kind)
                if window is None:
                    record = dict(id=str(uuid.uuid4()), number=self.next_number, kind=kind,
                                  display_area=list(area), bounds=dict(x=area[0], y=area[1],
                                  width=area[2] - area[0] - 24, height=area[3] - area[1] - 48))
                    self.next_number += 1
                    window = self._add(record)
                    created.append(window)
                window.display_area = area
                window.bounds = window_bounds(dict(x=area[0], y=area[1], width=area[2] - area[0] - 24,
                                                    height=area[3] - area[1] - 48), areas, window.minimum)
                window.root.deiconify()
                window.fill_display()
                window.root.lift()
                pair.append(window)
            self.root.update_idletasks()
            if not self.save_layout():
                raise ChatError("The display arrangement could not be saved. Your previous windows are kept.")
        except Exception:
            for window in created:
                self.windows.remove(window)
                window.dispose()
            for window, bounds, area, state in previous:
                window.bounds, window.display_area = bounds, area
                window._place()
                if state == "withdrawn":
                    window.root.withdraw()
            raise
        finally:
            self.loading = False
            self.refresh_menus()
        return tuple(pair)

    def swap_wow_displays(self):
        """Trade the quest log and activity cards between their two selected screens."""
        quest = next((w for w in self.windows if w.kind == "questlog"), None)
        cards = next((w for w in self.windows if w.kind == "activities"), None)
        if not quest or not cards or not quest.display_area or not cards.display_area:
            return
        try:
            self.open_wow_displays(cards.display_area, quest.display_area)
        except ChatError as error:
            quest.set_notice(str(error))
            cards.set_notice(str(error))

    def return_to_dias(self):
        displays = [w for w in self.windows if w.display]
        visible = [w for w in displays if w.root.state() != "withdrawn"]
        if not self.can_reopen and not any(w not in displays for w in self.windows):
            self.new_window()
        for window in displays:
            window.root.withdraw()
        if not self.save_layout():
            for window in visible:
                window.root.deiconify()
                window.fill_display()

    def _check_display_connections(self):
        self._display_after = None
        if self.closed:
            return
        displays = [w for w in self.windows if w.display and w.display_area is not None]
        if displays:
            areas = display_workareas(self.root)
            for window in displays:
                if window.display_area not in areas and window.root.state() != "withdrawn":
                    window.root.withdraw()
                    self.schedule_save()
        self._display_after = self.root.after(1000, self._check_display_connections)

    def save_activity_layout(self, name, *, replace=False):
        if self.closed:
            raise ChatError("The companion is closing. Reopen it to save an arrangement.")
        return self.saved_layouts.save(name, [layout_record(w) for w in self.windows], replace=replace)

    def _layout_topology(self):
        return deepcopy([(w.id, w.layout_key, w.kind, w.pin) for w in self.windows])

    def preview_activity_layout(self, name):
        saved = self.saved_layouts.get(name)
        reuse, create, skipped = [], [], []
        available = list(self.windows)
        for record in saved["windows"]:
            compatible = [w for w in available if record["id"] in (w.id, w.layout_key)
                          and w.kind == record["kind"] and w.pin == record.get("pin")]
            window = next((w for w in compatible if w.id == record["id"]), next(iter(compatible), None))
            if window:
                reuse.append((window, record))
                available.remove(window)
            elif len(self.windows) + len(create) < MAX_WINDOWS:
                create.append(record)
            else:
                skipped.append(record)
        return {"saved": saved, "topology": self._layout_topology(), "reuse": reuse,
                "create": create, "keep": available, "skipped": skipped}

    def _apply_activity_settings(self, window, record, *, tab=None, recover=True):
        if window.display:
            area = record.get("display_area")
            window.display_area = tuple(area) if area else None
        if window.card:
            window.mode = record["mode"]
            window.mode_bounds = deepcopy(record["mode_bounds"])
            window.root.minsize(*window.minimum)
            window.chrome.minimum = window.minimum
            window.card.render()
        if window.view:
            view = window.view
            chat = record["chat"]
            view.set_appearance(chat["appearance"])
            if view.book:
                view.book.select(chat["activity"].get("tab", 0) if tab is None else tab)
            if window.kind == "character":
                for key in ("gear_goal", "gear_slot"):
                    if key in chat["activity"]:
                        getattr(view, key).set(chat["activity"][key])
        window.topmost.set(record["topmost"])
        window.root.attributes("-topmost", record["topmost"])
        # Recovery belongs to an accepted restore. Rollback must put the exact
        # previous arrangement back, including a manually oversized window.
        window.bounds = (window_bounds(record["bounds"], self.areas, window.minimum)
                         if recover else dict(record["bounds"]))
        window._place()
        self.changed(window)

    def restore_activity_layout(self, plan, *, allow_partial=False):
        if self.closed or plan["topology"] != self._layout_topology() or self.saved_layouts.get(plan["saved"]["name"]) != plan["saved"]:
            raise ChatError("The windows or saved layout changed. Preview the arrangement again before restoring.")
        if plan["skipped"] and not allow_partial:
            raise ChatError("Eight windows would be exceeded. Preview and choose Restore available, or close a window first.")
        self.areas = display_workareas(self.root)
        previous = [(w, layout_record(w), w.view.book.select() if w.view and w.view.book else None,
                     w.root.state()) for w, _ in plan["reuse"]]
        added = []
        self.loading = True
        try:
            for window, record in plan["reuse"]:
                self._apply_activity_settings(window, record)
                if window.display_area is not None and window.display_area not in self.areas:
                    window.root.withdraw()
                else:
                    window.root.deiconify()
                    if window.display:
                        window.fill_display()
            for raw in plan["create"]:
                record = deepcopy(raw)
                record["layout_key"] = record["id"]
                if any(w.id == record["id"] for w in self.windows):
                    record["id"] = str(uuid.uuid4())
                record["number"] = self.next_number
                self.next_number += 1
                added.append(self._add(record))
            self.root.update_idletasks()
            if not self.save_layout():
                raise ChatError("The arrangement could not be saved. Your previous windows and drafts are kept.")
        except Exception:
            for window in added:
                self.windows.remove(window)
                window.dispose()
            for window, record, tab, state in previous:
                self._apply_activity_settings(window, record, tab=tab, recover=False)
                if state == "withdrawn":
                    window.root.withdraw()
            self.root.update_idletasks()
            raise
        finally:
            self.loading = False
            self.refresh_menus()
        return len(plan["reuse"]) + len(added)

    def preview_interface(self, settings):
        self._interface_preview = interface_settings(settings) if settings is not None else None
        apply_theme(self.root, self.display_settings["theme"])
        for window in self.windows:
            if not window.closed:
                window.opacity.apply()

    def _load(self):
        if not self.layout_path:
            return {}
        try:
            if self.layout_path.stat().st_size > 16_000_000:
                return {}
        except OSError:
            return {}
        data = read_json(self.layout_path)
        if data.get("version") == 1:
            for record in data.get("windows", []) if isinstance(data.get("windows"), list) else []:
                if isinstance(record, dict) and record.get("kind") in tuple(DISPLAY_TYPES):
                    display_state(record["kind"], record.get("display"))
                    area = record.get("display_area")
                    if area is not None and (not isinstance(area, list) or len(area) != 4 or
                                             any(type(v) is not int for v in area)):
                        raise ChatError("Saved companion display position is invalid. The existing layout is kept.")
                if isinstance(record, dict) and record.get("kind") == "play":
                    # Refuse damaged cards before any restore or automatic save.
                    try:
                        validate_pin(record.get("pin"))
                    except ChatError:
                        raise ChatError("Saved pinned advice could not be read. The existing layout is kept; restore a valid local backup.") from None
            return data
        return {}

    def _add(self, record):
        window = CompanionWindow(self, record)
        self.windows.append(window)
        self.refresh_menus()
        self.schedule_save()
        return window

    def new_window(self, source=None, *, kind="chooser"):
        if self.closed or len(self.windows) >= MAX_WINDOWS:
            return None
        bounds = source.capture_bounds() if source else {}
        if source:
            bounds.update(x=bounds["x"] + 32, y=bounds["y"] + 32)
        record = {"id": str(uuid.uuid4()), "number": self.next_number, "kind": kind,
                  "bounds": bounds, "topmost": source.topmost.get() if source else True,
                  "remember": source.remember.get() if source else True}
        self.next_number += 1
        return self._add(record)

    def pin_advice(self, selection, objective, next_step, appearance=None):
        if self.closed:
            raise ChatError("The companion is closing. Your review is kept.")
        if len(self.windows) >= MAX_WINDOWS:
            raise ChatError("Eight windows are open. Close one before pinning; your review and drafts are kept.")
        pin = pinned_selection(selection, objective, next_step, appearance)
        record = {"id": str(uuid.uuid4()), "number": self.next_number, "kind": "play",
                  "pin": pin, "bounds": {"width": 380, "height": 340}, "mode": "play"}
        self.next_number += 1
        window = self._add(record)
        if not self.save_layout():
            self.windows.remove(window)
            window.dispose()
            self.refresh_menus()
            raise ChatError("Could not save the pinned card. Your review is kept; try again after saving works.")
        self.record_usage("pinned", "save")
        return window

    def resume_conversation(self, source):
        """Reveal or restore the exact saved session, without an opening request."""
        from .journal import metadata
        metadata(source=source)
        key = (source["provider"], source["session_id"])
        for window in self.windows:
            views = [(None, window.view)] if window.view else []
            if isinstance(window.display, ActivityDeck):
                views += list(window.display.views.items())
            for activity, view in views:
                for candidate in [view, *view.quest_chats.values()]:
                    if candidate.selection_key == key:
                        if activity:
                            window.display.open_activity(activity)
                        if view.book:
                            view.book.select(candidate.root)
                        self.reveal(window)
                        return candidate
        if len(self.windows) >= MAX_WINDOWS:
            raise ChatError("Eight windows are open. Close one before opening this conversation; notes and drafts are kept.")
        if self.closed:
            raise ChatError("The companion is closing. Reopen it to resume this note.")
        record = {"id": str(uuid.uuid4()), "number": self.next_number, "kind": "chat",
                  "chat": {"session": {"provider": key[0], "id": key[1]}, "title": "Saved conversation"}}
        self.next_number += 1
        return self._add(record).view

    def changed(self, window):
        if self.closed or window.closed:
            return
        previous = window.caption
        if window.card:
            window.caption = "Pinned advice · " + ("Play" if window.mode == "play" else "Desk")
        elif window.kind in DISPLAY_TYPES:
            window.caption = DISPLAY_TYPES[window.kind]
        elif window.view:
            suffix = window.view.session_title[:50].replace("\n", " ") or "Choose a session"
            if window.view.selection_key and not window.view.selected:
                suffix += " · Disconnected"
            title = "Chat" if window.kind == "chat" else TYPES[window.kind][0]
            window.caption = f"{title} {window.number} · {suffix}" if window.kind == "chat" or window.view.selection_key else f"{title} {window.number}"
        else:
            window.caption = f"Window {window.number} · Choose a window type"
        if previous != window.caption:
            window.root.title("WoW Companion · " + window.caption)
            window.chrome.caption.set(window.caption)
            self.refresh_menus()
        self.schedule_save()

    def refresh_menus(self):
        for window in self.windows:
            window.new_button.configure(state="disabled" if len(self.windows) >= MAX_WINDOWS else "normal")
            window.options_menu.entryconfigure(
                window.hide_menu_index, state="normal" if self.can_reopen else "disabled",
                label=(f"Hide all windows ({self.access.shortcut} reopens)" if self.can_reopen
                       else "Hide all windows (shortcut unavailable)"))
            window.options_menu.entryconfigure(window.restart_menu_index,
                                               state="normal" if self.can_restart else "disabled")
            window.windows_menu.delete(0, "end")
            for other in self.windows:
                window.windows_menu.add_command(label=other.caption,
                                                 command=lambda w=other: self.reveal(w))
            window.windows_menu.add_separator()
            window.windows_menu.add_command(label="Quit companion (stops shortcut)", command=self.close)

    @property
    def can_reopen(self):
        return bool(not self.closed and self.access and self.access.available)

    @property
    def can_restart(self):
        return bool(not self.closed and self.access and self.access.restart_handle and self._restart_process is None)

    def restart(self):
        if not self.can_restart or not self.save_layout():
            return
        try:
            self._restart_process = start_restart(self.access.hotkey)
        except OSError:
            for window in self.windows:
                window.set_notice("Could not start the restart command. The companion is still open.")
            return
        self.refresh_menus()

    def enable_reopening(self, access):
        self.access = access
        self.refresh_menus()
        self._check_reopen()
        self.save_layout()

    def _check_reopen(self):
        if self.closed:
            return
        if self._access_after is not None:
            self.root.after_cancel(self._access_after)
            self._access_after = None
        if self.access.restart_requested():
            self.show_all()
            self.close()
            if self.closed:
                return
        if self._restart_process is not None and self._restart_process.poll() is not None:
            self._restart_process = None
            self.refresh_menus()
            for window in self.windows:
                window.set_notice("Restart did not finish. Check that windows can be saved, then try again.")
        if self.access.requested():
            self.show_all()
        self._access_after = self.root.after(100, self._check_reopen)

    def show_all(self):
        for window in self.windows:
            self.reveal(window)

    def hide_all(self):
        if not self.can_reopen or not self.save_layout():
            return
        for window in self.windows:
            window.root.withdraw()

    def reveal(self, window):
        if self.closed or window not in self.windows:
            return
        self.areas = display_workareas(self.root)
        if window.display_area is not None and window.display_area not in self.areas:
            window.set_notice("The selected display is missing. Choose screens again in WoW companion displays.")
            return
        bounds = window_bounds(window.capture_bounds(), self.areas, window.minimum)
        window.root.deiconify()
        window.bounds = bounds
        if window.display:
            window.fill_display()
        else:
            window._place()
        window.root.lift()

    def arrange(self, source):
        """Recover all windows on the source monitor through an explicit menu action."""
        bounds = source.capture_bounds()
        self.areas = display_workareas(self.root)
        area = next((a for a in self.areas if a[0] <= bounds["x"] < a[2]
                     and a[1] <= bounds["y"] < a[3]), self.areas[0])
        for index, window in enumerate(self.windows):
            raw = window.capture_bounds()
            raw.update(x=area[0] + 24 + index * 32, y=area[1] + 24 + index * 32)
            bounds = window_bounds(raw, [area], window.minimum)
            window.root.deiconify()
            window.bounds = bounds
            window._place()
        self.schedule_save()

    def close_window(self, window):
        if self.closed or window not in self.windows:
            return
        if len(self.windows) == 1:
            # Keep the final draft and a working way back into the app. Without
            # a registered shortcut, retain normal last-window exit behavior.
            if self.can_reopen:
                self.hide_all()
            else:
                self.close()
            return
        self.windows.remove(window)
        window.dispose()
        self.refresh_menus()
        self.save_layout()

    def schedule_save(self):
        if self.loading or self.closed or self.layout_path is None:
            return
        if self._save_after is not None:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(500, self.save_layout)

    def save_layout(self):
        if self.closed:
            return True
        if self._save_after is not None:
            self.root.after_cancel(self._save_after)
            self._save_after = None
        if self.layout_path is None:
            return True
        try:
            data = {"version": 1, "interface": dict(self.interface),
                    "windows": [window.snapshot() for window in self.windows]}
            write_json(self.layout_path, data)
        except (OSError, ChatError):
            for window in self.windows:
                window.set_notice("Could not save windows. Keep the companion open and try again.")
            return False
        else:
            for window in self.windows:
                if not self.can_reopen and self.access and self.access.api:
                    window.set_notice(f"{self.access.shortcut} unavailable. Use the launch command to reopen.")
                else:
                    window.set_notice("")
            return True

    def _callback_error(self, *_):
        for window in self.windows:
            window.set_notice("That action could not finish. Try again or refresh the chat.")

    def close(self):
        if self.closed:
            return
        if not self.save_layout():
            return
        self.closed = True
        if self._voice_dialog:
            self._voice_dialog.close()
        if self._display_after is not None:
            self.root.after_cancel(self._display_after)
            self._display_after = None
        if self._access_after is not None:
            self.root.after_cancel(self._access_after)
            self._access_after = None
        if self.access:
            self.access.close()
        for window in self.windows:
            window.dispose()
        self.lock.close()
        self.root.destroy()
