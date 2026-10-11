"""One Tk interpreter for all synthetic UI tests, matching the application."""

import os
import gc
import sys

import pytest


@pytest.fixture(autouse=True)
def collect_closed_tk_views():
    # Tests pump update() instead of running Tk's mainloop. Collect previous
    # tests' widget cycles on this thread before a new provider worker starts;
    # Tk variable finalizers cannot marshal calls from workers without mainloop.
    if "tkinter" in sys.modules:
        gc.collect()


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
