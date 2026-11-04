"""Spoken companion commands for hands-free voice.

A finished turn is matched as a whole utterance against a small grammar. A match
operates the companion's own interface: Settings menu entries, the frontmost
companion dialog's buttons, check boxes, choices, tabs and text fields, the bound
chat's session and draft, an armed gear comparison, and the companion's own voice
browser window (voice_browser). Anything else is chat.
Nothing here sends game input; game commands are recognized by assist.resolve and
executed by the hands-free controller through the existing assistive input path.
"""

from dataclasses import dataclass
import difflib
import re
import unicodedata

MAX_SPOKEN = 1200
HELP = ("Say a menu item, like open Journal or turn on keep above other windows. In a dialog, say press and a "
        "button name, check or uncheck a box, choose an option, show a tab, type some text, read it, send, or close. "
        "For chat, say switch to a session name, new Codex chat, type then send, read the reply, or just talk. "
        "With the gear comparison open and its shortcut enabled, say compare. For the voice browser, say open the "
        "browser, look up and a name, open the first result, read the page, read more, scroll down, or go back. "
        "Say stop hands free to disconnect.")


@dataclass(frozen=True)
class Outcome:
    kind: str        # "done", "refused", "chat", "game", "browser" or "disconnect"
    detail: str = ""  # for "browser", the voice_browser action
    text: str = ""   # the chat or game text, or the browser action's argument


def words(text):
    text = unicodedata.normalize("NFKC", str(text)).casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^\w' ]+", " ", text).replace("_", " ").split())


def spoken_label(label):
    # Menu labels carry shortcut hints after two spaces and trailing ellipses.
    label = re.split(r"\s{2,}", str(label))[0]
    return words(label.replace("…", " ").replace("...", " "))


FILLER = re.compile(
    r"^(?:(?:please|okay|ok|hey|lugos|helper|companion|wow helper|um|uh|so|just|quickly|now|"
    r"can you|could you|would you|will you|would you mind|can i get you to|"
    r"i want to|i wanna|i'd like to|i would like to|i need to|i need you to|i want you to|"
    r"let's|lets|let us|go ahead and)\s+)+")
TRAILER = re.compile(r"(?:\s+(?:please|for me|real quick|thanks|thank you))+$")
# "in the browser" and the like may close any browser request.
AT = r"(?: (?:in|on|with) (?:the |my |your |a )?(?:voice )?(?:browser|chrome)(?: window)?)?"


def command_words(text):
    return TRAILER.sub("", FILLER.sub("", words(text)))


def best(target, candidates):
    """The single candidate whose label matches the spoken target, or (None, close matches)."""
    target = re.sub(r"^(?:the|a|an|my) ", "", target)
    scored = []
    for item in candidates:
        label = spoken_label(item[0])
        if not label:
            continue
        if label == target:
            score = 1.0
        else:
            score = difflib.SequenceMatcher(None, target, label).ratio()
            tokens, label_tokens = target.split(), label.split()
            if tokens and all(any(t == l or (len(t) > 3 and l.startswith(t)) for l in label_tokens) for t in tokens):
                score = max(score, 0.8 + 0.1 * len(tokens) / len(label_tokens))
        scored.append((score, label, item))
    scored.sort(key=lambda row: -row[0])
    if not scored or scored[0][0] < 0.75:
        return None, []
    top = scored[0]
    rivals = [row for row in scored[1:] if row[0] > top[0] - 0.08 and row[1] != top[1]]
    if top[0] < 1.0 and rivals:
        return None, [top[1]] + [row[1] for row in rivals[:2]]
    return top[2][1], []


# Menu walking -----------------------------------------------------------------

def menu_entries(menu, path=()):
    """Every command and check button in a menu tree: (label, menu, index, type, path)."""
    rows = []
    end = menu.index("end")
    for index in range(0 if end is None else end + 1):
        kind = menu.type(index)
        if kind in {"separator", "tearoff"}:
            continue
        label = menu.entrycget(index, "label")
        if kind == "cascade":
            name = menu.entrycget(index, "menu")
            if name:
                rows += menu_entries(menu.nametowidget(name), path + (label,))
        elif kind in {"command", "checkbutton", "radiobutton"}:
            rows.append((label, menu, index, kind, path))
    return rows


