"""Reviewed economy discussion using the existing explicit-send Journal workflow."""

from .activities import FLAVORS
from .economy import MODES, SCHEMA, prepare_economy
from .imports import CONTEXT_FILE_LIMIT, read_text
from .notebook_ui import DiscussionNotebook
from .chat import ChatError


class EconomyNotebook(DiscussionNotebook):
    kind, title = 'economy', 'Session economy analysis'
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
        self.field('confirmed', 'I checked versions, view, filters, and periods',
                   'Not checked', ['Not checked', 'Checked'], parent=tab)
        help_text = self.label(tab, 'Use Journalator 171 with Auctionator 341, English Summary → By Type. '
                               'Confirm that both exports use your declared profile, edition, filters, and periods. '
                               'Amounts are raw copper. No automatic upload or transaction merge.')
        help_text.configure(wraplength=390, justify='left')
        help_text.pack(fill='x', pady=8)
        for prefix, title in (('', 'Current period'), ('previous_', 'Earlier period')):
            tab = self.tab(title)
            self.field(prefix + 'start', 'Period start (ISO timestamp with timezone)', parent=tab)
            self.field(prefix + 'end', 'Period end (ISO timestamp with timezone)', parent=tab)
            key = prefix + 'csv'
            self.editor(key, title, 'Paste one English Summary → By Type CSV. Dates are declared above; '
                        'they are absent from the export. Earlier evidence is used only in comparison mode.', parent=tab)
            self.ttk.Button(tab, text='Import CSV…', command=lambda field=key: self.import_csv(field)).pack(side='bottom')

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
