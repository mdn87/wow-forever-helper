"""Expandable quest details with wrapped guide rows and explicit source links."""

import hashlib
import json
import textwrap
import webbrowser

from .guidance import quest_tier
from .theme import ACCENT, PANEL, TEXT


class QuestTree:
    def __init__(self, parent, *, on_expand, on_change, opened=()):
        import tkinter as tk
        from tkinter import ttk
        self.on_expand, self.on_change = on_expand, on_change
        self.opened = set(opened)
        self.quests, self.guides, self.links = {}, {}, {}
        self.tier = "auto"
        self.suppress = False
        self.report = {}
        self.frame = tk.Frame(parent, bg=PANEL)
        self.frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(self.frame, show="tree", selectmode="browse", height=1)
        scroll = ttk.Scrollbar(self.frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.column("#0", width=300, stretch=True)
        self.tree.tag_configure("link", foreground=ACCENT)
        self.tree.bind("<<TreeviewOpen>>", self._expanded)
        self.tree.bind("<<TreeviewClose>>", self._collapsed)
        self.tree.bind("<Double-1>", self._open_link)
        self.tree.bind("<Return>", self._open_link)
        self.tree.bind("<Configure>", self._resize)
        self._width = 0
        self._resize_after = None
        self.font = ("Segoe UI", 10)
        self._measure = 7
        self.tree.insert("", "end", text="Loading the saved quest snapshot…")

    @staticmethod
    def key(quest, edition):
        return "q" + hashlib.sha256(json.dumps([edition, quest.get("id"), quest.get("title"),
                                                quest.get("remaining"), quest.get("action")],
                                               ensure_ascii=False).encode("utf-8")).hexdigest()[:24]

    def load(self, report, edition, tier="auto"):
        if self.quests:
            self.opened = set(self.open_ids())
        self.report, self.tier = report, tier
        self.quests = {self.key(quest, edition): quest for quest in report.get("plan", [])}
        self.guides = {key: value for key, value in self.guides.items() if key in self.quests}
        self.links.clear()
        self.suppress = True
        try:
            self.tree.delete(*self.tree.get_children())
            for key, quest in self.quests.items():
                level = f"[{quest['level']}] " if quest.get("level") else ""
                self.tree.insert("", "end", iid=key, text=level + quest["title"], open=key in self.opened)
                self.render(key)
            if not self.quests:
                self.tree.insert("", "end", text="No quests in this saved snapshot.")
        finally:
            self.suppress = False

    def open_ids(self):
        return [key for key in self.quests if self.tree.exists(key) and self.tree.item(key, "open")]

    def selected(self):
        key = self.tree.focus()
        while key and self.tree.parent(key):
            key = self.tree.parent(key)
        return key if key in self.quests else None

    def _expanded(self, _event=None):
        if not self.suppress:
            key = self.selected()
            if key and self.tree.focus() == key:
                self.opened.add(key)
                self.on_expand(key, self.quests[key])
                self.tree.after_idle(self.on_change)

    def _collapsed(self, _event=None):
        if not self.suppress:
            self.opened.discard(self.tree.focus())
            self.tree.after_idle(self.on_change)

    def _open_link(self, _event=None):
        link = self.links.get(self.tree.focus())
        if link:
            webbrowser.open(link)
            return "break"

    def set_guide(self, key, record):
        if key in self.quests and self.guides.get(key) != record:
            self.guides[key] = record
            self.render(key)

    def _line(self, parent, text, *, link=None):
        width = max(12, int((max(self.tree.winfo_width(), 300) - 90) / self._measure))
        for line in str(text).splitlines() or [""]:
            for wrapped in textwrap.wrap(line, width=width, break_long_words=True) or [""]:
                item = self.tree.insert(parent, "end", text=wrapped, tags=("link",) if link else ())
                if link:
                    self.links[item] = link

    def render(self, key):
        if not self.tree.exists(key):
            return
        position = self.tree.yview()
        selected = self.selected() == key
        for child in self.tree.get_children(key):
            self._forget_links(child)
            self.tree.delete(child)
        quest = self.quests[key]
        details = [quest.get("zone") or "Zone not recorded", "Next: " + quest["action"]]
        for line in details + quest.get("remaining", []) + quest.get("notes", []):
            self._line(key, line)
        record = self.guides.get(key, {})
        tier = record.get("tier") or quest_tier(quest, self.tier)
        label = "AI guide · " + tier.title()
        node = self.tree.insert(key, "end", text=label, open=True)
        guide = record.get("guide")
        if guide:
            self._line(node, guide["summary"])
            for index, step in enumerate(guide["steps"], 1):
                self._line(node, f"{index}. {step}")
            for caveat in guide["caveats"]:
                self._line(node, "Note: " + caveat)
            for source in guide["sources"]:
                self._line(node, "Source: " + source["title"], link=source["url"])
        else:
            text = record.get("error") or record.get("notice") or {
                "queued": "Waiting for an agent research slot…", "running": "Researching the quest on the web…",
                "failed": "Research did not finish. Use Retry guide to try again.",
            }.get(record.get("status"), "Expand this quest to request a guide automatically.")
            self._line(node, text)
        if position:
            self.tree.yview_moveto(position[0])
        if selected:
            self.tree.focus(key)
            self.tree.selection_set(key)

    def _forget_links(self, item):
        self.links.pop(item, None)
        for child in self.tree.get_children(item):
            self._forget_links(child)

    def _resize(self, event):
        if abs(event.width - self._width) < 12:
            return
        self._width = event.width
        if self._resize_after:
            self.tree.after_cancel(self._resize_after)
        self._resize_after = self.tree.after(150, self._rewrap)

    def _rewrap(self):
        self._resize_after = None
        for key in self.quests:
            self.render(key)

    def set_appearance(self, appearance):
        from tkinter import font, ttk
        self.font = (appearance["font_family"], appearance["font_size"])
        metrics = font.Font(root=self.tree, font=self.font)
        self._measure = max(1, metrics.measure("n"))
        style = ttk.Style(self.tree)
        name = "Quest" + str(id(self)) + ".Treeview"
        style.configure(name, font=self.font, background=appearance["background"],
                        fieldbackground=appearance["background"], foreground=appearance["text"],
                        rowheight=metrics.metrics("linespace") + 6)
        self.tree.configure(style=name)
        self._rewrap()

    def close(self):
        if self._resize_after:
            self.tree.after_cancel(self._resize_after)
            self._resize_after = None