def checked(menu, index):
    variable = menu.entrycget(index, "variable")
    if not variable:
        return False
    value = str(menu.getvar(variable))
    on = str(menu.entrycget(index, "onvalue") or 1)
    if on == "1":
        try:
            return bool(menu.tk.getboolean(value))
        except Exception:
            return False
    return value == on


# Dialog walking ---------------------------------------------------------------

def dialog_objects():
    """Open companion dialogs (JournalDialog and its subclasses) whose window still exists."""
    from .journal_ui import OPEN_DIALOGS
    alive = []
    for owner in list(OPEN_DIALOGS):
        try:
            if owner.root.winfo_exists():
                alive.append(owner)
        except Exception:
            pass
    return alive


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def widget_class(widget):
    try:
        return widget.winfo_class()
    except Exception:
        return ""


def visible(widget):
    try:
        return bool(widget.winfo_ismapped())
    except Exception:
        return False


def text_of(widget):
    try:
        return str(widget.cget("text"))
    except Exception:
        return ""


def enabled(widget):
    try:
        return not widget.instate(["disabled"])
    except Exception:
        try:
            return str(widget.cget("state")) != "disabled"
        except Exception:
            return True


def toplevels(root):
    """Mapped companion toplevels, lowest first."""
    try:
        names = root.tk.splitlist(root.tk.call("wm", "stackorder", "."))
        found = [root.nametowidget(name) for name in names]
    except Exception:
        found = []
    if not found:
        found = [w for w in descendants(root.nametowidget(".")) if widget_class(w) == "Toplevel" and visible(w)]
    return found


# The interpreter ---------------------------------------------------------------

