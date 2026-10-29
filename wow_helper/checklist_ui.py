"""Manual recurring activities in one journal, with reviewed planning requests."""

from copy import deepcopy
from datetime import datetime, timezone

from .chat import ChatError
from .journal import JournalService
from .journal_ui import FollowupDialog, JournalDialog
from .recurrence import completed, period, rule_summary


class ChecklistDialog(JournalDialog):
    def __init__(self, owner):
        self.owner, self.journal_id = owner, owner.journal_id
        self.followup = None
        self.goal_dialog = None
        self.rows = {}
        super().__init__(owner.view, 'Today / This week')
        self.chrome.minimum = (480, 560)
        self.root.minsize(*self.chrome.minimum)
        self.notice.set('Manual checklists for this journal. Add repeat rules in Edit goal → Repeat. '
                        'Periods use your chosen reset, not midnight or a detected game reset.')
        self.mode = self.tk.StringVar(master=self.root, value='Today')
        tabs = self.ttk.Combobox(self.surface, textvariable=self.mode, state='readonly', values=['Today', 'This week'])
        tabs.pack(fill='x', padx=8)
        tabs.bind('<<ComboboxSelected>>', lambda _: self.reload())
        listing = self.frame(self.surface); listing.pack(fill='x', padx=8, pady=6)
        self.entries = self.ttk.Treeview(listing, columns=('state', 'period'), show='tree headings',
                                         selectmode='browse', height=4, style='Journal.Treeview')
        for column, label, width in [('#0', 'Activity', 180), ('state', 'Manual state', 100), ('period', 'Reset date', 100)]:
            self.entries.heading(column, text=label)
            self.entries.column(column, width=width, minwidth=70)
        self.entries.pack(side='left', fill='both', expand=True)
        scroll = self.ttk.Scrollbar(listing, orient='vertical', command=self.entries.yview)
        scroll.pack(side='right', fill='y'); self.entries.configure(yscrollcommand=scroll.set)
        self.entries.bind('<<TreeviewSelect>>', self.selected)
        controls = self.frame(self.surface, padding=8); controls.pack(fill='x')
        for index, (label, command) in enumerate([('Complete / Undo', self.toggle), ('Refresh', self.reload),
                                                ('Edit goal…', self.edit_goal)]):
            self.ttk.Button(controls, text=label, command=command).grid(row=0, column=index, sticky='ew', padx=2)
        controls.columnconfigure((0, 1, 2), weight=1)
        planning = self.frame(self.surface, padding=8); planning.pack(fill='x')
        self.minutes, self.priorities = self.tk.StringVar(master=self.root), self.tk.StringVar(master=self.root)
        self.label(planning, 'Available minutes').grid(row=0, column=0, sticky='w')
        self.ttk.Entry(planning, textvariable=self.minutes, width=8).grid(row=0, column=1, sticky='ew')
        self.label(planning, 'Priorities').grid(row=1, column=0, sticky='w')
        self.ttk.Entry(planning, textvariable=self.priorities).grid(row=1, column=1, sticky='ew')
        planning.columnconfigure(1, weight=1)
        self.ttk.Button(planning, text='Review plan in selected chat…', command=self.plan).grid(
            row=2, column=0, columnspan=2, sticky='ew', pady=(6, 0))
        self.preview = self.text(self.surface)
        self.reload()
        self.show()

    def reload(self, selected=None):
        try:
            data = JournalService(self.view.activity.storage).load(self.journal_id)
            now = datetime.now(timezone.utc)
            rows = {}
            for entry in data['entries']:
                rule = entry.get('goal', {}).get('recurrence')
                if rule and rule['frequency'] == ('Daily' if self.mode.get() == 'Today' else 'Weekly'):
                    current = period(rule, now)
                    rows[entry['id']] = (entry, rule, current, completed(entry, rule, current))
        except ChatError as error:
            self.rows = {}
            for key in self.entries.get_children():
                self.entries.delete(key)
            self.selected()
            self.notice.set(str(error))
            return False
        self.name = data['name']
        self.rows = rows
        for key in self.entries.get_children():
            self.entries.delete(key)
        for key, (entry, rule, current, done) in rows.items():
            self.entries.insert('', 'end', iid=key, text=entry['goal']['title'], values=('Done' if done else 'Open', current))
        if rows:
            self.entries.selection_set(selected if selected in rows else next(iter(rows)))
        self.selected()
        return True

    def selected(self, _=None):
        from .task_window import replace_text
        chosen = self.entries.selection()
        row = self.rows.get(chosen[0]) if chosen else None
        if not row:
            replace_text(self.preview, 'No recurring activities in this list. Add a Daily or Weekly repeat rule to a goal.')
            return
        entry, rule, current, done = row
        lines = [entry['goal']['title'], rule_summary(rule), 'Current reset date: ' + current,
                 'Manually marked done' if done else 'Not marked complete', '', 'RECENT MANUAL HISTORY (latest 20)']
        lines += [event['at'] + ' · ' + ('Complete' if event['done'] else 'Undo') + ' · ' + event['period'] +
                  ' · ' + rule_summary(event['rule']) for event in reversed(entry.get('completions', [])[-20:])]
        replace_text(self.preview, '\n'.join(lines))

    def toggle(self):
        chosen = self.entries.selection()
        if not chosen or chosen[0] not in self.rows:
            return
        entry, rule, current, done = self.rows[chosen[0]]
        try:
            JournalService(self.view.activity.storage).complete_period(self.journal_id, entry['id'], not done,
                                                                       expected=entry, current_period=current)
        except ChatError as error:
            self.notice.set(str(error)); return
        self.reload(entry['id'])
        self.notice.set('Manual completion updated. Goal status and earlier periods are unchanged. Nothing was sent.')

    def edit_goal(self):
        from .goal_ui import GoalDialog
        if self.goal_dialog:
            self.goal_dialog.root.lift(); return
        chosen = self.entries.selection()
        if chosen and chosen[0] in self.rows:
            self.goal_dialog = GoalDialog(self, self.journal_id, self.name, entry=self.rows[chosen[0]][0])

    def plan(self):
        if self.followup:
            self.followup.root.lift(); return
        try:
            minutes = int(self.minutes.get())
            if not 1 <= minutes <= 10080 or not self.priorities.get().strip() or len(self.priorities.get()) > 1000:
                raise ValueError
        except ValueError:
            self.notice.set('Enter 1–10080 available minutes and priorities of 1–1000 characters.'); return
        if not self.view.selected:
            self.notice.set('Select a chat in the companion window first, then review the plan.'); return
        if not self.reload() or not self.rows:
            self.notice.set('No activities could be loaded for this list. Nothing was sent.'); return
        lines = [self.mode.get() + ' · reviewed manual checklist', 'This is a saved selection, not live game state.']
        for entry, rule, current, done in self.rows.values():
            goal = entry['goal']
            lines += ['', goal['title'] + ' · ' + goal['edition'], rule_summary(rule), 'Reset date: ' + current,
                      'Manually complete' if done else 'Open', 'Constraints: ' + goal['constraints'],
                      'Player decision: ' + goal['decision'], 'Next step: ' + entry.get('next_time', {}).get('text', '')]
        body = '\n'.join(lines)
        if len(body) > 8000:
            self.notice.set('This checklist is too large for one request. Use a smaller journal or research a selected goal.'); return
        entry = deepcopy(next(iter(self.rows.values()))[0])
        entry = {key: entry[key] for key in ('id', 'at')}
        entry['text'] = body
        task = (f'Suggest a practical plan for {minutes} available minutes. My priorities: {self.priorities.get().strip()}. '
                'Use only the reviewed activities, distinguish manual progress from verified facts, and do not change completion state.')
        self.followup = FollowupDialog(self, self.view, entry, task=task)

    def close(self):
        if self.goal_dialog:
            self.goal_dialog.close()
        if self.followup:
            self.followup.close()
        self.owner.checklist = None
        self.root.destroy()
