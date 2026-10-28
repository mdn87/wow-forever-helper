"""Reviewed, explicitly sent discussions and durable experiment notes."""

from copy import deepcopy
import json
import uuid

from .activities import FLAVORS, packet_preview
from .build_tutor import prepare_build
from .chat import ChatError
from .imports import read_text
from .journal import metadata
from .journal_ui import JournalDialog


def notebook_drafts(raw):
    if not isinstance(raw, dict):
        return {}
    return {k: {f: v for f, v in form.items() if isinstance(f, str) and isinstance(v, str)
                and len(f) <= 40 and len(v.encode('utf-8', errors='replace')) <= 64_000}
            for k, form in raw.items() if k in {'build', 'route', 'addon'} and isinstance(form, dict)
            and len(form) <= 20}


class DiscussionNotebook(JournalDialog):
    kind, title = 'build', 'Build tutor and experiment notebook'
    prepare_form = staticmethod(prepare_build)

    def __init__(self, view):
        self.packet = self.reviewed_form = self.source = None
        self.attempted = False
        self.fields, self.editors = {}, {}
        self.initial = view.notebook_drafts.get(self.kind, {})
        super().__init__(view, self.title)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.book = self.ttk.Notebook(self.surface)
        self.book.pack(fill='both', expand=True, padx=8)
        self.inputs = self.tab('Inputs')
        self.make_fields()
        self.review_tab = self.tab('Review')
        self.preview = self.text(self.review_tab, 'Prepare a review to see exactly what will be saved or sent.')
        self.prepare_button = self.ttk.Button(self.actions, text='Prepare review', command=self.prepare)
        self.prepare_button.pack(side='left')
        self.save_button = self.ttk.Button(self.actions, text='Save note', command=self.save, state='disabled')
        self.save_button.pack(side='left', padx=4)
        self.send_button = self.ttk.Button(self.actions, text='Send', command=self.send, state='disabled')
        self.send_button.pack(side='left')
        self.notice.set('Review imports before sending. Save note keeps reviewed evidence in Journal even when chat retention is off.')
        self.show()

    def tab(self, title):
        tab = self.frame(self.book, padding=8)
        self.book.add(tab, text=title)
        return tab

    def field(self, key, label, default='', choices=None, parent=None):
        parent = parent or self.inputs
        self.label(parent, label).pack(anchor='w', pady=(5, 0))
        variable = self.tk.StringVar(master=self.root, value=self.initial.get(key, default))
        widget = (self.ttk.Combobox(parent, textvariable=variable, values=choices, state='readonly')
                  if choices else self.ttk.Entry(parent, textvariable=variable))
        widget.pack(fill='x')
        self.fields[key] = variable
        variable.trace_add('write', lambda *_: self.changed())
        return variable

    def editor(self, key, title, help_text, parent=None):
        tab = parent or self.tab(title)
        label = self.label(tab, help_text)
        label.configure(wraplength=390, justify='left')
        label.pack(anchor='w')
        widget = self.text(tab, self.initial.get(key, ''), editable=True)
        widget.edit_modified(False)
        self.editors[key] = widget
        widget.bind('<<Modified>>', lambda _: self.modified(widget))
        return tab

    def make_fields(self):
        edition = next(k for k, v in FLAVORS.items() if v == self.view.profile['flavor'])
        self.field('edition', 'Game edition', edition, list(FLAVORS))
        self.field('format', 'Import format', 'Build notes', ['Build notes', 'SimulationCraft profile'])
        self.field('role', 'Role')
        self.field('preferences', 'Preferences')
        self.field('question', 'Comparison question')
        tab = self.editor('profile', 'Profile', 'Editable profile or notes; remove details you do not want sent.')
        self.ttk.Button(tab, text='Import text file…', command=lambda: self.import_text('profile', 64_000)).pack(side='bottom')
        tab = self.tab('Report')
        self.field('engine', 'Report engine and version (if known)', parent=tab)
        self.field('report_edition', 'Existing report edition', edition, list(FLAVORS), parent=tab)
        self.editor('report', 'Report', 'Optional existing report excerpt; plain text only, up to 8,000 bytes.', parent=tab)
        self.ttk.Button(tab, text='Import report excerpt…', command=lambda: self.import_text('report', 8000)).pack(side='bottom')

    def form(self):
        return {**{k: v.get() for k, v in self.fields.items()},
                **{k: v.get('1.0', 'end-1c') for k, v in self.editors.items()}}

    def modified(self, widget):
        if widget.edit_modified():
            widget.edit_modified(False)
            self.changed()

    def changed(self):
        form = self.form()
        if any(len(v.encode('utf-8', errors='replace')) > 64_000 for v in form.values()):
            self.notice.set('This draft is too large to remember. Reduce it before closing; the prior draft is kept.')
        else:
            self.view.notebook_drafts[self.kind] = form
            self.view.on_change()
        if self.packet is not None and form != self.reviewed_form:
            self.save_button.configure(state='disabled')
            self.send_button.configure(state='disabled')
            self.notice.set('Inputs changed. Prepare a fresh review before saving or sending.')

    def import_text(self, field, limit):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title='Import readable UTF-8 text',
                                          filetypes=[('Text or SimulationCraft profile', '*.txt *.simc')])
        if not path:
            return
        try:
            body = read_text(path, limit)
        except ChatError as error:
            self.notice.set(str(error))
            return
        widget = self.editors[field]
        widget.delete('1.0', 'end'); widget.insert('1.0', body)
        self.changed()

    def evidence(self, packet):
        return {'text': json.dumps({k: v for k, v in packet.items() if k != 'image'}, ensure_ascii=False, indent=2),
                'edition': packet['edition'], 'prepared_at': packet['prepared_at'],
                'gaps': ['User-provided evidence; source availability and capture time are unverified.']}

    def prepare(self):
        from .task_window import replace_text
        self.packet = None
        self.save_button.configure(state='disabled'); self.send_button.configure(state='disabled')
        try:
            form = self.form()
            packet = self.prepare_form(form)
            evidence = self.evidence(packet)
            metadata(evidence=evidence)
        except ChatError as error:
            self.notice.set(str(error))
            return
        self.packet, self.reviewed_form = packet, deepcopy(form)
        self.note_id, self.request_id = str(uuid.uuid4()), str(uuid.uuid4())
        self.session_key = self.view.selection_key
        self.source = ({'provider': self.session_key[0], 'session_id': self.session_key[1]}
                       if self.session_key else None)
        self.attempted = False
        destination = self.view.session_title if self.session_key else 'No conversation selected; saving is available offline'
        replace_text(self.preview, 'DESTINATION\n' + destination + '\n\n' + packet_preview(packet))
        self.book.select(self.review_tab)
        self.save_button.configure(state='normal')
        self.send_button.configure(state='normal' if self.session_key else 'disabled')
        self.notice.set('Review the full evidence. Send uses the selected conversation and preserves its draft.')
        self.changed()

    def valid_review(self):
        if self.packet is None or self.form() != self.reviewed_form:
            self.notice.set('Inputs changed or no review exists. Prepare a fresh review first.')
            return False
        return True

    def save(self):
        if not self.valid_review():
            return
        try:
            self.view.activity.add_note(self.view.journal_id, self.title[:80], self.packet['task'], self.note_id,
                                        source=self.source, evidence=self.evidence(self.packet),
                                        next_time={'text': self.packet['task'], 'state': 'open'})
            self.notice.set('Saved in this window’s Journal. Resume session or Ctrl+K can reopen its source conversation.')
        except (ChatError, OSError) as error:
            self.notice.set(str(error) if isinstance(error, ChatError) else 'The note could not be saved. Your review is kept.')

    def send(self):
        if not self.valid_review() or self.attempted:
            return
        if self.view.selection_key != self.session_key or not self.session_key:
            self.notice.set('The selected conversation changed. Prepare a fresh review first.')
            return
        if self.view.send_prepared(self.packet, self.session_key, self.request_id):
            self.attempted = True
            self.send_button.configure(state='disabled')
            self.notice.set('Request attempted once. Read the conversation for delivery and reply status; Save note remains available.')
        else:
            self.notice.set(self.view.activity_notice.get())

    def close(self):
        self.changed()
        self.view._notebooks.pop(self.kind, None)
        self.root.destroy()
