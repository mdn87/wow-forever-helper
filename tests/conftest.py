"""One Tk interpreter for all synthetic UI tests, matching the application."""

import os

import pytest


@pytest.fixture(scope="session")
def desktop():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        if os.name == "nt":
            raise
        pytest.skip("Tk requires a graphical desktop")
    root.withdraw()
    yield tk, root
    root.destroy()
