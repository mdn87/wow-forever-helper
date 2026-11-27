"""Button rows that wrap onto another line instead of running past a narrow window's edge."""


class FlowRow:
    """Place widgets left to right in ``frame`` and start a new line when the next one won't fit.

    The widgets must be children of ``frame``. The frame's height follows the number of lines,
    so a window at its minimum width keeps every button whole instead of cutting the last ones.
    """

    def __init__(self, frame, *, gap=4, line_gap=3):
        self.frame, self.gap, self.line_gap = frame, gap, line_gap
        self.widgets, self.hidden = [], set()
        frame.bind("<Configure>", self.layout, add="+")

    def add(self, widget, *, visible=True):
        self.widgets.append(widget)
        if not visible:
            self.hidden.add(widget)
        # A theme or font change resizes the widget without resizing the frame.
        widget.bind("<Configure>", self.layout, add="+")
        self.layout()
        return widget

    def show(self, widget, visible=True):
        if visible:
            self.hidden.discard(widget)
        else:
            self.hidden.add(widget)
        self.layout()

    def layout(self, _event=None):
        frame = self.frame
        if not frame.winfo_exists():
            return
        # place() positions inside the frame's padding; the frame's height must include it.
        pad_x, pad_y = int(str(frame.cget("padx"))), int(str(frame.cget("pady")))
        shown = [widget for widget in self.widgets if widget not in self.hidden]
        width = frame.winfo_width() - 2 * pad_x
        if frame.winfo_width() <= 1:  # not laid out yet: one line until the first resize
            width = sum(widget.winfo_reqwidth() + self.gap for widget in shown)
        x = y = line = 0
        for widget in self.widgets:
            if widget in self.hidden:
                widget.place_forget()
                continue
            needed, height = widget.winfo_reqwidth(), widget.winfo_reqheight()
            if x and x + needed > width:
                x, y, line = 0, y + line + self.line_gap, 0
            widget.place(x=x, y=y)
            x += needed + self.gap
            line = max(line, height)
        height = y + line + 2 * pad_y
        if int(str(frame.cget("height"))) != height:
            frame.configure(height=height)
