"""Reviewed economy discussion using the existing explicit-send Journal workflow."""

from datetime import datetime, timedelta

from .activities import FLAVORS
from .economy import MODES, SCHEMA, prepare_economy
from .imports import CONTEXT_FILE_LIMIT, read_text
from .notebook_ui import DiscussionNotebook
from .chat import ChatError


class EconomyNotebook(DiscussionNotebook):
    kind, title = 'economy', 'Session economy analysis'
    # Five tabs need about 451 px in Classic; at 440 Tk squeezed them and cut their labels.
    minimum = (460, 480)
    prepare_form = staticmethod(prepare_economy)

    def make_fields(self):
        edition = next(key for key, value in FLAVORS.items() if value == self.view.profile['flavor'])
        self.field('edition', 'Export edition (your declaration)', edition, list(FLAVORS))
        self.field('mode', 'Review', MODES[0], list(MODES))
        self.field('profile', 'Private profile alias (avoid character or realm names)')
        self.field('scope', 'Filter scope alias (same filters for both periods)')
        self.field('question', 'Question or goal', 'Explain my incoming and outgoing cash and one way to work toward my goal.')
        tab = self.tab('Export setup')
        self.field('schema', 'Source format', SCHEMA, [SCHEMA], parent=tab)
        confirmed = self.tk.StringVar(master=self.root, value=self.initial.get('confirmed', 'Not checked'))
        self.fields['confirmed'] = confirmed
        confirmed.trace_add('write', lambda *_: self.changed())
        self.confirm_check = self.ttk.Checkbutton(
            tab, text='I checked versions, view, filters, and periods',
            variable=confirmed, onvalue='Checked', offvalue='Not checked',
        )
        self.confirm_check.pack(anchor='w', pady=(8, 4))
        help_text = self.label(tab, 'Use Journalator 171 with Auctionator 341, English Summary → By Type. '
                               'Confirm that both exports use your declared profile, edition, filters, and periods. '
                               'Amounts are raw copper. No automatic upload or transaction merge.')
        help_text.configure(wraplength=390, justify='left')
        help_text.pack(fill='x', pady=8)
        self.period_buttons = {}
        for prefix, title in (('', 'Current period'), ('previous_', 'Earlier period')):
            tab = self.tab(title)
            quick = self.frame(tab)
            quick.pack(fill='x', pady=(0, 4))
            self.label(quick, 'Quick fill:').pack(side='left', padx=(0, 4))
            today_btn = self.ttk.Button(quick, text='Today', style='Agent.TButton',
                                        command=lambda p=prefix: self.fill_period(p, days=0))
            today_btn.pack(side='left', padx=(0, 4))
            week_btn = self.ttk.Button(quick, text='Last 7 days', style='Agent.TButton',
                                       command=lambda p=prefix: self.fill_period(p, days=7))
            week_btn.pack(side='left')
            self.period_buttons[prefix] = (today_btn, week_btn)
            self.field(prefix + 'start', 'Period start (ISO timestamp with timezone)', parent=tab)
            self.field(prefix + 'end', 'Period end (ISO timestamp with timezone)', parent=tab)
            key = prefix + 'csv'
            self.editor(key, title, 'Paste one English Summary → By Type CSV. Dates are declared above; '
                        'they are absent from the export. Earlier evidence is used only in comparison mode.', parent=tab)
            self.ttk.Button(tab, text='Import CSV…', command=lambda field=key: self.import_csv(field)).pack(side='bottom')

    def fill_period(self, prefix, *, days):
        now = datetime.now().astimezone().replace(microsecond=0)
        if days == 0:
            start = now.replace(hour=0, minute=0, second=0)
            if start >= now:
                start = now - timedelta(hours=1)
        else:
            start = now - timedelta(days=days)
        self.fields[prefix + 'start'].set(start.isoformat())
        self.fields[prefix + 'end'].set(now.isoformat())

    def import_csv(self, field):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title='Import Journalator summary CSV',
                                          filetypes=[('CSV or text', '*.csv *.txt')])
        if not path:
            return
        try:
            body = read_text(path, CONTEXT_FILE_LIMIT)
        except ChatError as error:
            self.notice.set(str(error))
            return
        widget = self.editors[field]
        widget.delete('1.0', 'end'); widget.insert('1.0', body)
        self.fields['confirmed'].set('Not checked')
        self.changed()
