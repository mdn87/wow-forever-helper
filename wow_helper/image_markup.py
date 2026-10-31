"""Local image edits for the reviewed Screen adviser image; never sends a request."""

import math
from .chat import ChatError
from .screen_capture import saved_image, save_edited_image
from .theme import palette
from .window_frame import WindowFrame

MARKUP_MAX_PIXELS = 20_000_000
MAX_OPERATIONS = 20


def _apply(image, operation):
    from PIL import Image, ImageDraw

    kind, bounds = operation
    x1, y1, x2, y2 = bounds
    if kind == "crop":
        return image.crop((x1, y1, x2 + 1, y2 + 1))
    if kind == "mask":
        ImageDraw.Draw(image).rectangle((x1, y1, x2, y2), fill="#101010")
        return image
    if kind == "arrow":
        dx, dy = x2 - x1, y2 - y1
        if dx == dy == 0:
            return image
        angle = math.atan2(dy, dx)
        width = max(3, min(14, round(min(image.size) / 300)))
        head = max(12, min(54, round(min(image.size) / 24)))
        left = (x2 - head * math.cos(angle - math.pi / 6),
                y2 - head * math.sin(angle - math.pi / 6))
        right = (x2 - head * math.cos(angle + math.pi / 6),
                 y2 - head * math.sin(angle + math.pi / 6))
        draw = ImageDraw.Draw(image)
        draw.line((x1, y1, x2, y2), fill="#ff3030", width=width)
        draw.polygon(((x2, y2), left, right), fill="#ff3030")
        return image
    if kind == "magnify":
        margin = min(8, max(1, min(image.size) // 10))
        padding = 8
        region = image.crop((x1, y1, x2 + 1, y2 + 1))
        max_width = min(480, image.width - 2 * margin - padding)
        max_height = min(360, image.height - 2 * margin - padding)
        if min(max_width, max_height) < 2:
            raise ChatError("The image is too small for a magnified inset. The current preview is unchanged.")
        scale = min(2.0, max_width / region.width, max_height / region.height)
        if scale <= 1.0:
            raise ChatError("Select a smaller region to magnify. The current preview is unchanged.")
        inset_size = (max(1, round(region.width * scale)), max(1, round(region.height * scale)))
        inset = region.resize(inset_size, Image.Resampling.LANCZOS)
        framed = Image.new("RGB", (inset.width + padding, inset.height + padding), "#f4f4f4")
        framed.paste(inset, (padding // 2, padding // 2))
        draw = ImageDraw.Draw(framed)
        draw.rectangle((0, 0, framed.width - 1, framed.height - 1), outline="#111111", width=3)
        candidates = ((image.width - framed.width - margin, margin),
                      (margin, margin),
                      (image.width - framed.width - margin, image.height - framed.height - margin),
                      (margin, image.height - framed.height - margin))
        source = (x1, y1, x2, y2)
        place = None
        for px, py in candidates:
            box = (px, py, px + framed.width, py + framed.height)
            if (box[0] >= 0 and box[1] >= 0 and box[2] <= image.width and box[3] <= image.height
                    and (box[2] < source[0] or box[0] > source[2]
                         or box[3] < source[1] or box[1] > source[3])):
                place = (px, py)
                break
        if place is None:
            raise ChatError("No clear corner can fit the magnified inset. The current preview is unchanged.")
        image.paste(framed, place)
        return image
    raise ChatError("Choose crop, arrow, magnify, or mask before editing.")


class ImageMarkupDialog:
    """Make a new sanitized image from the current Screen adviser selection."""

    def __init__(self, view):
        import tkinter as tk
        from tkinter import ttk
        from PIL import Image, ImageTk

        self.view = view
        self.tk = tk
        self.ttk = ttk
        self.ImageTk = ImageTk
        self.source_name = view.image_name
        try:
            path = saved_image(view.activity.storage, self.source_name)
            with Image.open(path) as image:
                if image.width * image.height > MARKUP_MAX_PIXELS:
                    raise ChatError("Image markup supports images up to 20 megapixels. The original remains selected.")
                self.original = image.convert("RGB")
        except (OSError, ValueError, Image.DecompressionBombError):
            raise ChatError("The selected image could not be opened. The original remains selected.") from None
        self.current = self.original.copy()
        self.operations = []
        self.photo = None
        self.drag_start = None
        self.display_rect = (0, 0, 1, 1, 1.0)
        self.draw_after = None
        self.closed = False

        self.root = tk.Toplevel(view.root)
        self.root.withdraw()
        self.root.title("Edit reviewed image")
        parent = view.root.winfo_toplevel()
        self.root.transient(parent)
        self.root.geometry(f"820x740+{parent.winfo_x() + 30}+{parent.winfo_y() + 30}")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.bind("<Control-z>", lambda _event: self.undo())
        self.chrome = WindowFrame(self.root, title="Edit reviewed image", close=self.close, minimum=(640, 520))
        surface = self.chrome.content
        colors = palette(self.root)
        tk.Label(surface, text="Edits stay local until you save a new copy. The source image is preserved.",
                 bg=colors.BACKGROUND, fg=colors.MUTED, anchor="w", wraplength=760).pack(fill="x", padx=12, pady=(10, 6))

        toolbar = tk.Frame(surface, bg=colors.BACKGROUND, padx=8, pady=5)
        toolbar.pack(fill="x")
        self.mode = tk.StringVar(master=self.root, value="arrow")
        for value, label in (("crop", "Crop"), ("arrow", "Arrow"), ("magnify", "Magnify"), ("mask", "Mask")):
            ttk.Radiobutton(toolbar, text=label, value=value, variable=self.mode).pack(side="left", padx=(0, 5))
        ttk.Button(toolbar, text="Undo", command=self.undo).pack(side="right", padx=(5, 0))
        ttk.Button(toolbar, text="Reset edits", command=self.reset).pack(side="right", padx=(5, 0))

        self.canvas = tk.Canvas(surface, bg="#202020", highlightthickness=1, highlightbackground=colors.EDGE,
                                cursor="crosshair")
        self.canvas.pack(fill="both", expand=True, padx=10, pady=5)
        self.canvas.bind("<Configure>", self.queue_draw)
        self.canvas.bind("<ButtonPress-1>", self.begin)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.end)

        footer = tk.Frame(surface, bg=colors.BACKGROUND, padx=8, pady=7)
        footer.pack(fill="x")
        self.notice = tk.StringVar(master=self.root, value="Select a tool, then drag over the preview. Masked pixels are flattened to solid dark pixels.")
        tk.Label(footer, textvariable=self.notice, bg=colors.BACKGROUND, fg=colors.MUTED,
                 anchor="w", justify="left", wraplength=520).pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="Save edited copy", command=self.save).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Cancel", command=self.close).pack(side="right")
        self.root.deiconify()
        self.chrome.apply_native()
        self.queue_draw()

    def queue_draw(self, _event=None):
        if self.draw_after is not None:
            self.root.after_cancel(self.draw_after)
        self.draw_after = self.root.after(60, self.draw)

    def draw(self):
        from PIL import Image

        self.draw_after = None
        if self.closed or not self.canvas.winfo_exists():
            return
        width, height = max(1, self.canvas.winfo_width() - 16), max(1, self.canvas.winfo_height() - 16)
        scale = min(width / self.current.width, height / self.current.height, 1.0)
        display_size = (max(1, round(self.current.width * scale)), max(1, round(self.current.height * scale)))
        display = self.current.resize(display_size, Image.Resampling.LANCZOS) if display_size != self.current.size else self.current
        self.photo = self.ImageTk.PhotoImage(display, master=self.root)
        left = (self.canvas.winfo_width() - display_size[0]) // 2
        top = (self.canvas.winfo_height() - display_size[1]) // 2
        self.display_rect = (left, top, display_size[0], display_size[1], scale)
        self.canvas.delete("all")
        self.canvas.create_image(left, top, image=self.photo, anchor="nw", tags="preview")

    def point(self, event):
        left, top, width, height, scale = self.display_rect
        if scale <= 0 or not (left <= event.x < left + width and top <= event.y < top + height):
            return None
        x = min(self.current.width - 1, max(0, round((event.x - left) / scale)))
        y = min(self.current.height - 1, max(0, round((event.y - top) / scale)))
        return x, y

    def begin(self, event):
        self.drag_start = self.point(event)

    def drag(self, event):
        if self.drag_start is None:
            return
        end = self.point(event)
        if end is None:
            return
        left, top, _width, _height, scale = self.display_rect
        x1 = left + round(self.drag_start[0] * scale)
        y1 = top + round(self.drag_start[1] * scale)
        x2 = left + round(end[0] * scale)
        y2 = top + round(end[1] * scale)
        self.canvas.delete("selection")
        if self.mode.get() == "arrow":
            self.canvas.create_line(x1, y1, x2, y2, fill="#ff3030", width=3, arrow="last", tags="selection")
        else:
            fill = "#f0f0f0" if self.mode.get() == "mask" else ""
            stipple = "gray50" if fill else ""
            self.canvas.create_rectangle(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2),
                                         outline="#f0f0f0", width=2, fill=fill, stipple=stipple,
                                         tags="selection")

    def end(self, event):
        if self.drag_start is None:
            return
        start, self.drag_start = self.drag_start, None
        finish = self.point(event)
        if finish is None:
            self.canvas.delete("selection")
            return
        bounds = (min(start[0], finish[0]), min(start[1], finish[1]),
                  max(start[0], finish[0]), max(start[1], finish[1]))
        if self.mode.get() == "arrow":
            bounds = (start[0], start[1], finish[0], finish[1])
        if self.mode.get() != "arrow" and (bounds[2] - bounds[0] < 2 or bounds[3] - bounds[1] < 2):
            self.notice.set("Drag a larger region; no edit was applied.")
            self.canvas.delete("selection")
            return
        if self.mode.get() == "mask" and any(kind == "magnify" for kind, _region in self.operations):
            self.notice.set("Undo Magnify edits before masking so enlarged copies cannot retain unmasked pixels.")
            self.canvas.delete("selection")
            return
        if len(self.operations) >= MAX_OPERATIONS:
            self.notice.set(f"This edit has reached the {MAX_OPERATIONS}-operation limit. Save a copy or reset the edits.")
            self.canvas.delete("selection")
            return
        operation = (self.mode.get(), bounds)
        try:
            result = _apply(self.current.copy(), operation)
        except ChatError as error:
            self.notice.set(str(error))
            self.canvas.delete("selection")
            return
        except (OSError, ValueError, MemoryError):
            self.notice.set("That edit could not be applied. The current preview is unchanged.")
            self.canvas.delete("selection")
            return
        self.operations.append(operation)
        self.current = result
        self.notice.set(f"{self.mode.get().title()} applied locally. Undo or reset before saving if needed.")
        self.draw()

    def undo(self):
        if not self.operations:
            return "break"
        self.operations.pop()
        self.rebuild()
        self.notice.set("Last edit undone. The source image is unchanged.")
        return "break"

    def reset(self):
        self.operations.clear()
        self.current = self.original.copy()
        self.notice.set("Edits reset. The source image is unchanged.")
        self.draw()

    def rebuild(self):
        current = self.original.copy()
        for operation in self.operations:
            current = _apply(current, operation)
        self.current = current
        self.draw()

    def save(self):
        try:
            name = save_edited_image(self.view.activity.storage, self.current)
        except ChatError as error:
            self.notice.set(str(error))
            return
        self.view._image_result(name, None)
        self.view.activity_notice.set("Edited image selected for review. The original remains saved; no request was sent.")
        self.view.record_usage("screen", "markup")
        self.close()

    def close(self):
        self.closed = True
        if self.draw_after is not None:
            self.root.after_cancel(self.draw_after)
            self.draw_after = None
        if getattr(self.view, "_markup_dialog", None) is self:
            self.view._markup_dialog = None
        self.root.destroy()
