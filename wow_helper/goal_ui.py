"""Small explicit goal editor, using the existing journal and follow-up flow."""

from copy import deepcopy
import uuid

from .activities import FLAVORS
from .chat import ChatError
from .goals import KINDS, STATES, TEXT_LIMITS, validate_goal
from .journal import JournalService
from .journal_ui import JournalDialog, note_summary


class GoalDialog(JournalDialog):
    def __init__(self, owner, journal_id, name, *, entry=None, selection=None):
        self.owner, self.journal_id, self.name = owner, journal_id, name
        self.original = deepcopy(entry)
        self.selection = deepcopy(selection)
        key = owner.view.selection_key
        self.manual_source = {'provider': key[0], 'session_id': key[1]} if key else None
        self.manual_title = owner.view.session_title if key else 'None selected'
        self.note_id = entry['id'] if entry else str(uuid.uuid4())
        self.fields, self.editors = {}, {}
        super().__init__(owner.view, 'Personal goal')
        if selection:
            # The reply destination picker adds two controls above the goal fields.
            self.chrome.minimum = (440, 540)
            self.root.minsize(*self.chrome.minimum)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.notice.set('Save a goal and your chosen next step. Suggestions remain separate from your decisions. '
                        'Ownership and progress are manual; saving sends nothing.')
        self.book = self.ttk.Notebook(self.surface)
        self.book.pack(fill='both', expand=True, padx=8)
        main, plan, decisions, evidence = [self.tab(title) for title in ('Goal', 'Plan', 'Decisions', 'Evidence')]
        repeat = self.tab('Repeat')
        from .recurrence import DAYS
        self.field(repeat, 'frequency', 'Repeat', choices=['None', 'Daily', 'Weekly'])
        self.field(repeat, 'zone', 'IANA time zone (for example America/New_York)')
        self.field(repeat, 'reset_time', 'Reset time (HH:MM, 24-hour)')
        self.field(repeat, 'weekday', 'Weekly reset day', choices=DAYS)
        hint = self.label(repeat, 'DST: first repeated time; missing times shift forward. '
                         'Rule changes keep prior history. Game resets are not detected.')
        hint.configure(wraplength=370, justify='left'); hint.pack(fill='x', pady=8)
        if selection:
            data = JournalService(self.view.activity.storage).load(journal_id)
            self.targets = [None] + [e for e in data['entries'] if e.get('goal')]
            self.label(main, 'Save as a new goal or update an existing goal').pack(anchor='w')
            self.target = self.ttk.Combobox(main, state='readonly', values=['New goal'] +
                                          [f"{i + 1}. {e['goal']['title']}" for i, e in enumerate(self.targets[1:])])
            self.target.pack(fill='x'); self.target.current(0)
            self.target.bind('<<ComboboxSelected>>', self.choose_target)
        self.field(main, 'title', 'Goal')
        self.field(main, 'kind', 'Type', choices=KINDS)
        self.field(main, 'edition', 'Game edition', choices=['Unknown', *FLAVORS])
        self.field(main, 'state', 'Goal status (manual)', choices=STATES)
        self.field(main, 'next_step', 'My next step (optional)')
        self.field(plan, 'url', 'Source link (optional; http or https)')
        self.editor(plan, 'requirements', 'Researched requirements — unknown until supported')
        self.editor(plan, 'suggestions', 'Agent suggestions — review before adopting')
        self.editor(decisions, 'constraints', 'My constraints: time, solo/group, budget, preferences')
        self.editor(decisions, 'decision', 'My decision')
        self.editor(decisions, 'progress', 'My progress or ownership notes (manual)')
        self.evidence = self.text(evidence)
        self.ttk.Button(self.actions, text='Save goal', command=self.save).pack(side='left')
        self.load_fields(entry)
        self.show()

    def tab(self, title):
        tab = self.frame(self.book, padding=8)
        self.book.add(tab, text=title)
        return tab

    def field(self, parent, key, title, choices=None):
        self.label(parent, title).pack(anchor='w', pady=(4, 0))
        var = self.tk.StringVar(master=self.root)
        widget = (self.ttk.Combobox(parent, textvariable=var, values=choices, state='readonly') if choices
                  else self.ttk.Entry(parent, textvariable=var))
        widget.pack(fill='x')
        self.fields[key] = var

    def editor(self, parent, key, title):
        label = self.label(parent, title)
        label.configure(wraplength=370, justify='left')
        label.pack(anchor='w', pady=(4, 0))
        area = self.frame(parent)
        area.pack(fill='both', expand=True)
        self.editors[key] = self.text(area, editable=True)
        self.editors[key].configure(height=1)

    def form(self):
        return {**{k: v.get() for k, v in self.fields.items()},
                **{k: v.get('1.0', 'end-1c') for k, v in self.editors.items()}}

    def load_fields(self, entry):
        from .task_window import replace_text
        self.original = deepcopy(entry)
        self.note_id = entry['id'] if entry else self.note_id
        goal = deepcopy(entry.get('goal', {})) if entry else {}
        initial = entry or self.selection or {}
        defaults = {k: '' for k in TEXT_LIMITS}
        defaults.update(title=initial.get('text', '').split('\n')[0][:200], kind='Free text', state='Planned',
                        edition=initial.get('evidence', {}).get('edition', 'Unknown'))
        if not initial:
            defaults['edition'] = next((k for k, v in FLAVORS.items() if v == self.view.profile['flavor']), 'Unknown')
        defaults.update(goal)
        from .recurrence import DAYS
        rule = goal.get('recurrence', {})
        defaults.update(frequency=rule.get('frequency', 'None'), zone=rule.get('zone', ''),
                        reset_time=rule.get('time', ''), weekday=DAYS[rule.get('weekday', 0)])
        if defaults['edition'] not in FLAVORS:
            defaults['edition'] = 'Unknown'
        if self.selection:
            defaults['suggestions'] = self.selection['text']
        defaults['next_step'] = (entry or self.selection or {}).get('next_time', {}).get('text', '')
        for key, variable in self.fields.items():
            variable.set(defaults[key])
        for key, widget in self.editors.items():
            widget.delete('1.0', 'end'); widget.insert('1.0', defaults[key])
        body = note_summary(initial) if initial else ('Conversation chosen when this editor opened: ' + self.manual_title +
                '\nNo game evidence recorded. Ownership and completion are unknown.')
        if self.selection and entry:
            body += '\n\nNEW REVIEWED SUGGESTION\n' + note_summary(self.selection)
        replace_text(self.evidence, body)
        self.loaded_form = self.form()

    def choose_target(self, _=None):
        # Do not silently discard edits when switching the destination for a reply.
        if self.form() != self.loaded_form:
            self.target.current(self.target_index)
            self.notice.set('Save or close this draft before choosing another goal. Your edits are kept.')
            return
        self.target_index = self.target.current()
        self.note_id = str(uuid.uuid4())
        self.load_fields(self.targets[self.target_index])

    target_index = 0

    def save(self):
        form = self.form()
        goal = {k: v for k, v in form.items() if k not in {'next_step', 'frequency', 'zone', 'reset_time', 'weekday'}}
        if form['frequency'] != 'None':
            from .recurrence import DAYS
            goal['recurrence'] = dict(frequency=form['frequency'], zone=form['zone'].strip(),
                                      time=form['reset_time'].strip(), weekday=DAYS.index(form['weekday'])
                                      if form['frequency'] == 'Weekly' else 0)
        if self.selection:
            goal['review'] = {k: deepcopy(v) for k, v in self.selection.items() if k in {'text', 'source', 'evidence'}}
        elif self.original and self.original.get('goal', {}).get('review'):
            goal['review'] = deepcopy(self.original['goal']['review'])
        next_text = form['next_step'].strip()
        previous = (self.original or {}).get('next_time', {})
        step = ({'text': next_text, 'state': previous.get('state', 'open') if previous.get('text') == next_text else 'open'}
                if next_text else None)
        service = JournalService(self.view.activity.storage)
        try:
            goal = validate_goal(goal)
            if self.original:
                data = service.update_goal(self.journal_id, self.note_id, goal, step, expected=self.original)
            else:
                initial = self.selection or {}
                data = service.add(self.journal_id, self.name, initial.get('text') or goal['title'], self.note_id,
                                   source=initial.get('source') or self.manual_source,
                                   evidence=initial.get('evidence'), next_time=step, goal=goal)
        except ChatError as error:
            self.notice.set(str(error))
            return
        self.original = deepcopy(next(e for e in data['entries'] if e['id'] == self.note_id))
        self.loaded_form = self.form()
        if hasattr(self.owner, 'reload'):
            self.owner.reload(self.note_id)
        self.notice.set('Goal saved locally. Use Research / follow-up in Goals and wishlist to review a request before sending.')
        self.view.status.set('Goal saved in ' + self.name + '. Find it in Journal or Ctrl+K.')

    def close(self):
        self.owner.goal_dialog = None
        self.root.destroy()
