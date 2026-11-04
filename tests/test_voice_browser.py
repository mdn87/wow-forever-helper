"""Synthetic voice browser checks: spoken browser commands and the DevTools calls they make.

No Chrome, network or game is used. The DevTools connection, the local HTTP
endpoints, the launcher and the foreground window are fakes.
"""

import json
import time

import pytest

from wow_helper.voice_browser import Browser, BrowserError, page_url
from wow_helper.voice_bridge import write_request
from wow_helper.voice_commands import Interpreter
from test_handsfree import handsfree, say  # noqa: F401
from test_workspace import manager_factory  # noqa: F401


class FakePage:
    """One synthetic tab: its address, title, links, results and text."""

    def __init__(self):
        self.url, self.title = "about:blank", ""
        self.history, self.index = [("about:blank", "")], 0
        self.sites = {
            "https://www.wowhead.com/search?q=frostbolt": ("frostbolt - Search", [], [["Frostbolt", "https://example.test/frostbolt"],
                                                                                 ["Frost Nova", "https://example.test/nova"]], ""),
            "https://example.test/frostbolt": ("Frostbolt - Spell", [["Rank 2 trainer", "https://example.test/trainer"]], [],
                                               "Launches a bolt of frost. " * 80),
            "https://example.test/trainer": ("Mage trainer", [], [], "Find the trainer in town."),
        }
        self.scripts, self.calls = [], []

    def visit(self, url):
        self.history = self.history[:self.index + 1] + [(url, self.sites.get(url, ("Synthetic page",))[0])]
        self.index = len(self.history) - 1
        self.url, self.title = self.history[self.index]


class FakeDevTools:
    def __init__(self, page):
        self.page = page

    def __call__(self, url):
        self.page.calls.append(("connect", url))
        return self

    def call(self, method, params=None):
        page, params = self.page, params or {}
        page.calls.append((method, params))
        if method == "Page.navigate":
            page.visit(params["url"])
        elif method == "Page.getNavigationHistory":
            return {"currentIndex": page.index, "entries": [{"id": i, "url": u} for i, (u, _) in enumerate(page.history)]}
        elif method == "Page.navigateToHistoryEntry":
            page.index = params["entryId"]
            page.url, page.title = page.history[page.index]
        elif method == "Runtime.evaluate":
            return {"result": {"value": self.evaluate(params["expression"])}}
        return {}

    def evaluate(self, script):
        page = self.page
        page.scripts.append(script)
        _, links, results, text = page.sites.get(page.url, ("", [], [], ""))
        if script == "location.href":
            return page.url
        if "readyState" in script:
            return {"url": page.url, "title": page.title, "ready": "complete"}
        if "document.title" in script:
            return {"url": page.url, "title": page.title}
        if "listview-row" in script:
            return results
        if "a[href]" in script:
            return links
        if "innerText" in script:
            return text
        return None

    def close(self):
        pass


@pytest.fixture
def browser(tmp_path):
    page = FakePage()
    state = {"running": True, "pages": 1, "launched": [], "foreground": [100]}

    def http(url):
        if not state["running"]:
            raise OSError("connection refused")
        if url.endswith("/json/version"):
            return json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1/browser"}).encode()
        return json.dumps([{"type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1/page"}] * state["pages"]).encode()

    def launcher(args, **options):
        state["launched"].append((args, options))
        state["running"] = True

    tool = Browser(profile=tmp_path / "profile", http=http, devtools=FakeDevTools(page), launcher=launcher, chrome="chrome.exe",
                   foreground=lambda: state["foreground"][-1], sleep=lambda _: None)
    tool.page_state, tool.state = page, state
    return tool


def test_spoken_browser_phrases_map_to_actions():
    interpreter = Interpreter(None, None)
    cases = {
        "open the browser": ("open", ""), "close the browser": ("close", ""),
        "look up frostbolt": ("search", "frostbolt"), "please look up orgrimmar flight master on wowhead":
            ("search", "orgrimmar flight master"),
        "look up thunder bluff on classic": ("classic", "thunder bluff"),
        "search the web for wow forever patch notes": ("web", "wow forever patch notes"),
        "browse to wowhead dot com": ("go", "wowhead dot com"),
        "open the first result": ("result", "first"), "open result 3": ("result", "3"),
        "open the 2nd result": ("result", "2"), "follow the link rank 2 trainer": ("follow", "rank 2 trainer"),
        "scroll down": ("scroll", "down"), "page up": ("scroll", "up"), "scroll to the top": ("scroll", "top"),
        "go back": ("back", ""), "forward": ("forward", ""),
        "read the page": ("read", ""), "keep reading": ("read", "more"),
        "what's on the browser": ("where", ""),
        # Natural phrasing: lead-ins, the wake word, "for me", "in the browser" and question marks.
        "can you look up frostbolt for me": ("search", "frostbolt"),
        "Hey Lugos, could you please look up frostbolt in the browser?": ("search", "frostbolt"),
        "look frostbolt up": ("search", "frostbolt"), "pull up orgrimmar flight master": ("search", "orgrimmar flight master"),
        "I want you to search for the mage trainer on wowhead please": ("search", "the mage trainer"),
        "can you google wow forever patch notes": ("web", "wow forever patch notes"),
        "go ahead and open up the browser": ("open", ""), "let's open the first one": ("result", "first"),
        "take me to the second result": ("result", "second"), "read me the page": ("read", ""),
        "what does the page say": ("read", ""), "keep going": ("read", "more"),
        "scroll down a little": ("scroll", "down"), "previous page": ("back", ""),
    }
    for phrase, (action, argument) in cases.items():
        outcome = interpreter.handle(phrase)
        assert (outcome.kind, outcome.detail, outcome.text) == ("browser", action, argument), phrase


