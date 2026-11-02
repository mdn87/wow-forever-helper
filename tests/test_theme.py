import tkinter

import pytest

from wow_helper import theme


class FakePhoto:
    attempts = []
    failures = []

    def __init__(self, master=None, file=None):
        FakePhoto.attempts.append(file)
        if FakePhoto.failures:
            raise tkinter.TclError(FakePhoto.failures.pop(0))

    def subsample(self, factor):
        return ("subsampled", factor)


@pytest.fixture
def fake_photo(monkeypatch):
    FakePhoto.attempts, FakePhoto.failures = [], []
    monkeypatch.setattr(tkinter, "PhotoImage", FakePhoto)
    return FakePhoto


def test_texture_retries_once_after_empty_tk_decode_error(fake_photo):
    fake_photo.failures = [""]
    assert theme._load_texture(None, "dark-leather.png") == ("subsampled", 3)
    assert fake_photo.attempts == [str(theme.ASSETS / "dark-leather.png")] * 2


def test_texture_reports_a_described_tk_error_without_retrying(fake_photo):
    fake_photo.failures = ["couldn't open file"]
    with pytest.raises(tkinter.TclError, match="couldn't open"):
        theme._load_texture(None, "dark-leather.png")
    assert len(fake_photo.attempts) == 1


def test_texture_retries_only_once(fake_photo):
    fake_photo.failures = ["", ""]
    with pytest.raises(tkinter.TclError):
        theme._load_texture(None, "red-leather.png")
    assert len(fake_photo.attempts) == 2
