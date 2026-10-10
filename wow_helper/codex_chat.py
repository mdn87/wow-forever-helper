"""Read an existing Codex daemon and queue explicit messages, without a shell."""

import json
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import threading
import time


class ChatError(Exception):
    """A fixed, public-safe error for the chat UI."""


def codex_executable():
    """Avoid Windows npm .cmd quoting: messages must never enter a shell."""
    found = shutil.which("codex")
    if not found:
        raise ChatError("Codex is not installed or is not on PATH.")
    path = Path(found)
    if os.name != "nt" or path.suffix.lower() == ".exe":
        return str(path)
    package = path.parent / "node_modules" / "@openai" / "codex"
    candidates = sorted(package.glob("node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe"))
    candidates += sorted(package.glob("vendor/*/codex/codex.exe"))
    if not candidates:
        raise ChatError("The Codex native executable was not found. Repair the CLI installation.")
    return str(candidates[0])


def process_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


class PipeSocket:
    """A socket interface for WebSocket bytes over `codex app-server proxy`.

    The proxy owns the platform-specific local socket. A reader thread gives
    Windows pipes bounded reads without requiring Unix socket support in Python.
    """

    def __init__(self, process, timeout=6):
        self.process = process
        self.timeout = timeout
        self.buffer = b""
        self.chunks = queue.Queue()
        self.ended = False
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while chunk := self.process.stdout.read1(65536):
                self.chunks.put(chunk)
        except (OSError, ValueError):
            pass
        finally:
            self.chunks.put(b"")

    def settimeout(self, timeout):
        self.timeout = timeout

    def gettimeout(self):
        return self.timeout

    def send(self, data):
        self.process.stdin.write(data)
        self.process.stdin.flush()
        return len(data)

    def recv(self, size):
        if not self.buffer and not self.ended:
            try:
                self.buffer = self.chunks.get(timeout=self.timeout)
            except queue.Empty:
                raise socket.timeout() from None
            self.ended = not self.buffer
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.process.stdin.close()
        self.process.stdout.close()

    def shutdown(self, *_):
        self.close()


class CodexClient:
    """Single-worker read-only RPC connection; sends use the CLI's queue command."""

    def __init__(self):
        self.ws = None
        self.pipe = None
        self.sequence = 0

    def close(self):
        if self.pipe is not None:
            self.pipe.close()
        self.ws = self.pipe = None

    def _connect(self):
        try:
            import websocket
        except ImportError:
            raise ChatError("Chat needs websocket-client. Install the project's chat extra.") from None
        try:
            process = subprocess.Popen(
                [codex_executable(), "app-server", "proxy"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                **process_options(),
            )
            self.pipe = PipeSocket(process)
            self.ws = websocket.create_connection(
                "ws://localhost/", socket=self.pipe, timeout=6, suppress_origin=True,
                # recv() still decodes text with strict UTF-8 in native code. The
                # duplicate Python validator can starve Tk on multi-MB histories.
                skip_utf8_validation=True,
            )
            self._rpc("initialize", {
                "clientInfo": {"name": "wow_helper", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            })
            self.ws.send(json.dumps({"method": "initialized", "params": {}}))
        except ChatError:
            self.close()
            raise
        except Exception:
            self.close()
            raise ChatError("Codex is unavailable. Open a local Codex session, then refresh.") from None

    def _rpc(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.ws.send(json.dumps({"id": request_id, "method": method, "params": params}))
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            self.ws.settimeout(max(0.01, deadline - time.monotonic()))
            message = json.loads(self.ws.recv())
            if message.get("id") == request_id:
                if "error" in message:
                    # Provider errors may contain prompts, credentials, and machine paths.
                    raise ChatError("Codex could not read this session. Check the CLI and refresh.")
                return message["result"]
        raise ChatError("Codex did not respond in time. Refresh to reconnect.")

    def rpc(self, method, params):
        # This connection deliberately cannot execute tools, resume, or grant approvals.
        if method not in {"thread/loaded/list", "thread/read", "thread/items/list", "thread/turns/list"}:
            raise ChatError("Unsupported chat operation.")
        try:
            if self.ws is None:
                self._connect()
            return self._rpc(method, params)
        except ChatError:
            self.close()
            raise
        except Exception:
            self.close()
            raise ChatError("The Codex connection closed. Refresh to reconnect.") from None

    def sessions(self):
        found = []
        cursor = None
        for _ in range(20):
            page = self.rpc("thread/loaded/list", {"limit": 100, "cursor": cursor})
            for session_id in page.get("data", []):
                summary = self.rpc("thread/read", {"threadId": session_id, "includeTurns": False})["thread"]
                # Include terminal and desktop sessions, but exclude background child agents.
                if (summary.get("parentThreadId") or isinstance(summary.get("source"), dict)
                        or summary.get("canAcceptDirectInput") is False):
                    continue
                if summary.get("status", {}).get("type") == "notLoaded":
                    continue
                found.append(summary)
            cursor = page.get("nextCursor")
            if not cursor:
                break
        return found

    def messages(self, session_id):
        page = self.rpc("thread/items/list", {
            "threadId": session_id, "limit": 100, "sortDirection": "desc",
        })
        return [entry["item"] for entry in reversed(page.get("data", []))]

    def send(self, session_id, message):
        try:
            result = subprocess.run(
                [codex_executable(), "queue", "--thread", session_id, "--message", message],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=20, **process_options(),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ChatError("Delivery is uncertain. Check the terminal before sending again.") from None
        if result.returncode != 0:
            raise ChatError("Codex did not confirm delivery. Check the terminal before sending again.")