def test_spoken_addresses():
    assert page_url("wowhead dot com") == "https://wowhead.com"
    assert page_url("https://example.test/a") == "https://example.test/a"
    assert page_url("warcraft wiki classic") is None


def test_open_starts_chrome_without_a_window_then_opens_one_in_the_background(browser):
    browser.state["running"] = False
    assert browser.run("open").startswith("The voice browser is open.")
    args, options = browser.state["launched"][0]
    assert "--no-startup-window" in args and f"--remote-debugging-port={browser.port}" in args
    assert "--remote-debugging-address=127.0.0.1" in args and any(a.startswith("--user-data-dir=") for a in args)
    created = [p for m, p in browser.page_state.calls if m == "Target.createTarget"]
    assert created == [{"url": "about:blank", "newWindow": True, "background": True}]
    assert browser.run("open") == "The voice browser is already open."
    assert len(browser.state["launched"]) == 1


def test_commands_refuse_when_the_browser_is_not_open(browser):
    browser.state["running"] = False
    with pytest.raises(BrowserError, match="not open"):
        browser.run("search", "frostbolt")
    browser.state.update(running=True, pages=0)
    with pytest.raises(BrowserError, match="no open tab"):
        browser.run("read")


def test_search_result_link_read_and_history(browser):
    page = browser.page_state
    assert browser.run("search", "frostbolt") == "Opened frostbolt - Search."
    assert page.url == "https://www.wowhead.com/search?q=frostbolt"
    assert browser.run("result", "first") == "Opened Frostbolt - Spell."
    first = browser.run("read")
    assert first.startswith("Frostbolt - Spell. Launches a bolt") and len(first) < 1000
    more = browser.run("read", "more")
    assert more.startswith("Launches") and more != first
    assert browser.run("follow", "rank two trainer") == "Opened Mage trainer."
    assert browser.run("back") == "Back to Frostbolt - Spell."
    assert browser.run("forward") == "Forward to Mage trainer."
    assert browser.run("where") == "The browser shows Mage trainer, on example.test."
    with pytest.raises(BrowserError, match="No link called"):
        browser.run("follow", "auction house")
    browser.run("back"); browser.run("back")
    with pytest.raises(BrowserError, match="shows 2 results"):
        browser.run("result", "fifth")
    navigations = [p["url"] for m, p in page.calls if m == "Page.navigate"]
    assert navigations == ["https://www.wowhead.com/search?q=frostbolt", "https://example.test/frostbolt",
                           "https://example.test/trainer"]


def test_page_actions_use_page_scripts_only(browser):
    for direction, expected in [("down", "Scrolled down."), ("up", "Scrolled up."), ("bottom", "At the bottom.")]:
        assert browser.run("scroll", direction) == expected
    methods = {m for m, _ in browser.page_state.calls if m != "connect"}
    # No input emulation and no window activation: only page scripts and navigation.
    assert methods <= {"Runtime.evaluate", "Page.navigate", "Page.getNavigationHistory", "Page.navigateToHistoryEntry"}
    assert not any(m.startswith(("Input.", "Target.activate", "Page.bringToFront")) for m, _ in browser.page_state.calls)


def test_a_foreground_change_is_reported_and_not_undone(browser):
    foreground = browser.state["foreground"]
    original = browser.foreground
    browser.foreground = lambda: (foreground.append(200), 100)[1] if len(foreground) == 1 else foreground[-1]
    assert browser.run("search", "frostbolt").endswith("The foreground window changed during that; switch back to the game.")
    browser.foreground = original
    assert foreground[-1] == 200


def test_one_command_at_a_time(browser):
    browser.lock.acquire()
    try:
        with pytest.raises(BrowserError, match="still working"):
            browser.run("read")
    finally:
        browser.lock.release()


def test_hands_free_browser_turns_are_answered_from_the_worker(handsfree):
    manager, window, view, folder = handsfree
    calls = []

    class Fake:
        def run(self, action, argument=""):
            calls.append((action, argument))
            if action == "read":
                raise BrowserError("The voice browser is not open. Say open the browser first.")
            return "Opened frostbolt - Search."

    manager.handsfree.browser_factory = Fake
    manager.handsfree._browser = None

    def spoken(text):
        request_id = write_request(text, storage=folder)
        path = folder / "results" / (request_id + ".json")
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            manager.handsfree.poll()
            manager.root.update()
            time.sleep(0.02)
        return json.loads(path.read_text(encoding="utf-8"))

    result = spoken("look up frostbolt")
    assert (result["status"], result["detail"]) == ("done", "Opened frostbolt - Search.")
    result = spoken("read the page")
    assert result["status"] == "rejected" and "not open" in result["detail"]
    assert calls == [("search", "frostbolt"), ("read", "")]
    assert view.editor.get("1.0", "end").strip() == ""   # nothing went to chat
    assert manager.handsfree.history[-1][1] == "refused"
