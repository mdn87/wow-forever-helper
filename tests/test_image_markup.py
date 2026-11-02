"""F10 screenshot markup checks with synthetic images only; nothing is sent.

Every source image here is generated in code. Each pixel encodes its own
coordinates so crop mapping can be verified exactly, and no pixel equals the
solid mask colour, so mask coverage is unambiguous.
"""

import hashlib
import math
import socket
import uuid

import pytest
from PIL import Image, ImageChops, PngImagePlugin

from test_workspace import choose, manager_factory, settle  # noqa: F401 (fixture)
from wow_helper import image_markup, screen_capture
from wow_helper.chat import ChatError
from wow_helper.image_markup import MARKUP_MAX_PIXELS, MAX_OPERATIONS, _apply
from wow_helper.screen_capture import import_image, save_edited_image
from wow_helper.theme import PALETTES

MASK = (16, 16, 16)
SECRET = "SyntheticSecretMarker"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- helpers

def coded_image(width, height):
    """R/G hold x/y low bytes; B holds the high bytes offset to 64..143."""
    assert width <= 2560 and height <= 2048
    red = Image.frombytes("L", (width, 1), bytes(x % 256 for x in range(width))).resize((width, height), Image.Resampling.NEAREST)
    green = Image.frombytes("L", (1, height), bytes(y % 256 for y in range(height))).resize((width, height), Image.Resampling.NEAREST)
    high_x = Image.frombytes("L", (width, 1), bytes((x // 256) * 8 for x in range(width))).resize((width, height), Image.Resampling.NEAREST)
    high_y = Image.frombytes("L", (1, height), bytes(y // 256 for y in range(height))).resize((width, height), Image.Resampling.NEAREST)
    blue = ImageChops.add(high_x, high_y, scale=1.0, offset=64)
    return Image.merge("RGB", (red, green, blue))


def decode(pixel):
    r, g, b = pixel
    high = b - 64
    return r + 256 * (high // 8), g + 256 * (high % 8)


def save_with_metadata(image, path):
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", SECRET)
    info.add_text("Software", SECRET, zip=True)
    info.add_itxt("Author", SECRET, lang="en", tkey="Author")
    exif = Image.Exif()
    exif[0x010E] = SECRET  # ImageDescription
    exif[0x013B] = SECRET  # Artist
    image.save(path, format="PNG", pnginfo=info, exif=exif, dpi=(300, 300))


def chunk_types(path):
    data = path.read_bytes()
    assert data[:8] == PNG_SIGNATURE
    position, types = 8, []
    while position < len(data):
        length = int.from_bytes(data[position:position + 4], "big")
        types.append(data[position + 4:position + 8])
        position += 12 + length
    return types


def assert_metadata_free(path):
    assert set(chunk_types(path)) <= {b"IHDR", b"IDAT", b"IEND"}
    assert SECRET.encode() not in path.read_bytes()
    with Image.open(path) as image:
        assert not image.text
        assert not image.getexif()
        assert "exif" not in image.info and "dpi" not in image.info


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_masked(image, bounds):
    x1, y1, x2, y2 = bounds
    region = image.crop((x1, y1, x2 + 1, y2 + 1))
    assert region.getextrema() == ((16, 16), (16, 16), (16, 16))


class Pointer:
    def __init__(self, x, y):
        self.x, self.y = x, y


def to_display(dialog, x, y):
    left, top, _width, _height, scale = dialog.display_rect
    return Pointer(left + round(x * scale), top + round(y * scale))


def drag(dialog, mode, start, finish):
    dialog.mode.set(mode)
    dialog.begin(to_display(dialog, *start))
    dialog.drag(to_display(dialog, *finish))
    dialog.end(to_display(dialog, *finish))


@pytest.fixture
def no_network(monkeypatch):
    attempts = []

    def refuse(*args, **_kwargs):
        attempts.append(args)
        raise AssertionError("markup attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    return attempts


@pytest.fixture
def editor(manager_factory):
    def open_editor(image, *, theme=None, metadata=True):
        manager = manager_factory()
        if theme:
            manager.preview_interface({"theme": theme})
        window = manager.new_window(kind="screen")
        view = window.view
        settle(view)
        folder = view.activity.storage / "captures"
        folder.mkdir(parents=True, exist_ok=True)
        name = str(uuid.uuid4()) + ".png"
        if metadata:
            save_with_metadata(image, folder / name)
        else:
            image.save(folder / name)
        view._image_result(name, None)
        view.edit_image()
        dialog = view._markup_dialog
        assert dialog is not None, view.activity_notice.get()
        manager.root.update()
        dialog.draw()
        return manager, window, view, dialog, folder / name

    return open_editor


# ------------------------------------------------- pure pixel operations

def test_mask_fills_inclusive_bounds_with_solid_pixels_only():
    source = coded_image(120, 90)
    result = _apply(source.copy(), ("mask", (10, 20, 29, 39)))
    assert_masked(result, (10, 20, 29, 39))
    for x, y in ((9, 20), (30, 20), (10, 19), (10, 40), (0, 0), (119, 89)):
        assert decode(result.getpixel((x, y))) == (x, y)


def test_crop_keeps_inclusive_source_coordinates():
    result = _apply(coded_image(300, 280), ("crop", (40, 260, 299, 279)))
    assert result.size == (260, 20)
    assert decode(result.getpixel((0, 0))) == (40, 260)
    assert decode(result.getpixel((259, 19))) == (299, 279)


def test_magnify_duplicates_source_pixels_which_is_why_masking_needs_it_undone():
    source = coded_image(400, 300)
    result = _apply(source.copy(), ("magnify", (20, 200, 60, 240)))
    original = {decode(source.getpixel((x, y))) for x in range(20, 61) for y in range(200, 241)}
    elsewhere = {result.getpixel((x, y)) for x in range(100, 400) for y in range(0, 150)}
    # The inset is a second, enlarged copy of the selected pixels far from the source.
    assert any(pixel[2] >= 64 and decode(pixel) in original for pixel in elsewhere)


@pytest.mark.parametrize("operation", [("magnify", (0, 0, 9, 9)), ("magnify", (0, 0, 199, 149))])
def test_magnify_refuses_when_no_clear_inset_fits(operation):
    with pytest.raises(ChatError, match="unchanged"):
        _apply(coded_image(20, 20) if operation[1][2] == 9 else coded_image(200, 150), operation)


def test_unknown_operation_is_refused():
    with pytest.raises(ChatError, match="Choose crop"):
        _apply(coded_image(10, 10), ("blur", (0, 0, 5, 5)))


# ------------------------------------------------ saving derived copies

def test_saved_copy_is_new_metadata_free_png_with_exact_mask(tmp_path):
    source = tmp_path / "captures" / "source.png"
    source.parent.mkdir()
    save_with_metadata(coded_image(200, 150), source)
    assert {b"tEXt", b"zTXt", b"iTXt", b"eXIf"} <= set(chunk_types(source))  # precondition
    before = digest(source)
    with Image.open(source) as image:
        edited = _apply(image.convert("RGB"), ("mask", (5, 6, 50, 60)))
    names = {save_edited_image(tmp_path, edited) for _ in range(3)}
    assert len(names) == 3 and "source.png" not in names
    assert digest(source) == before
    for name in names:
        path = tmp_path / "captures" / name
        assert_metadata_free(path)
        with Image.open(path) as saved:
            assert saved.size == (200, 150) and saved.mode == "RGB"
            assert_masked(saved, (5, 6, 50, 60))
            assert decode(saved.getpixel((51, 60))) == (51, 60)


def test_import_strips_png_text_and_exif(tmp_path):
    source = tmp_path / "synthetic.png"
    save_with_metadata(coded_image(64, 48), source)
    name = import_image(tmp_path / "storage", source)
    assert_metadata_free(tmp_path / "storage" / "captures" / name)


def test_save_rejects_non_images_and_oversized_results(tmp_path, monkeypatch):
    with pytest.raises(ChatError, match="original remains"):
        save_edited_image(tmp_path, b"not an image")
    monkeypatch.setattr(screen_capture, "MAX_PIXELS", 100)
    with pytest.raises(ChatError, match="40 megapixels"):
        save_edited_image(tmp_path, coded_image(20, 20))
    folder = tmp_path / "captures"
    assert not folder.exists() or not any(folder.iterdir())


def test_save_failure_leaves_no_partial_file(tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("synthetic disk full")

    monkeypatch.setitem(Image.SAVE, "PNG", fail)
    with pytest.raises(ChatError, match="could not be saved"):
        save_edited_image(tmp_path, coded_image(20, 20))
    assert not any((tmp_path / "captures").iterdir())


# --------------------------------------------------------- editor dialog

@pytest.mark.parametrize("size,max_scale", [((320, 240), 1.0), ((1200, 900), 0.9), ((2400, 1800), 0.45)])
def test_mask_survives_display_scaling_crop_and_save(editor, no_network, size, max_scale):
    manager, _window, view, dialog, source = editor(coded_image(*size))
    before = digest(source)
    first_scale = dialog.display_rect[4]
    assert first_scale <= max_scale
    width, height = size

    drag(dialog, "crop", (width // 8, height // 6), (width * 7 // 8, height * 5 // 6))
    assert [kind for kind, _ in dialog.operations] == ["crop"]
    cx1, cy1, cx2, cy2 = dialog.operations[0][1]
    tolerance = math.ceil(1 / first_scale)
    assert abs(cx1 - width // 8) <= tolerance and abs(cy1 - height // 6) <= tolerance
    assert abs(cx2 - width * 7 // 8) <= tolerance and abs(cy2 - height * 5 // 6) <= tolerance
    assert dialog.current.size == (cx2 - cx1 + 1, cy2 - cy1 + 1)

    # The preview refits the cropped image, so later drags use a new scale.
    cropped_width, cropped_height = dialog.current.size
    drag(dialog, "mask", (cropped_width // 4, cropped_height // 4), (cropped_width // 2, cropped_height // 2))
    assert [kind for kind, _ in dialog.operations] == ["crop", "mask"]
    mask = dialog.operations[1][1]
    assert_masked(dialog.current, mask)

    dialog.save()
    manager.root.update()
    assert view._markup_dialog is None
    saved = view.activity.storage / "captures" / view.image_name
    assert saved != source and digest(source) == before
    assert_metadata_free(saved)
    with Image.open(saved) as image:
        # Saved at source resolution, never at the scaled preview size.
        assert image.size == (cropped_width, cropped_height)
        assert_masked(image, mask)
        mx1, my1, mx2, my2 = mask
        for x, y in ((0, 0), (mx2 + 1, my1), (mx1, my2 + 1), (cropped_width - 1, cropped_height - 1)):
            assert decode(image.getpixel((x, y))) == (x + cx1, y + cy1)
        # Downscaling the saved copy cannot recover the hidden pixels either: away from
        # the mask edge (beyond Lanczos' 3-pixel support) the result stays solid.
        for factor in (2, 3, 4):
            small = image.resize((max(1, cropped_width // factor), max(1, cropped_height // factor)),
                                 Image.Resampling.LANCZOS)
            inner = (math.ceil(mx1 / factor) + 4, math.ceil(my1 / factor) + 4,
                     mx2 // factor - 4, my2 // factor - 4)
            if inner[2] > inner[0] and inner[3] > inner[1]:
                assert_masked(small, inner)
    assert view.service.sent == [] and no_network == []
    assert "no request was sent" in view.activity_notice.get()


def test_crop_drag_maps_display_to_source_without_offset(editor):
    _manager, _window, _view, dialog, _source = editor(coded_image(1600, 1200))
    left, top, _width, _height, scale = dialog.display_rect
    assert scale < 1
    dialog.mode.set("crop")
    dialog.begin(Pointer(left + 40, top + 30))
    dialog.end(Pointer(left + 200, top + 150))
    x1, y1, x2, y2 = dialog.operations[0][1]
    assert (x1, y1, x2, y2) == (round(40 / scale), round(30 / scale), round(200 / scale), round(150 / scale))
    assert decode(dialog.current.getpixel((0, 0))) == (x1, y1)
    assert decode(dialog.current.getpixel((x2 - x1, y2 - y1))) == (x2, y2)
    # A release outside the preview applies nothing.
    dialog.begin(Pointer(left + 10, top + 10))
    dialog.end(Pointer(left - 5, top - 5))
    assert len(dialog.operations) == 1


def test_magnify_must_be_undone_before_masking(editor, no_network):
    _manager, _window, view, dialog, _source = editor(coded_image(800, 600))
    drag(dialog, "magnify", (40, 400), (120, 480))
    drag(dialog, "arrow", (300, 300), (360, 340))
    assert [kind for kind, _ in dialog.operations] == ["magnify", "arrow"]
    preview = dialog.current.copy()
    drag(dialog, "mask", (40, 400), (120, 480))
    assert [kind for kind, _ in dialog.operations] == ["magnify", "arrow"]
    assert "Undo Magnify" in dialog.notice.get()
    assert ImageChops.difference(preview, dialog.current).getbbox() is None
    dialog.undo()
    drag(dialog, "mask", (40, 400), (120, 480))
    assert "Undo Magnify" in dialog.notice.get()  # magnify is still first
    dialog.undo()
    assert dialog.operations == []
    drag(dialog, "mask", (40, 400), (120, 480))
    assert [kind for kind, _ in dialog.operations] == ["mask"]
    assert_masked(dialog.current, dialog.operations[0][1])
    # Magnifying after masking only copies already-flattened pixels.
    drag(dialog, "magnify", (60, 420), (100, 460))
    assert [kind for kind, _ in dialog.operations] == ["mask", "magnify"]
    assert_masked(dialog.current, dialog.operations[0][1])
    assert not any(pixel[2] >= 64 and 60 <= decode(pixel)[0] <= 100 and 420 <= decode(pixel)[1] <= 460
                   for _count, pixel in dialog.current.getcolors(maxcolors=1_000_000))
    assert view.service.sent == [] and no_network == []


def test_undo_and_reset_rebuild_from_the_untouched_original(editor):
    original = coded_image(600, 400)
    manager, _window, _view, dialog, source = editor(original)
    before = digest(source)
    drag(dialog, "crop", (50, 50), (550, 350))
    after_crop = dialog.current.copy()
    drag(dialog, "mask", (10, 10), (100, 100))
    after_mask = dialog.current.copy()
    drag(dialog, "arrow", (200, 200), (260, 240))
    assert len(dialog.operations) == 3
    # Ctrl+Z reaches the dialog binding from a focused control.
    control = next(w for w in widgets(dialog.root) if w.winfo_class() == "TRadiobutton")
    control.focus_force()
    manager.root.update()
    control.event_generate("<Control-z>")
    manager.root.update()
    assert len(dialog.operations) == 2
    assert ImageChops.difference(after_mask, dialog.current).getbbox() is None
    assert dialog.undo() == "break"
    assert ImageChops.difference(after_crop, dialog.current).getbbox() is None
    assert "unchanged" in dialog.notice.get()
    dialog.undo()
    assert dialog.operations == [] and dialog.current.size == original.size
    assert ImageChops.difference(original, dialog.current).getbbox() is None
    assert dialog.undo() == "break"  # undo with nothing left is harmless
    drag(dialog, "mask", (10, 10), (100, 100))
    drag(dialog, "crop", (5, 5), (300, 300))
    dialog.reset()
    assert dialog.operations == []
    assert ImageChops.difference(original, dialog.current).getbbox() is None
    assert "unchanged" in dialog.notice.get()
    assert digest(source) == before


def test_operation_limit_and_tiny_regions_leave_preview_unchanged(editor):
    _manager, _window, _view, dialog, _source = editor(coded_image(400, 300))
    drag(dialog, "mask", (10, 10), (11, 11))
    assert dialog.operations == [] and "larger region" in dialog.notice.get()
    for index in range(MAX_OPERATIONS):
        drag(dialog, "arrow", (10 + index, 10), (100 + index, 120))
    assert len(dialog.operations) == MAX_OPERATIONS
    preview = dialog.current.copy()
    drag(dialog, "mask", (200, 200), (260, 260))
    assert len(dialog.operations) == MAX_OPERATIONS
    assert f"{MAX_OPERATIONS}-operation limit" in dialog.notice.get()
    assert ImageChops.difference(preview, dialog.current).getbbox() is None


def test_cancel_and_escape_keep_original_selected_and_write_nothing(editor, no_network):
    manager, _window, view, dialog, source = editor(coded_image(300, 200))
    before, name = digest(source), view.image_name
    drag(dialog, "mask", (10, 10), (200, 150))
    buttons = [w for w in widgets(dialog.root) if w.winfo_class() == "TButton" and w.cget("text") == "Cancel"]
    assert len(buttons) == 1
    buttons[0].invoke()
    manager.root.update()
    assert view._markup_dialog is None and view.image_name == name
    assert sorted(p.name for p in source.parent.iterdir()) == [source.name]
    assert digest(source) == before
    view.edit_image()
    dialog = view._markup_dialog
    manager.root.update()
    drag(dialog, "mask", (10, 10), (200, 150))
    control = next(w for w in widgets(dialog.root) if w.winfo_class() == "TRadiobutton")
    control.focus_force()
    manager.root.update()
    control.event_generate("<Escape>")
    manager.root.update()
    assert view._markup_dialog is None and view.image_name == name
    assert sorted(p.name for p in source.parent.iterdir()) == [source.name]
    assert view.service.sent == [] and no_network == []


def test_save_failure_keeps_dialog_edits_and_original(editor, monkeypatch, no_network):
    manager, _window, view, dialog, source = editor(coded_image(300, 200))
    before, name = digest(source), view.image_name
    drag(dialog, "mask", (10, 10), (200, 150))

    def fail(*_args, **_kwargs):
        raise OSError("synthetic disk full")

    monkeypatch.setitem(Image.SAVE, "PNG", fail)
    dialog.save()
    manager.root.update()
    assert view._markup_dialog is dialog and not dialog.closed
    assert "could not be saved" in dialog.notice.get()
    assert len(dialog.operations) == 1 and view.image_name == name
    assert sorted(p.name for p in source.parent.iterdir()) == [source.name]
    assert digest(source) == before
    monkeypatch.undo()
    dialog.save()
    manager.root.update()
    assert view._markup_dialog is None and view.image_name != name
    assert digest(source) == before
    assert view.service.sent == [] and no_network == []


def test_saved_copy_is_what_a_reviewed_request_would_attach(editor, no_network):
    manager, window, view, dialog, source = editor(coded_image(300, 200))
    drag(dialog, "mask", (10, 10), (200, 150))
    dialog.save()
    manager.root.update()
    edited = view.image_name
    assert edited != source.name and view._preview_image is not None
    choose(window, 1)
    view.prepare_request()
    settle(view)
    assert view._request_dialog.packet["image"].endswith(edited)
    assert view.service.sent == [] and no_network == []


def test_missing_corrupt_and_oversized_sources_do_not_open(editor, manager_factory, monkeypatch):
    manager, _window, view, dialog, source = editor(coded_image(64, 48))
    dialog.close()
    name = view.image_name
    source.unlink()
    view.edit_image()
    assert view._markup_dialog is None and "unavailable" in view.activity_notice.get()
    source.write_bytes(b"not a png")
    view.edit_image()
    assert view._markup_dialog is None and "could not be opened" in view.activity_notice.get()
    assert view.image_name == name and source.read_bytes() == b"not a png"
    coded_image(64, 48).save(source)
    assert MARKUP_MAX_PIXELS == 20_000_000
    monkeypatch.setattr(image_markup, "MARKUP_MAX_PIXELS", 64 * 48 - 1)
    view.edit_image()
    assert view._markup_dialog is None and "20 megapixels" in view.activity_notice.get()
    monkeypatch.setattr(image_markup, "MARKUP_MAX_PIXELS", 64 * 48)
    view.edit_image()
    assert view._markup_dialog is not None
    view.image_name = "../outside.png"
    view._markup_dialog.close()
    view.edit_image()
    assert view._markup_dialog is None and "image first" in view.activity_notice.get()
    view.image_name = None
    view.edit_image()
    assert view._markup_dialog is None and "before editing" in view.activity_notice.get()
    assert view.service.sent == []
    manager.root.update()


# ------------------------------------------------------------ UI layout

def widgets(root):
    pending, found = [root], []
    while pending:
        widget = pending.pop()
        found.append(widget)
        pending.extend(widget.winfo_children())
    return found


@pytest.mark.parametrize("theme", ["classic", "modern"])
def test_editor_controls_fit_and_are_keyboard_reachable_at_minimum_size(editor, theme):
    manager, _window, _view, dialog, _source = editor(coded_image(640, 360), theme=theme)
    assert dialog.root.minsize() == (640, 520)
    dialog.chrome.place("640x520+40+40")
    manager.root.update()
    dialog.draw()
    colors = PALETTES[theme]
    assert dialog.chrome.content.cget("bg") == colors.BACKGROUND
    labels = [w for w in widgets(dialog.root) if w.winfo_class() == "Label"]
    assert any(w.cget("bg") == colors.BACKGROUND and "source image is preserved" in w.cget("text") for w in labels)

    controls = {}
    for widget in widgets(dialog.root):
        if widget.winfo_class() in ("TRadiobutton", "TButton"):
            controls[str(widget.cget("text"))] = widget
    expected = ["Crop", "Arrow", "Magnify", "Mask", "Undo", "Reset edits", "Save edited copy", "Cancel"]
    assert set(expected) <= set(controls)

    right = dialog.root.winfo_rootx() + dialog.root.winfo_width()
    bottom = dialog.root.winfo_rooty() + dialog.root.winfo_height()
    for label in expected:
        widget = controls[label]
        assert widget.winfo_ismapped(), label
        assert widget.winfo_width() >= widget.winfo_reqwidth(), f"{label} is truncated"
        assert widget.winfo_rootx() >= dialog.root.winfo_rootx(), label
        assert widget.winfo_rootx() + widget.winfo_width() <= right, label
        assert widget.winfo_rooty() + widget.winfo_height() <= bottom, label
    assert dialog.canvas.winfo_ismapped() and dialog.canvas.winfo_height() > 100

    # The longest notice wraps inside the footer instead of clipping or hiding buttons.
    dialog.notice.set("Undo Magnify edits before masking so enlarged copies cannot retain unmasked pixels.")
    manager.root.update()
    notice = next(w for w in labels if str(w.cget("textvariable")) == str(dialog.notice))
    assert notice.winfo_width() >= notice.winfo_reqwidth()
    for label in ("Save edited copy", "Cancel"):
        widget = controls[label]
        assert widget.winfo_width() >= widget.winfo_reqwidth(), f"{label} is truncated"
        assert widget.winfo_rooty() + widget.winfo_height() <= bottom, label

    reached, current = set(), str(controls["Crop"])
    for _ in range(200):
        reached.add(current)
        current = str(dialog.root.tk.call("tk_focusNext", current))
        if current == str(controls["Crop"]):
            break
    assert {str(controls[label]) for label in expected} <= reached

    controls["Mask"].invoke()
    assert dialog.mode.get() == "mask"
    controls["Crop"].invoke()
    assert dialog.mode.get() == "crop"