class Interpreter:
    """Applies one spoken turn to the companion. `dialogs` lists dialog objects with a `.root`."""

    def __init__(self, manager, window, *, exclude=(), game=None):
        self.manager, self.window = manager, window
        self.exclude = set(exclude)
        self.game = game          # callable(text) -> True when text is a recognized game command

    # -- targets
    def view(self):
        window = self.window
        view = window.view or getattr(getattr(window, "display", None), "views", {}).get(
            getattr(getattr(window, "display", None), "active", None))
        return view if view is not None and hasattr(view, "editor") else None

    def dialog(self):
        mains = {str(w.root) for w in self.manager.windows}
        for top in reversed(toplevels(self.manager.root)):
            if str(top) not in mains and str(top) not in self.exclude:
                return top
        return None

    def later(self, action):
        # Report first; an action that opens a file picker must not hold the reply.
        self.manager.root.after_idle(action)

    # -- entry point
    def handle(self, text):
        phrase = command_words(text)
        if not phrase:
            return Outcome("refused", "Nothing was heard.")
        for pattern, method in self.GRAMMAR:
            match = re.fullmatch(pattern, phrase)
            if match:
                outcome = getattr(self, method)(*match.groups())
                if outcome is not None:
                    return outcome
        if self.game and self.game(text):
            return Outcome("game", text=text)
        menu = self.menu_command(phrase, bare=True)
        if menu is not None:
            return menu
        return Outcome("chat", text=text.strip())

    GRAMMAR = [
        (r"(?:what can i say|voice help|help|list (?:voice )?commands)", "help"),
        (r"(?:stop|end|disconnect|turn off) hands ?free(?: voice)?|disconnect voice", "disconnect"),
        (r"(?:tell|ask|say to) (?:the )?(?:agent|chat|codex|claude) (.+)", "chat"),
        (r"(?:open|open up|start|launch|show|bring up|pull up|get) (?:the |my |a |your )?(?:voice )?browser(?: window)?",
         "browser_open"),
        (r"(?:close|quit|shut) (?:down )?(?:the |my |your )?(?:voice )?browser(?: window)?", "browser_close"),
        (r"(?:google|search google for|search the web for|web search for|web search|search online for) (.+?)" + AT,
         "browser_web"),
        (r"(?:look up|lookup|look for|search for|search wowhead for|search|wowhead|find|find me|check wowhead for|pull up) (.+?) (?:on|in) classic(?: wowhead)?" + AT, "browser_classic"),
        (r"look (.+?) up(?: on wowhead)?" + AT, "browser_search"),
        (r"(?:look up|lookup|look for|search for|search wowhead for|search|wowhead|find|find me|check wowhead for|pull up) (.+?)(?: (?:on|in) wowhead)?" + AT, "browser_search"),
        (r"(?:browse to|browser go to|go to website|open website|open the website|go to the site) (.+?)" + AT,
         "browser_go"),
        (r"(?:open|open up|click|click on|follow|show me|go to|pick|take me to)(?: the)? (first|second|third|fourth|fifth|top|\d+)(?:st|nd|rd|th)? (?:result|one|link|hit)" + AT,
         "browser_result"),
        (r"(?:open|click|follow) result (one|two|three|four|five|\d+)" + AT, "browser_result"),
        (r"(?:open|click|click on|follow) (?:the )?link(?: called| named| for| that says)? (.+?)" + AT, "browser_follow"),
        (r"(?:scroll|page|go) (down|up)(?: a bit| a little| some| more| the page)?" + AT + "|scroll to the (top|bottom)",
         "browser_scroll"),
        (r"(?:go |browser )?(back|forward)(?: a page| one page| to the last page)?" + AT, "browser_history"),
        (r"(?:previous|last) page", "browser_back"),
        (r"(?:read|read me|read out|read aloud)(?: what's on| what is on)? (?:the |this )?(?:page|article|guide|browser|web page|site)"
         r"(?: to me| aloud| out loud)?|what does (?:the |this )?page say", "browser_read"),
        (r"(?:read more|keep reading|continue reading|read on|continue|keep going|go on|more|next part|what else)",
         "browser_more"),
        (r"(?:what's|what is) (?:on )?(?:the |my )?(?:browser|page)(?: showing| on)?|browser status|where is the browser",
         "browser_where"),
        (r"(?:cancel|never mind|nevermind|close(?: (?:this|the|that))?(?: (?:dialog|panel|popup|box|form))?)", "close"),
        (r"(?:press|click|hit|push|tap) (?:the )?(.+?)(?: button)?", "press"),
        (r"(?:check|tick|turn on|enable|switch on) (.+)", "check_on"),
        (r"(?:uncheck|untick|turn off|disable|switch off) (.+)", "check_off"),
        (r"(?:new|start (?:a )?new|open (?:a )?new) (codex|claude)(?: chat| session| conversation)?", "new_session"),
        (r"(?:show|open|go to) (?:the )?(.+?) tab", "tab"),
        (r"(?:switch to|go to|talk to|change to) (?:the )?(.+?)(?: chat| session| conversation)?", "switch"),
        (r"(?:choose|select|pick) (.+)", "choose"),
        (r"(?:set|put) (?:the )?(.+?) to (.+)", "set_field"),
        (r"(?:type|write|dictate|draft) (.+)", "type"),
        (r"send(?: it| that| this| the draft| draft| the message| message| the question)?", "send"),
        (r"(?:clear|delete|erase) (?:the )?draft", "clear_draft"),
        (r"read(?: me| back)?(?: the| that| last| latest)* (?:reply|answer|response)", "read_reply"),
        (r"read(?: it| that| this| back| the dialog| the digest| the review| the draft| the notice)?", "read"),
        (r"compare(?: gear| items| this| now| it| tooltips)?|capture(?: now| it| tooltips?)?", "compare"),
        (r"(?:open|show|run|start|launch|bring up|go to) (.+)", "open"),
    ]

    # -- the voice browser; the hands-free controller runs these off the interface thread
    def browser_open(self):
        return Outcome("browser", "open")

    def browser_close(self):
        return Outcome("browser", "close")

    def browser_search(self, query):
        return Outcome("browser", "search", query)

    def browser_classic(self, query):
        return Outcome("browser", "classic", query)

    def browser_web(self, query):
        return Outcome("browser", "web", query)

    def browser_go(self, site):
        return Outcome("browser", "go", site)

    def browser_result(self, which):
        return Outcome("browser", "result", which)

    def browser_follow(self, name):
        return Outcome("browser", "follow", name)

    def browser_scroll(self, direction, edge=None):
        return Outcome("browser", "scroll", direction or edge)

    def browser_history(self, step):
        return Outcome("browser", step)

    def browser_back(self):
        return Outcome("browser", "back")

    def browser_read(self):
        return Outcome("browser", "read")

    def browser_more(self):
        return Outcome("browser", "read", "more")

    def browser_where(self):
        return Outcome("browser", "where")

    # -- general
    def help(self):
        return Outcome("done", HELP)

    def disconnect(self):
        return Outcome("disconnect", "Hands-free voice disconnected.")

    def chat(self, text):
        return Outcome("chat", text=text)

    # -- dialogs
    def _buttons(self, top):
        return [(text_of(w), w) for w in descendants(top)
                if widget_class(w) in {"TButton", "Button"} and visible(w) and text_of(w).strip()]

    def close(self):
        top = self.dialog()
        if top is None:
            return Outcome("refused", "No companion dialog is open.")
        for label, button in self._buttons(top):
            if spoken_label(label) in {"close", "cancel"}:
                self.later(button.invoke)
                return Outcome("done", "Closed.")
        try:
            command = top.protocol("WM_DELETE_WINDOW")
            if command:
                self.later(lambda: top.tk.eval(command))
                return Outcome("done", "Closed.")
        except Exception:
            pass
        return Outcome("refused", "That dialog has no Close button.")

    def press(self, target):
        top = self.dialog()
        candidates = self._buttons(top) if top is not None else []
        view = self.view()
        if view is not None and top is None:
            candidates += [(text_of(b), b) for b in (view.send_button, *getattr(view, "provider_buttons", {}).values())
                           if visible(b)]
        if not candidates:
            return None  # Leave "press ..." to a menu entry of that name, then chat.
        button, close = best(target, candidates)
        if button is None:
            return Outcome("refused", "Did you mean " + " or ".join(close) + "?") if close else None
        if not enabled(button):
            return Outcome("refused", f"{spoken_label(text_of(button)).capitalize()} is unavailable right now.")
        self.later(button.invoke)
        return Outcome("done", f"Pressed {spoken_label(text_of(button))}.")

    def _checks(self, top):
        return [(text_of(w), w) for w in descendants(top) if widget_class(w) in {"TCheckbutton", "Checkbutton"}
                and visible(w)]

    def _set_check(self, target, on):
        top = self.dialog()
        if top is not None:
            box, close = best(target, self._checks(top))
            if close:
                return Outcome("refused", "Did you mean " + " or ".join(close) + "?")
            if box is not None:
                state = box.instate(["selected"]) if hasattr(box, "instate") else None
                label = spoken_label(text_of(box))
                if state == on:
                    return Outcome("done", f"{label.capitalize()} is already {'on' if on else 'off'}.")
                if not enabled(box):
                    return Outcome("refused", f"{label.capitalize()} is unavailable right now.")
                box.invoke()
                return Outcome("done", f"{label.capitalize()} {'on' if on else 'off'}.")
        return self.menu_command(target, toggle=on)

    def check_on(self, target):
        return self._set_check(target, True)

    def check_off(self, target):
        return self._set_check(target, False)

    def choose(self, target):
        top = self.dialog()
        if top is not None:
            options = []
            for w in descendants(top):
                kind = widget_class(w)
                if kind in {"TRadiobutton", "Radiobutton"} and visible(w):
                    options.append((text_of(w), ("radio", w, None)))
                elif kind == "TCombobox" and visible(w):
                    options += [(value, ("combo", w, value)) for value in w.cget("values")]
            choice, close = best(target, options)
            if close:
                return Outcome("refused", "Did you mean " + " or ".join(close) + "?")
            if choice is not None:
                kind, widget, value = choice
                if not enabled(widget):
                    return Outcome("refused", "That choice is unavailable right now.")
                if kind == "radio":
                    widget.invoke()
                    return Outcome("done", f"Chose {spoken_label(text_of(widget))}.")
                widget.set(value)
                widget.event_generate("<<ComboboxSelected>>")
                return Outcome("done", f"Chose {value}.")
        return self.switch(target)

    def tab(self, target):
        top = self.dialog()
        roots = [top] if top is not None else []
        if self.window.root is not None:
            roots.append(self.window.root)
        for root in roots:
            tabs = []
            for book in (w for w in descendants(root) if widget_class(w) == "TNotebook" and visible(w)):
                tabs += [(book.tab(tab_id, "text"), (book, tab_id)) for tab_id in book.tabs()]
            found, close = best(target, tabs)
            if close:
                return Outcome("refused", "Did you mean " + " or ".join(close) + "?")
            if found is not None:
                found[0].select(found[1])
                return Outcome("done", f"Showing {spoken_label(found[0].tab(found[1], 'text'))}.")
        return None

    def _dialog_object(self, top):
        """The dialog object behind a toplevel, found through its Close button's owner."""
        for owner in dialog_objects():
            if str(getattr(owner, "root", "")) == str(top):
                return owner
        return None

    def _editors(self, top):
        """Named text fields of a discussion dialog, else its visible text boxes and entries."""
        rows = []
        owner = self._dialog_object(top)
        for key, widget in (getattr(owner, "editors", {}) or {}).items():
            rows.append((key, widget))
        if not rows:
            rows = [(str(i), w) for i, w in enumerate(w for w in descendants(top)
                    if widget_class(w) in {"Text", "TEntry", "Entry"} and visible(w) and enabled(w))]
        return rows

    def set_field(self, name, value):
        top = self.dialog()
        if top is None:
            return None
        widget, close = best(name, [row for row in self._editors(top) if not row[0].isdigit()])
        if close:
            return Outcome("refused", "Did you mean " + " or ".join(close) + "?")
        if widget is None:
            return None
        return self._write(widget, value, replace=True, name=name)

    def _write(self, widget, value, *, replace, name="the field"):
        if widget_class(widget) == "Text":
            if str(widget.cget("state")) == "disabled":
                return Outcome("refused", "That field is read-only.")
            if replace:
                widget.delete("1.0", "end")
            current = widget.get("1.0", "end-1c")
            widget.insert("end", (" " if current and not current[-1].isspace() else "") + value)
            widget.event_generate("<<Modified>>")
        else:
            if replace:
                widget.delete(0, "end")
            current = widget.get()
            widget.insert("end", (" " if current and not current[-1].isspace() else "") + value)
        return Outcome("done", f"Typed into {name}.")

    def type(self, value):
        top = self.dialog()
        if top is not None:
            try:
                focus = top.focus_get()
            except Exception:
                focus = None
            target = None
            if focus is not None and str(focus).startswith(str(top)) and widget_class(focus) in {"Text", "TEntry", "Entry"}:
                target = focus
            else:
                rows = self._editors(top)
                target = rows[0][1] if rows else None
            if target is not None:
                return self._write(target, value, replace=False, name="the dialog")
        view = self.view()
        if view is None:
            return Outcome("refused", "There is no draft or dialog field to type into.")
        from .chat import MAX_MESSAGE
        current = view.editor.get("1.0", "end-1c")
        addition = (" " if current and not current[-1].isspace() else "") + value
        if len(current + addition) > MAX_MESSAGE:
            return Outcome("refused", "The draft is full; nothing was added.")
        view.editor.insert("end", addition)
        view.on_change()
        return Outcome("done", "Added to the draft. Say send when it is ready.")

    def send(self):
        top = self.dialog()
        if top is not None:
            for label, button in self._buttons(top):
                if spoken_label(label).startswith("send"):
                    if not enabled(button):
                        return Outcome("refused", "Send is unavailable until the review is prepared.")
                    self.later(button.invoke)
                    return Outcome("done", f"Pressed {spoken_label(label)}.")
            return Outcome("refused", "This dialog has no Send button. Say close to return to the chat.")
        view = self.view()
        if view is None or not view.editor.get("1.0", "end-1c").strip():
            return Outcome("refused", "The draft is empty. Say type and your message first, or just talk.")
        if view.selected is None:
            return Outcome("refused", "No session is selected. Say switch to a session name or new Codex chat.")
        draft = view.editor.get("1.0", "end-1c").strip()
        if not view.send_message(draft, clear_draft=True):
            return Outcome("refused", "The chat is busy; the draft was kept.")
        return Outcome("done", "Draft sent.")

    def clear_draft(self):
        view = self.view()
        if view is None:
            return Outcome("refused", "This window has no draft.")
        view.editor.delete("1.0", "end")
        view.on_change()
        return Outcome("done", "Draft cleared.")

    def read_reply(self):
        view = self.view()
        messages = view.history_cache.get(view.selection_key, []) if view is not None else []
        reply = next((m.text for m in reversed(messages) if m.role == "assistant" and m.text.strip()), "")
        if not reply:
            return Outcome("refused", "There is no reply to read yet.")
        return Outcome("done", reply.strip()[:MAX_SPOKEN])

    def read(self):
        top = self.dialog()
        if top is not None:
            owner = self._dialog_object(top)
            parts = [str(owner.notice.get())] if owner is not None and hasattr(owner, "notice") else []
            editors = getattr(owner, "editors", {}) or {}
            if editors:
                # Named fields read as "Question: ..."; review JSON is for the screen, not for speech.
                parts += [f"{key.capitalize()}: {box.get('1.0', 'end-1c')}" for key, box in editors.items()
                          if box.get("1.0", "end-1c").strip()]
            else:
                parts += [box.get("1.0", "end-1c") for box in descendants(top) if widget_class(box) == "Text" and visible(box)]
            text = "\n".join(p.strip() for p in parts if p and p.strip())
            return Outcome("done", text[:MAX_SPOKEN] if text else "This dialog has no text to read.")
        view = self.view()
        draft = view.editor.get("1.0", "end-1c").strip() if view is not None else ""
        return Outcome("done", ("The draft says: " + draft)[:MAX_SPOKEN] if draft else "The draft is empty.")

    def compare(self):
        gear = next((owner for owner in dialog_objects() if type(owner).__name__ == "GearDialog"), None)
        if gear is None or getattr(gear, "closed", False):
            return Outcome("refused", "Open Live gear comparison and enable its shortcut first.")
        if not gear.key:
            return Outcome("refused", "Enable the comparison shortcut in the gear comparison panel first.")
        from .chat import ChatError
        try:
            gear.engine.begin()
        except ChatError as error:
            return Outcome("refused", str(error))
        return Outcome("done", "Comparing. Keep the tooltips on screen.")

    # -- chat sessions
    def new_session(self, provider):
        view = self.view()
        if view is None:
            return Outcome("refused", "This window has no chat.")
        view.start_session(provider)
        return Outcome("done", f"Starting a new {provider.capitalize()} chat.")

    def switch(self, target):
        view = self.view()
        if view is None or not view.sessions:
            return None
        session, close = best(target, [(s.title, s) for s in view.sessions])
        if close:
            return Outcome("refused", "Did you mean " + " or ".join(close) + "?")
        if session is None:
            return None
        view.session_picker.current(view.sessions.index(session))
        view._select_session(session)
        return Outcome("done", f"Now talking to {session.title[:60]}.")

    # -- menus and companion commands
    def _menu_rows(self):
        rows = [(label, ("menu", menu, index, kind)) for label, menu, index, kind, _ in
                menu_entries(self.window.options_menu)]
        from .search import TYPES, SETTINGS_ACTIONS
        names = {spoken_label(row[0]) for row in rows}
        for kind, (title, _) in TYPES.items():
            if spoken_label(title) not in names:
                rows.append((title, ("search", "command", kind, "Open " + title)))
        for action, title in SETTINGS_ACTIONS:
            if spoken_label(title) not in names:
                rows.append((title, ("search", "command", action, title)))
        return rows

    def open(self, target):
        return self.menu_command(target)

    def menu_command(self, target, *, toggle=None, bare=False):
        rows = self._menu_rows()
        if bare:
            # A bare utterance is a command only when it names an entry exactly.
            rows = [row for row in rows if spoken_label(row[0]) == target]
        found, close = best(target, rows)
        if close and not bare:
            return Outcome("refused", "Did you mean " + " or ".join(close) + "?")
        if found is None:
            return None
        if found[0] == "search":
            _, kind, action, title = found
            from .search import open_row
            self.later(lambda: open_row(self.manager, self.window, {"kind": kind, "target": action}))
            return Outcome("done", f"Opening {spoken_label(title)}.")
        _, menu, index, kind = found
        label = spoken_label(menu.entrycget(index, "label"))
        if str(menu.entrycget(index, "state")) == "disabled":
            return Outcome("refused", f"{label.capitalize()} is unavailable right now.")
        if kind == "checkbutton":
            state = checked(menu, index)
            if toggle is None:
                return Outcome("refused", f"Say turn on or turn off {label}.")
            if state == toggle:
                return Outcome("done", f"{label.capitalize()} is already {'on' if toggle else 'off'}.")
            menu.invoke(index)
            return Outcome("done", f"{label.capitalize()} {'on' if toggle else 'off'}.")
        if toggle is not None:
            return None
        self.later(lambda: menu.invoke(index))
        return Outcome("done", f"{label.capitalize()}.")
