"""Synthetic preference and fallback checks; no desktop or game access."""

import pytest

from wow_helper.interface import INTERFACE_DEFAULTS, WindowOpacity, interface_settings


@pytest.mark.parametrize("raw", [None, [], "modern", {"theme": [], "opacity": True, "solid_when_active": 1},
                                 {"theme": "missing", "opacity": float("nan")}, {"opacity": "85"}])
def test_invalid_preferences_fall_back_to_readable_defaults(raw):
    assert interface_settings(raw) == INTERFACE_DEFAULTS


def test_opacity_is_bounded_and_theme_is_optional_for_old_layouts():
    assert interface_settings({"opacity": -100})["opacity"] == 65
    assert interface_settings({"opacity": 1000})["opacity"] == 100
    assert interface_settings({"theme": "modern", "opacity": 87, "solid_when_active": False}) == {
        "theme": "modern", "opacity": 87, "solid_when_active": False}


class Surface:
    def __init__(self):
        self.tk = self
        self.alpha = 1.0
        self.active = False
        self.reject = False
        self.ignore = False

    def bind(self, *_args, **_kwargs): pass
    def __str__(self): return ".synthetic"
    def call(self, *_): return ".synthetic.editor" if self.active else ""

    def attributes(self, name, value=None):
        assert name == "-alpha"
        if self.reject:
            from tkinter import TclError
            raise TclError("Synthetic unsupported alpha")
        if value is not None and not self.ignore:
            self.alpha = value
        return self.alpha


def test_focus_restores_readability_and_returns_to_selected_opacity():
    root = Surface()
    settings = {"opacity": 80, "solid_when_active": True}
    controller = WindowOpacity(root, lambda: settings)
    assert root.alpha == .8
    root.active = True
    controller.apply()
    assert root.alpha == 1
    root.active = False
    controller.apply()
    assert root.alpha == .8
    settings["solid_when_active"] = False
    root.active = True
    controller.apply()
    assert root.alpha == .8


@pytest.mark.parametrize("failure", ["reject", "ignore"])
def test_unavailable_transparency_stays_opaque_and_reports_fallback(failure):
    root = Surface()
    setattr(root, failure, True)
    controller = WindowOpacity(root, lambda: {"opacity": 80})
    assert not controller.supported
    assert root.alpha == 1
