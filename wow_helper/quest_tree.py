"""Master-detail quest guide with priority groups, selectable detail pane, and clickable sources."""

import hashlib
import json
import textwrap
import webbrowser

from .guidance import quest_tier
from .markdown_text import valid_http_url
from .theme import is_modern, palette


def _quest_group(quest, current_zone):
    action = str(quest.get("action") or "").strip().lower()
    if quest.get("complete") or action.startswith(("turn in", "complete")):
        return "turnin"
    zone = str(quest.get("zone") or "").strip()
    if current_zone and zone and zone.casefold() == current_zone.casefold():
        return "zone"
    return "progress"


def _guide_badge(record):
    if not record:
        return "Not loaded"
    if record.get("guide"):
        return "Ready"
    status = record.get("status")
    return {
        "queued": "Queued…",
        "running": "Researching…",
        "failed": "Failed",
        "completed": "Ready",
    }.get(status, "Not loaded")


class QuestTree:
    GROUPS = (
        ("turnin", "Ready to turn in"),
        ("zone", "Current zone"),
        ("progress", "In progress"),
        ("pickups", "Nearby pickups"),
    )

    def __init__(self, parent, *, on_expand, on_change, on_research=None, opened=()):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.on_expand, self.on_change, self.on_research = on_expand, on_change, on_research
        self.opened = set(opened)
        self.quests, self.guides, self.links, self.pickups = {}, {}, {}, {}
        self.detail_links = {}
        self.tier = "auto"
        self.edition = ""
        self.suppress = False
        self.report = {}
        self.appearance = None

        colors = palette(parent)
        self.frame = tk.Frame(parent, bg=colors.PANEL)
        self.frame.pack(fill="both", expand=True)

        self.paned = ttk.PanedWindow(self.frame, orient="vertical")
        self.paned.pack(fill="both", expand=True)

        # Top pane: priority-grouped quest table.
        self.tree_frame = tk.Frame(self.paned, bg=colors.PANEL)
        self.tree = ttk.Treeview(
            self.tree_frame, columns=("zone", "guide"), show="tree headings",
            selectmode="browse", height=6,
        )
        self.tree.heading("#0", text="Quest")
        self.tree.heading("zone", text="Zone")
        self.tree.heading("guide", text="Guide")
        self.tree.column("#0", width=230, minwidth=120, stretch=True)
        self.tree.column("zone", width=110, minwidth=70, stretch=False)
        self.tree.column("guide", width=85, minwidth=65, anchor="e", stretch=False)
        scroll = ttk.Scrollbar(self.tree_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure("link", foreground=colors.ACCENT)
        self.tree.tag_configure("group", foreground=colors.ACCENT)
        self.tree.bind("<<TreeviewOpen>>", self._expanded)
        self.tree.bind("<<TreeviewClose>>", self._collapsed)
        self.tree.bind("<<TreeviewSelect>>", self._selected_changed)
        self.tree.bind("<Double-1>", self._open_link)
        self.tree.bind("<Return>", self._open_link)
        self.tree.bind("<Configure>", self._resize)
        self.paned.add(self.tree_frame, weight=3)

        # Bottom pane: selectable/copyable detail & AI guide pane with explicit Research quest button.
        self.detail_frame = tk.Frame(self.paned, bg=colors.PANEL)
        header = tk.Frame(self.detail_frame, bg=colors.PANEL, padx=8, pady=4)
        header.pack(fill="x")
        self.detail_title = tk.StringVar(master=self.detail_frame, value="Select a quest for details & guide")
        tk.Label(header, textvariable=self.detail_title, bg=colors.PANEL, fg=colors.ACCENT,
                 anchor="w", font=("Segoe UI", 10, "bold")).pack(side="left", fill="x", expand=True)
        self.research_button = ttk.Button(header, text="Research quest", style="Agent.TButton",
                                          command=self._request_selected, state="disabled")
        self.research_button.pack(side="right", padx=(6, 0))
        body_wrap = tk.Frame(self.detail_frame, bg=colors.PANEL)
        body_wrap.pack(fill="both", expand=True)
        self.detail = tk.Text(body_wrap, wrap="word", width=1, height=7, relief="flat", padx=8, pady=6)
        self.detail_scroll = ttk.Scrollbar(body_wrap, command=self.detail.yview)
        self.detail.configure(yscrollcommand=self.detail_scroll.set)
        self.detail_scroll.pack(side="right", fill="y")
        self.detail.pack(side="left", fill="both", expand=True)
        self.detail.configure(state="disabled")
        self.paned.add(self.detail_frame, weight=2)

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
        previous_selected = self.selected()
        self.report, self.tier = report, tier
        self.edition = edition
        self.quests = {self.key(quest, edition): quest for quest in report.get("plan", [])}
        self.guides = {key: value for key, value in self.guides.items() if key in self.quests}
        self.pickups = {}
        self.links.clear()
        self.suppress = True
        try:
            self.tree.delete(*self.tree.get_children())
            current_zone = str(report.get("zone") or report.get("player", {}).get("zone") or "").strip()
            buckets = {"turnin": [], "zone": [], "progress": []}
            for key, quest in self.quests.items():
                buckets[_quest_group(quest, current_zone)].append((key, quest))

            for group_id, group_title in self.GROUPS[:3]:
                items = buckets[group_id]
                if not items:
                    continue
                gid = f"group:{group_id}"
                self.tree.insert("", "end", iid=gid, text=f"{group_title} ({len(items)})",
                                 values=("", ""), open=True, tags=("group",))
                for key, quest in items:
                    level = f"[{quest['level']}] " if quest.get("level") else ""
                    zone = quest.get("zone") or ""
                    badge = _guide_badge(self.guides.get(key))
                    self.tree.insert(gid, "end", iid=key, text=level + quest["title"],
                                     values=(zone, badge), open=key in self.opened)
                    self.render(key)

            available = report.get("available") or []
            if available:
                gid = "group:pickups"
                self.tree.insert("", "end", iid=gid, text=f"Nearby pickups ({len(available)})",
                                 values=("", ""), open=False, tags=("group",))
                for idx, offer in enumerate(available[:100]):
                    pid = f"pickup:{idx}"
                    self.pickups[pid] = offer
                    title = str(offer.get("title") or "Available quest")
                    self.tree.insert(gid, "end", iid=pid, text=title, values=("Pickup", "Snapshot"))

            if not self.quests and not available:
                self.tree.insert("", "end", text="No quests in this saved snapshot.")
            elif previous_selected and previous_selected in self.quests:
                self.tree.focus(previous_selected)
                self.tree.selection_set(previous_selected)
        finally:
            self.suppress = False
        self._render_detail()

    def open_ids(self):
        return [key for key in self.quests if self.tree.exists(key) and self.tree.item(key, "open")]

    def _quest_for_iid(self, iid):
        while iid and iid not in self.quests:
            iid = self.tree.parent(iid)
        return iid if iid in self.quests else None

    def selected(self):
        key = self._quest_for_iid(self.tree.focus())
        if key:
            return key
        sel = self.tree.selection()
        return self._quest_for_iid(sel[0]) if sel else None

    def _selected_changed(self, _event=None):
        if not self.suppress:
            self._render_detail()

    def _expanded(self, _event=None):
        if not self.suppress:
            focus = self.tree.focus()
            if focus in self.quests:
                self.opened.add(focus)
                self.on_expand(focus, self.quests[focus])
                self._render_detail()
                self.tree.after_idle(self.on_change)

    def _collapsed(self, _event=None):
        if not self.suppress:
            self.opened.discard(self.tree.focus())
            self.tree.after_idle(self.on_change)

    def _request_selected(self):
        if self.on_research and self.selected():
            self.on_research()

    def _open_url(self, url):
        safe = valid_http_url(url)
        if safe:
            webbrowser.open(safe)

    def _open_link(self, _event=None):
        link = self.links.get(self.tree.focus())
        if link:
            self._open_url(link)
            return "break"

    def set_guide(self, key, record):
        if key in self.quests and self.guides.get(key) != record:
            self.guides[key] = record
            self.render(key)
            if self.selected() == key:
                self._render_detail()

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
        record = self.guides.get(key, {})
        self.tree.item(key, values=(quest.get("zone") or "", _guide_badge(record)))
        details = ["Next: " + quest["action"]] + list(quest.get("remaining", []))
        for line in details[:6]:
            self._line(key, line)
        guide = record.get("guide")
        if guide:
            self._line(key, "Guide: " + guide["summary"])
            for source in guide["sources"][:3]:
                self._line(key, "Source: " + source["title"], link=source["url"])
        if position:
            self.tree.yview_moveto(position[0])
        if selected:
            self.tree.focus(key)
            self.tree.selection_set(key)

    def _render_detail(self):
        colors = palette(self.detail)
        self.detail_links.clear()
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.tag_configure("heading", font=(self.font[0], self.font[1], "bold"), foreground=colors.ACCENT)
        self.detail.tag_configure("muted", foreground=colors.MUTED)
        self.detail.tag_configure("link", foreground=colors.ACCENT, underline=True)
        self.detail.tag_bind("link", "<Enter>", lambda _: self.detail.configure(cursor="hand2"))
        self.detail.tag_bind("link", "<Leave>", lambda _: self.detail.configure(cursor=""))

        key = self.selected()
        if key is None:
            sel = self.tree.selection()
            pid = sel[0] if sel and sel[0] in self.pickups else None
            if pid:
                offer = self.pickups[pid]
                self.detail_title.set("Nearby pickup · " + str(offer.get("title") or "Available quest"))
                self.research_button.configure(state="disabled")
                self.detail.insert("end", "Not yet in your saved quest log.\n", ("muted",))
                self.detail.insert("end", "Listed as available in the last snapshot; current in-game availability is unverified.\n")
            else:
                self.detail_title.set("Select a quest for details & guide")
                self.research_button.configure(state="disabled")
                self.detail.insert("end", "Select any quest above to read its objectives, guide steps, and source links.\n", ("muted",))
            self.detail.configure(state="disabled")
            return

        quest = self.quests[key]
        record = self.guides.get(key, {})
        tier = record.get("tier") or quest_tier(quest, self.tier)
        level = f"[{quest['level']}] " if quest.get("level") else ""
        self.detail_title.set(f"{level}{quest['title']}")
        self.research_button.configure(
            text="Retry guide" if record.get("guide") or record.get("status") == "failed" else "Research quest",
            state="normal" if self.on_research else "disabled",
        )
        zone = quest.get("zone") or "Zone not recorded"
        self.detail.insert("end", f"{zone}  ·  Next: {quest['action']}\n", ("muted",))
        if quest.get("remaining"):
            self.detail.insert("end", "\nObjectives\n", ("heading",))
            for item in quest["remaining"]:
                self.detail.insert("end", f"• {item}\n")
        if quest.get("notes"):
            self.detail.insert("end", "\nNotes\n", ("heading",))
            for note in quest["notes"]:
                self.detail.insert("end", f"• {note}\n")

        self.detail.insert("end", f"\nAI Guide · {tier.title()}\n", ("heading",))
        guide = record.get("guide")
        if guide:
            self.detail.insert("end", guide["summary"] + "\n\n")
            for idx, step in enumerate(guide["steps"], 1):
                self.detail.insert("end", f"{idx}. {step}\n")
            if guide.get("caveats"):
                self.detail.insert("end", "\nCaveats\n", ("heading",))
                for caveat in guide["caveats"]:
                    self.detail.insert("end", f"• {caveat}\n", ("muted",))
            if guide.get("sources"):
                self.detail.insert("end", "\nSources (click to open)\n", ("heading",))
                for idx, source in enumerate(guide["sources"]):
                    safe = valid_http_url(source.get("url", ""))
                    title = source.get("title") or source.get("url") or "Source"
                    if safe:
                        tag = f"qlink_{idx}"
                        self.detail_links[tag] = safe
                        self.detail.insert("end", f"• {title}\n", ("link", tag))
                        self.detail.tag_bind(tag, "<Button-1>", lambda _e, u=safe: self._open_url(u))
                    else:
                        self.detail.insert("end", f"• {title}\n", ("muted",))
        else:
            status_text = record.get("error") or record.get("notice") or {
                "queued": "Waiting for an agent research slot…",
                "running": "Researching this quest on the web…",
                "failed": "Research did not finish. Press Retry guide to try again.",
            }.get(record.get("status"), "Press Research quest (or expand the quest when Guide on expand is enabled) to fetch a guide.")
            self.detail.insert("end", status_text + "\n", ("muted",))
        self.detail.configure(state="disabled")

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
        from .appearance import resolved_appearance, style_text
        from tkinter import font, ttk
        self.appearance = appearance
        self.tree._companion_theme_refresh = lambda: self.set_appearance(self.appearance)
        resolved = resolved_appearance(appearance, self.tree)
        colors = palette(self.tree)
        self.tree.tag_configure("link", foreground=colors.ACCENT)
        self.tree.tag_configure("group", foreground=colors.ACCENT)
        self.font = (resolved["font_family"], resolved["font_size"])
        metrics = font.Font(root=self.tree, font=self.font)
        self._measure = max(1, metrics.measure("n"))
        style = ttk.Style(self.tree)
        name = "Quest" + str(id(self)) + ".Treeview"
        style.configure(name, font=self.font, background=resolved["background"],
                        fieldbackground=resolved["background"], foreground=resolved["text"],
                        rowheight=metrics.metrics("linespace") + 6)
        style.map(name, background=[("selected", colors.SELECT)],
                  foreground=[("selected", colors.TEXT if is_modern(self.tree) else colors.ACCENT)])
        style.configure(name + ".Heading", background=colors.TITLE, foreground=colors.TEXT)
        self.tree.configure(style=name)
        style_text(self.detail, appearance)
        self._rewrap()
        self._render_detail()

    def close(self):
        if self._resize_after:
            self.tree.after_cancel(self._resize_after)
            self._resize_after = None
