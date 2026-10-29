"""Explicit region preview, live comparison result review, and Journal saving."""

import time

from .activities import FLAVORS
from .chat import ChatError
from .comparison_shortcut import ComparisonShortcut
from .journal_ui import JournalDialog, SaveAdviceDialog
from .live_gear import LiveGear, journal_selection, rendered
from .screen_capture import capture_game, crop_region, saved_image
from .task_window import replace_text


class GearDialog(JournalDialog):
    def __init__(self, view, *, engine_factory=LiveGear, key_factory=ComparisonShortcut,
                 capture=capture_game):
        self.key_factory, self.capture = key_factory, capture
        self.key = self.future = self.source_image = self.preview_photo = self.review_photo = None
        self.preview_name = self.preview_flavor = self.region = self.reviewed = None
        self.last_record = None
        self.after = None
        self.closed = False
        super().__init__(view, 'Live gear comparison')
        self.engine = engine_factory(view.activity.storage, view.service.agents,
                                     target=lambda: (view.selection_key, view.selection_revision))
        self.edition = self.tk.StringVar(master=self.root, value=next(k for k, v in FLAVORS.items() if v == view.profile['flavor']))
        self.build = self.tk.StringVar(master=self.root)
        self.goal = self.tk.StringVar(master=self.root, value='Explain the tradeoffs')
        self.book = self.ttk.Notebook(self.surface)
        self.book.pack(fill='both', expand=True, padx=8)
        self.setup = self.frame(self.book, padding=8)
        self.review = self.frame(self.book, padding=8)
        self.result = self.frame(self.book, padding=8)
        self.evidence_tab = self.frame(self.book, padding=8)
        for tab, title in ((self.setup, 'Setup'), (self.review, 'Review region'), (self.result, 'Result'),
                           (self.evidence_tab, 'Captured evidence')):
            self.book.add(tab, text=title)
        for label, variable, choices in [('Game edition', self.edition, list(FLAVORS)),
                                          ('Build / role', self.build, None), ('Comparison goal', self.goal, None)]:
            self.label(self.setup, label).pack(anchor='w')
            widget = (self.ttk.Combobox(self.setup, textvariable=variable, values=choices, state='readonly')
                      if choices else self.ttk.Entry(self.setup, textvariable=variable))
            widget.pack(fill='x', pady=(0, 4))
        self.label(self.setup, 'Capture a preview, then drag around where both tooltips appear.').pack(anchor='w')
        self.canvas = self.tk.Canvas(self.setup, height=250, highlightthickness=0, background='#101722')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda _: self.draw_preview())
        self.canvas.bind('<ButtonPress-1>', self.drag_start)
        self.canvas.bind('<B1-Motion>', self.drag_move)
        self.canvas.bind('<ButtonRelease-1>', self.drag_end)
        self.destination = self.label(self.review, '')
        self.destination.configure(wraplength=420, justify='left')
        self.destination.pack(fill='x', pady=8)
        self.review_label = self.label(self.review, 'Select and review a region first.')
        self.review_label.pack(fill='both', expand=True)
        self.progress = self.tk.StringVar(master=self.root)
        self.progress_label = self.label(self.result, '')
        self.progress_label.configure(textvariable=self.progress, wraplength=400, justify='left')
        self.progress_label.pack(fill='x')
        self.output = self.text(self.result, 'No comparison requested yet.')
        self.evidence_label = self.label(self.evidence_tab, 'The next requested capture will appear here.')
        self.evidence_label.pack(fill='both', expand=True)
        self.evidence_photo = None
        self.evidence_name = None
        self.commands = self.frame(self.actions)
        self.commands.pack(side='left', fill='x', expand=True)
        self.preview_button = self.ttk.Button(self.commands, text='Capture preview', command=self.preview)
        self.review_button = self.ttk.Button(self.commands, text='Review region', command=self.review_region)
        self.enable_button = self.ttk.Button(self.commands, text='Enable shortcut', command=self.enable, state='disabled')
        self.disable_button = self.ttk.Button(self.commands, text='Disable', command=self.disable)
        self.save_button = self.ttk.Button(self.commands, text='Save to Journal', command=self.save, state='disabled')
        for button, row, column in [(self.preview_button, 0, 0), (self.review_button, 0, 1),
                                    (self.enable_button, 1, 0), (self.disable_button, 1, 1), (self.save_button, 2, 0)]:
            button.grid(row=row, column=column, sticky='ew', padx=2, pady=2)
        for variable in (self.edition, self.build, self.goal):
            variable.trace_add('write', lambda *_: self.changed())
        self.notice.set('Choose a companion-created chat. Review what the region includes before enabling Ctrl+Alt+F9. Voice stays input-only.')
        self.show()
        self.after = self.root.after(50, self.poll)

    def form(self):
        return (self.edition.get(), self.build.get(), self.goal.get(), self.view.selection_key,
                self.view.selection_revision, tuple(self.region) if self.region else None, self.preview_name)

    def changed(self):
        self.disable()
        self.reviewed = None
        self.enable_button.configure(state='disabled')
        self.notice.set('Settings changed. Review the region and destination again before enabling.')

    def disable(self):
        self.engine.disable()
        if self.key:
            self.key.close()
            self.key = None
        if hasattr(self, 'notice'):
            self.notice.set('Shortcut disabled. A request already sent may finish in its original conversation.')

    def preview(self):
        if self.future or self.engine.busy:
            self.notice.set('Wait for the current operation to finish.'); return
        self.changed()
        flavor = FLAVORS[self.edition.get()]
        self.preview_flavor = flavor
        self.future = self.view.worker.submit(self.capture, self.view.activity.storage, flavor)
        self.notice.set('Capturing a fresh WoW preview locally. Nothing is being sent.')

    def load_preview(self, name):
        from PIL import Image
        with Image.open(saved_image(self.view.activity.storage, name)) as image:
            if image.width * image.height > 40_000_000:
                raise ChatError('The preview is too large.')
            self.source_image = image.copy()
        self.preview_name = name
        self.region = None
        self.draw_preview()
        self.notice.set('Drag a region containing the candidate and Equipped tooltips, then Review region.')

    def draw_preview(self):
        if self.source_image is None or self.closed:
            return
        from PIL import ImageTk
        image = self.source_image.copy()
        image.thumbnail((max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())))
        self.scale_x = image.width / self.source_image.width
        self.scale_y = image.height / self.source_image.height
        self.preview_photo = ImageTk.PhotoImage(image, master=self.root)
        self.canvas.delete('all')
        self.canvas.create_image(0, 0, image=self.preview_photo, anchor='nw')
        if self.region:
            x, y, width, height = self.region
            self.canvas.create_rectangle(x*self.scale_x, y*self.scale_y, (x+width)*self.scale_x,
                                         (y+height)*self.scale_y, outline='#58c8ff', width=2, tags='region')

    def point(self, event):
        return (max(0, min(self.source_image.width, round(event.x / self.scale_x))),
                max(0, min(self.source_image.height, round(event.y / self.scale_y))))

    def drag_start(self, event):
        if self.source_image is not None and not self.engine.busy:
            self.changed()
            self.anchor = self.point(event)

    def drag_move(self, event):
        if not hasattr(self, 'anchor'):
            return
        x, y = self.point(event)
        ax, ay = self.anchor
        self.region = [min(x, ax), min(y, ay), abs(x-ax), abs(y-ay)]
        self.draw_preview()

    def drag_end(self, event):
        self.drag_move(event)
        if hasattr(self, 'anchor'):
            del self.anchor

    def review_region(self):
        from PIL import ImageTk
        try:
            if self.source_image is None or self.preview_flavor != FLAVORS[self.edition.get()]:
                raise ChatError('Capture a new preview for the selected edition first.')
            image = crop_region(self.source_image, self.region, list(self.source_image.size))
            session = self.view.selected
            if not session or not session.managed:
                raise ChatError('Start or select a companion-created Codex or Claude conversation first.')
            image.thumbnail((max(300, self.root.winfo_width()-40), max(200, self.root.winfo_height()-230)))
            self.review_photo = ImageTk.PhotoImage(image, master=self.root)
            self.review_label.configure(image=self.review_photo, text='')
            self.destination.configure(text=f'Destination: {session.provider.title()} · {session.title}\n'
                                       'Each explicit shortcut sends this region from a fresh game frame. '
                                       'Exclude names or chat you do not want shared. Requires image-reading support.')
            self.reviewed = self.form()
            self.enable_button.configure(state='normal')
            self.book.select(self.review)
            self.notice.set('Review the exact region and destination. Enable shortcut approves future explicit captures for this setup only.')
        except (ChatError, OSError, ValueError) as error:
            self.notice.set(str(error) if isinstance(error, ChatError) else 'The preview could not be read. Capture another.')

    def enable(self):
        try:
            if self.reviewed != self.form():
                raise ChatError('Settings changed. Review the region again.')
            self.engine.approve(self.view.selected, self.view.selection_revision, FLAVORS[self.edition.get()],
                                self.preview_name, self.region, self.build.get(), self.goal.get())
            if self.key:
                self.key.close()
            self.key = self.key_factory()
            if not self.key.available:
                self.disable()
                raise ChatError('Ctrl+Alt+F9 or its Shift variant is in use. Disable it in the other comparison window before enabling here.')
            self.notice.set('Enabled: in WoW, show both tooltips and press Ctrl+Alt+F9 (Shift may stay held). One request at a time; no automatic retries.')
        except (ChatError, OSError, ValueError) as error:
            self.notice.set(str(error) if isinstance(error, ChatError) else 'The setup could not be enabled. Review a new preview.')

    def poll(self):
        if self.after:
            self.root.after_cancel(self.after)
        self.after = None
        if self.closed:
            return
        if self.reviewed is not None and self.reviewed != self.form():
            self.changed()
        if self.future and self.future.done():
            future, self.future = self.future, None
            try:
                self.load_preview(future.result())
            except Exception as error:
                self.notice.set(str(error) if isinstance(error, ChatError) else 'Preview capture failed. It was not retried.')
        if self.key and self.key.requested():
            try:
                self.engine.begin()
            except ChatError as error:
                self.notice.set(str(error))
        record = self.engine.snapshot()
        if record and record != self.last_record:
            self.last_record = record
            replace_text(self.output, rendered(record) or 'Capturing and reading the requested tooltips…')
            self.save_button.configure(state='normal' if record.get('state') == 'completed' else 'disabled')
            if record.get('image') and record['image'] != self.evidence_name:
                try:
                    from PIL import Image, ImageTk
                    with Image.open(saved_image(self.view.activity.storage, record['image'])) as image:
                        image.thumbnail((max(300, self.root.winfo_width()-40), max(200, self.root.winfo_height()-220)))
                        self.evidence_photo = ImageTk.PhotoImage(image, master=self.root)
                    self.evidence_label.configure(image=self.evidence_photo, text='')
                    self.evidence_name = record['image']
                except (ChatError, OSError, ValueError):
                    self.evidence_label.configure(text='The captured evidence image is unavailable.', image='')
        if record:
            age = max(0, int(time.time() - record.get('captured_at', record['requested_at'])))
            times = ', '.join(f'{name} {value:.1f}s' for name, value in record['timings'].items())
            status = {'capturing': 'Capturing', 'extracting': 'Reading tooltips', 'explaining': 'Explaining tradeoffs',
                      'completed': 'Comparison complete — review Result', 'failed': record.get('error', 'Comparison failed')}
            enabled = 'Shortcut enabled' if self.key and self.key.available else 'Shortcut disabled'
            self.progress.set(f"{enabled} · {status.get(record['state'], record['state'])} · capture age {age}s" + (f' · {times}' if times else ''))
        self.after = self.root.after(100, self.poll)

    def save(self):
        try:
            selection = journal_selection(self.engine.snapshot())
            if self.view._journal_dialog:
                self.view._journal_dialog.root.lift()
            else:
                self.view._journal_dialog = SaveAdviceDialog(self.view, selection)
        except ChatError as error:
            self.notice.set(str(error))

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.disable()
        if self.after:
            self.root.after_cancel(self.after)
        self.view._gear_dialog = None
        self.preview_photo = self.review_photo = self.evidence_photo = self.source_image = None
        self.root.destroy()
