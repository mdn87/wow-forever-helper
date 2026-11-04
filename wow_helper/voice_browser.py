"""A companion-owned Chrome window driven by spoken hands-free commands.

The companion starts one Chrome window with its own throwaway profile and a
loopback-only DevTools port and no window, opens the window in the background
through DevTools so the game keeps the foreground, then drives that window alone: navigate, search,
follow a link by name or result number, scroll, back and forward, and read the
page text for Lugos Voice to speak. Every action goes through the DevTools
Protocol to the page itself, so nothing is clicked or typed through the real
mouse or keyboard and no window is activated. The foreground window is checked
before and after each action, and a change is reported, never undone.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import quote_plus, urlparse
from urllib.request import urlopen

from .chat import ROOT

PORT = 9231
PROFILE = ROOT / ".runtime" / "voice-browser" / "profile"
START_URL = "about:blank"
TIMEOUT = 6.0
READ_CHARS = 900
CHROME = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
]
SEARCH = {
    "wowhead": "https://www.wowhead.com/search?q={}",
    "classic": "https://www.wowhead.com/classic/search?q={}",
    "web": "https://www.bing.com/search?q={}",
}
NUMBERS = {"first": 1, "top": 1, "one": 1, "second": 2, "two": 2, "third": 3, "three": 3,
           "fourth": 4, "four": 4, "fifth": 5, "five": 5}

# Page scripts. They only read the page, scroll it, or return a link to navigate to.
LINKS_JS = r"""(() => {
  const seen = new Set(), rows = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const r = a.getBoundingClientRect(), text = (a.innerText || a.title || '').replace(/\s+/g, ' ').trim();
    if (!text || r.width < 2 || r.height < 2 || !/^https?:/.test(a.href) || seen.has(a.href)) continue;
    seen.add(a.href); rows.push([text.slice(0, 120), a.href]);
    if (rows.length >= 400) break;
  }
  return rows;
})()"""
RESULTS_JS = r"""(() => {
  const pick = (sel) => [...document.querySelectorAll(sel)].map(a => [(a.innerText || '').replace(/\s+/g, ' ').trim(), a.href])
    .filter(([t, h]) => t && /^https?:/.test(h));
  const host = location.hostname;
  let rows = [];
  if (host.endsWith('wowhead.com')) rows = pick('.listview-row a.listview-cleartext, .listview-row td a[href*="="]');
  if (!rows.length && host.endsWith('bing.com')) rows = pick('#b_results li.b_algo h2 a');
  if (!rows.length) rows = pick('main a[href], article a[href], #content a[href]');
  const seen = new Set();
  return rows.filter(([t, h]) => !seen.has(h) && seen.add(h)).slice(0, 20);
})()"""
TEXT_JS = r"""(() => {
  const root = document.querySelector('#main-contents .text, article, main, [role=main]') || document.body;
  return (root ? root.innerText : '').replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim().slice(0, 60000);
})()"""


class BrowserError(Exception):
    """A browser command that could not run; the message is spoken."""


def find_chrome():
    return next((path for path in CHROME if path.is_file()), None)


def foreground_window():
    if os.name != "nt":
        return None
    from .tooltip_probe import foreground_window as current
    return current()


class DevTools:
    """One DevTools Protocol connection to a page target."""

    def __init__(self, url, timeout=TIMEOUT):
        import websocket
        # Chrome refuses websocket clients that send an Origin it was not told to allow.
        self.ws = websocket.create_connection(url, timeout=timeout, suppress_origin=True)
        self.next_id = 0

    def call(self, method, params=None):
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params or {}}))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get("id") == self.next_id:
                if "error" in reply:
                    raise BrowserError(f"The browser refused that: {reply['error'].get('message', 'unknown error')}.")
                return reply.get("result", {})

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def page_url(spoken):
    """A spoken site or address as a URL, or None when it does not look like one."""
    text = spoken.strip().lower()
    text = re.sub(r"\s+dot\s+", ".", text).replace(" ", "")
    if re.fullmatch(r"https?://\S+", text):
        return text
    if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?", text):
        return "https://" + text
    return None


class Browser:
    def __init__(self, *, port=PORT, profile=PROFILE, chrome=None, http=None, devtools=DevTools,
                 launcher=subprocess.Popen, foreground=foreground_window, clock=time.monotonic, sleep=time.sleep):
        self.port, self.profile = port, Path(profile)
        self.chrome = chrome
        self.http = http or (lambda url: urlopen(url, timeout=2).read())
        self.devtools, self.launcher = devtools, launcher
        self.foreground, self.clock, self.sleep = foreground, clock, sleep
        self.lock = threading.Lock()
        self.read_from = {}      # page URL -> characters already read aloud

    # -- the window
    def _json(self, path):
        return json.loads(self.http(f"http://127.0.0.1:{self.port}{path}"))

    def running(self):
        try:
            self._json("/json/version")
            return True
        except Exception:
            return False

    def launch(self):
        chrome = self.chrome or find_chrome()
        if chrome is None:
            raise BrowserError("Chrome was not found, so the voice browser cannot open.")
        self.profile.mkdir(parents=True, exist_ok=True)
        # A window Chrome opens itself takes the foreground (seen 2026-11-04 even with SW_SHOWNOACTIVATE),
        # so Chrome starts with none and new_window() opens one in the background.
        args = [str(chrome), f"--user-data-dir={self.profile}", f"--remote-debugging-port={self.port}",
                "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
                "--no-startup-window"]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.launcher(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      close_fds=True, **options)
        deadline = self.clock() + 15
        while self.clock() < deadline:
            if self.running():
                return
            self.sleep(0.25)
        raise BrowserError("The voice browser did not start within 15 seconds.")

    def new_window(self):
        tools = self.devtools(self._json("/json/version")["webSocketDebuggerUrl"])
        try:
            tools.call("Target.createTarget", {"url": START_URL, "newWindow": True, "background": True})
        finally:
            tools.close()

    def pages(self):
        try:
            return [t for t in self._json("/json/list") if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        except Exception:
            return []

    def page(self):
        pages = self.pages()
        if not pages:
            raise BrowserError("The voice browser has no open tab. Say open the browser.")
        return pages[0]

    # -- running one command
    def run(self, action, argument=""):
        """Run one spoken browser command; returns the sentence to speak."""
        if not self.lock.acquire(blocking=False):
            raise BrowserError("The browser is still working on the last request.")
        try:
            before = self.foreground()
            if action == "open":
                detail = self._open()
            else:
                if not self.running():
                    raise BrowserError("The voice browser is not open. Say open the browser first.")
                tools = self.devtools(self.page()["webSocketDebuggerUrl"])
                try:
                    detail = getattr(self, "_" + action)(tools, argument)
                finally:
                    tools.close()
            after = self.foreground()
            if before is not None and after != before:
                detail += " The foreground window changed during that; switch back to the game."
            return detail
        finally:
            self.lock.release()

    def _open(self):
        if self.running() and self.pages():
            return "The voice browser is already open."
        if not self.running():
            self.launch()
        self.new_window()
        return "The voice browser is open. Move it where you want it once; Chrome remembers the spot."

    def _evaluate(self, tools, script):
        result = tools.call("Runtime.evaluate", {"expression": script, "returnByValue": True})
        if "exceptionDetails" in result:
            raise BrowserError("That page did not allow it.")
        return result.get("result", {}).get("value")

    def _wait_loaded(self, tools, previous=None):
        deadline = self.clock() + TIMEOUT
        state = {}
        while self.clock() < deadline:
            state = self._evaluate(tools, "({url: location.href, title: document.title, ready: document.readyState})") or {}
            # A redirect page has no title yet; wait for the page it leads to.
            if state.get("url") != previous and state.get("ready") == "complete" and state.get("title"):
                break
            self.sleep(0.2)
        return state

    def _say_page(self, state, verb="Opened"):
        title = (state.get("title") or "").strip() or urlparse(state.get("url", "")).hostname or "the page"
        return f"{verb} {title[:120]}."

    def _navigate(self, tools, url):
        previous = self._evaluate(tools, "location.href")
        tools.call("Page.navigate", {"url": url})
        return self._say_page(self._wait_loaded(tools, previous))

    def _go(self, tools, spoken):
        url = page_url(spoken)
        if url is None:
            return self._search(tools, spoken)
        return self._navigate(tools, url)

    def _search(self, tools, query, site="wowhead"):
        query = query.strip()
        if not query:
            raise BrowserError("Say what to look up.")
        state_text = self._navigate(tools, SEARCH[site].format(quote_plus(query)))
        return state_text

    def _classic(self, tools, query):
        return self._search(tools, query, "classic")

    def _web(self, tools, query):
        return self._search(tools, query, "web")

    def _history(self, tools, step):
        entries = tools.call("Page.getNavigationHistory")
        index = entries.get("currentIndex", 0) + step
        rows = entries.get("entries", [])
        if not 0 <= index < len(rows):
            return "There is no page to go " + ("back" if step < 0 else "forward") + " to."
        previous = self._evaluate(tools, "location.href")
        tools.call("Page.navigateToHistoryEntry", {"entryId": rows[index]["id"]})
        return self._say_page(self._wait_loaded(tools, previous), "Back to" if step < 0 else "Forward to")

    def _back(self, tools, _=""):
        return self._history(tools, -1)

    def _forward(self, tools, _=""):
        return self._history(tools, 1)

    def _scroll(self, tools, direction):
        sign = {"up": -1, "top": 0}.get(direction, 1)
        if direction in {"top", "bottom"}:
            script = "window.scrollTo(0, %s)" % ("0" if direction == "top" else "document.body.scrollHeight")
        else:
            script = f"window.scrollBy(0, {sign} * Math.round(innerHeight * 0.8))"
        self._evaluate(tools, script)
        return {"up": "Scrolled up.", "top": "At the top.", "bottom": "At the bottom."}.get(direction, "Scrolled down.")

    def _follow(self, tools, name):
        from .voice_commands import best, spoken_label
        links = self._evaluate(tools, LINKS_JS) or []
        href, close = best(spoken_label(name), [(text, url) for text, url in links])
        if href is None:
            if close:
                return "Did you mean " + " or ".join(close) + "?"
            raise BrowserError(f"No link called {name} is on the page.")
        return self._navigate(tools, href)

    def _result(self, tools, which):
        number = NUMBERS.get(which) or (int(which) if str(which).isdigit() else None)
        if not number:
            raise BrowserError("Say a result number, like open the first result.")
        rows, deadline = [], self.clock() + 3
        while True:   # result lists can render a moment after the page loads
            rows = self._evaluate(tools, RESULTS_JS) or []
            if len(rows) >= number or self.clock() >= deadline:
                break
            self.sleep(0.25)
        if len(rows) < number:
            raise BrowserError(f"The page shows {len(rows)} results." if rows else "No results are on this page.")
        return self._navigate(tools, rows[number - 1][1])

    def _read(self, tools, more=""):
        state = self._evaluate(tools, "({url: location.href, title: document.title})") or {}
        text = self._evaluate(tools, TEXT_JS) or ""
        url = state.get("url", "")
        start = self.read_from.get(url, 0) if more else 0
        if start >= len(text):
            return "That is the end of the page."
        chunk = text[start:start + READ_CHARS]
        cut = max(chunk.rfind(". "), chunk.rfind("\n"))
        if start + READ_CHARS < len(text) and cut > READ_CHARS // 2:
            chunk = chunk[:cut + 1]
        self.read_from[url] = start + len(chunk)
        lead = "" if more else (state.get("title", "").strip()[:100] + ". ")
        return (lead + " ".join(chunk.split())).strip()

    def _where(self, tools, _=""):
        state = self._evaluate(tools, "({url: location.href, title: document.title})") or {}
        host = urlparse(state.get("url", "")).hostname or "a blank page"
        return f"The browser shows {(state.get('title') or '').strip()[:120] or 'an untitled page'}, on {host}."

    def _close(self, tools, _=""):
        try:
            tools.call("Browser.close")
        except Exception:
            pass
        return "The voice browser is closed."
