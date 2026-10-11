"""Local session discovery, text-only transcripts, and a durable Claude inbox."""

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from .codex_chat import ChatError, CodexClient, process_options

ROOT = Path(__file__).resolve().parents[1]
CHAT_STATE = ROOT / ".runtime" / "chat"
MAX_MESSAGE = 6000


def identifier(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError):
        raise ChatError("Invalid session or message identifier.") from None


def read_json(path):
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    # A Windows reader can briefly deny replacement while loading the old
    # snapshot. Retry the atomic rename, never the action recorded in it.
    deadline = time.monotonic() + 0.5
    while True:
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


@dataclass(frozen=True)
class Session:
    provider: str
    id: str
    title: str
    project: str
    status: str
    transcript: Path | None = None
    managed: bool = False

    @property
    def key(self):
        return self.provider, self.id


@dataclass(frozen=True)
class Message:
    id: str
    role: str
    text: str
    at: float = 0


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item["text"] for item in content
            if isinstance(item, dict) and item.get("type") in {"text", "input_text", "output_text"}
            and isinstance(item.get("text"), str)
        )
    return ""


def codex_messages(items):
    messages = []
    for item in items:
        kind = item.get("type")
        if kind == "agentMessage":
            body, role = item.get("text", ""), "assistant"
        elif kind == "userMessage":
            body, role = text_content(item.get("content")), "user"
        else:
            continue
        if isinstance(body, str) and body.strip():
            messages.append(Message(str(item.get("id", "")), role, body))
    return messages


def claude_messages(path):
    if path is None:
        return []
    messages = []
    # Bounded tail: never load an entire long-running session or a screenshot.
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            start = max(0, stream.tell() - 2_000_000)
            stream.seek(start)
            if start:
                stream.readline()
            raw = stream.read(2_000_000)
    except OSError:
        raise ChatError("The Claude transcript is unavailable. Refresh the session list.") from None
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            continue  # A writer may not have finished the last record yet.
        try:
            item = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(item, dict) or item.get("isSidechain") or item.get("isMeta"):
            continue
        role = item.get("type")
        if role not in {"user", "assistant"}:
            continue
        payload = item.get("message")
        if not isinstance(payload, dict):
            continue
        body = text_content(payload.get("content"))
        if body.strip():
            try:
                at = datetime.fromisoformat(str(item.get("timestamp", "")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                at = 0
            messages.append(Message(str(item.get("uuid", "")), role, body, at))
    return messages[-100:]


def live_pids():
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
            errors="replace", timeout=5, **process_options(),
        )
        if result.returncode:
            return set()
        return {int(row[1]) for row in csv.reader(io.StringIO(result.stdout))
                if len(row) > 1 and row[1].isdigit()
                and row[0].lower() in {"claude.exe", "node.exe"}}
    except (OSError, subprocess.TimeoutExpired):
        return set()


def pid_alive(pid, pids=None):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        return pid in (live_pids() if pids is None else pids)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, OverflowError):
        return False


def claude_sessions(home=None):
    home = Path(home or os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    sessions = []
    pids = live_pids()
    for path in (home / "sessions").glob("*.json"):
        item = read_json(path)
        if item.get("kind") != "interactive" or not pid_alive(item.get("pid"), pids):
            continue
        if not isinstance(item.get("status"), str) or item["status"] not in {"idle", "busy"}:
            continue
        if not isinstance(item.get("cwd", ""), str):
            continue
        try:
            session_id = identifier(item.get("sessionId"))
        except ChatError:
            continue
        project = Path(item.get("cwd") or ".").name
        paths = list((home / "projects").glob("*/" + session_id + ".jsonl"))
        sessions.append(Session(
            "claude", session_id, str(item.get("name") or "Claude Code session"),
            project, item["status"], paths[0] if paths else None,
        ))
    return sessions


class ChatService:
    def __init__(self, state=CHAT_STATE, codex=None, claude_home=None):
        self.state = Path(state)
        self.codex = codex or CodexClient()
        self.claude_home = claude_home
        from .agent_sessions import AgentSessions
        self.agents = AgentSessions(self.state / "agents")

    def close(self):
        self.codex.close()

    def discover(self):
        found, notices = [], []
        try:
            for item in self.codex.sessions():
                found.append(Session(
                    "codex", identifier(item["id"]), str(item.get("name") or item.get("preview") or "Codex session")[:100],
                    Path(item.get("cwd") or ".").name, item.get("status", {}).get("type", "unknown"),
                ))
        except ChatError as error:
            notices.append(str(error))
        found.extend(claude_sessions(self.claude_home))
        owned = self.agents.discover()
        # Companion conversations keep stable local identities even while their
        # native CLI turn is finishing. Do not attach through the external bridge.
        native_ids = {read_json(self.agents.folder(s.id) / "session.json").get("native_id") for s in owned}
        found = [s for s in found if s.id not in native_ids]
        found.extend(owned)
        return found, notices

    def create(self, provider, *, title="Companion chat", startup="", creation_id=None):
        return self.agents.create(provider, title, startup=startup, creation_id=creation_id)

    def history(self, session):
        if session.managed:
            return self.agents.history(session)
        if session.provider == "codex":
            return codex_messages(self.codex.messages(session.id))
        messages = claude_messages(session.transcript)
        # Polling presents the request as a tool read in Claude's own transcript.
        # Merge the explicit human messages back into their chronological position.
        inbox = self.state / "claude" / identifier(session.id) / "inbox"
        for path in inbox.glob("*.json"):
            item = read_json(path)
            if isinstance(item.get("text"), str) and isinstance(item.get("created_at"), (int, float)):
                messages.append(Message(path.stem, "user", item["text"], item["created_at"]))
        return sorted(messages, key=lambda message: message.at)[-100:]

    def response_status(self, session, request_id):
        """Read completion without mistaking an owned CLI's progress for its reply."""
        if not session.managed:
            if session.provider == "claude":
                # Inbox entries appear in history before Claude polls them. Only its
                # explicit acknowledgement confirms that this request was handled.
                path = self.state / "claude" / identifier(session.id) / "claimed" / (identifier(request_id) + ".json")
                return read_json(path).get("status", "queued")
            return None
        request = self.agents.result(session.id, request_id)
        status = request.get("status", "unconfirmed")
        if status in {"queued", "running"} and time.time() - request.get("heartbeat", 0) > 30:
            return "interrupted"
        return status

    def send(self, session, body, request_id):
        body = body.strip()
        if not body or len(body) > MAX_MESSAGE or "\0" in body:
            raise ChatError(f"Enter a message between 1 and {MAX_MESSAGE} characters, without null characters.")
        session_id, request_id = identifier(session.id), identifier(request_id)
        if session.managed:
            return self.agents.send(session, body, request_id)
        current, _ = self.discover()
        if session.key not in {item.key for item in current}:
            raise ChatError("That session is no longer available. Refresh and select an open session.")
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        receipts = self.state / "outbox"
        receipts.mkdir(parents=True, exist_ok=True)
        receipt = receipts / (request_id + ".json")
        data = {"provider": session.provider, "session": session_id, "status": "sending"}
        try:
            # Exclusive creation makes retries across processes and restarts refuse.
            with receipt.open("x", encoding="utf-8") as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            raise ChatError("This message was already attempted. Check the terminal before sending again.") from None
        try:
            if session.provider == "codex":
                self.codex.send(session_id, body)
                status = "queued"
            elif session.provider == "claude":
                target = self.state / "claude" / session_id / "inbox" / (request_id + ".json")
                write_json(target, {"id": request_id, "text": body, "created_at": time.time()})
                status = "waiting for Claude to poll"
            else:
                raise ChatError("Unsupported agent provider.")
        except (ChatError, OSError):
            write_json(receipt, {**data, "status": "uncertain"})
            raise
        write_json(receipt, {**data, "status": status})
        return status


@contextmanager
def inbox_lock(folder):
    """One local poller/acknowledger per session; OS releases locks after a crash."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "poll.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ChatError("This session already has a poll in progress.") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def acknowledge_claude(session_id, request_id, *, state=CHAT_STATE):
    folder = Path(state) / "claude" / identifier(session_id)
    request_id = identifier(request_id)
    Path(state).mkdir(mode=0o700, parents=True, exist_ok=True)
    with inbox_lock(folder):
        incoming = read_json(folder / "incoming.json")
        if incoming.get("id") != request_id:
            raise ChatError("That message is not the current Claude request.")
        write_json(folder / "claimed" / (request_id + ".json"), {"status": "acknowledged"})
    return {"status": "acknowledged"}


def poll_claude(session_id, *, state=CHAT_STATE, wait=25, clock=time.monotonic, sleep=time.sleep):
    """Claim one request, keeping its contents out of terminal/CI output.

    Acknowledgment is explicit: a second poll never overwrites an unread request.
    Claim markers survive crashes and prevent automatic redelivery.
    """
    session_id = identifier(session_id)
    if not 0 <= wait <= 50:
        raise ChatError("Poll wait must be between 0 and 50 seconds.")
    Path(state).mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = Path(state) / "claude" / session_id
    with inbox_lock(folder):
        inbox, claims = folder / "inbox", folder / "claimed"
        inbox.mkdir(parents=True, exist_ok=True)
        claims.mkdir(parents=True, exist_ok=True)
        incoming = read_json(folder / "incoming.json")
        if incoming.get("id"):
            claim = read_json(claims / (identifier(incoming["id"]) + ".json"))
            if claim.get("status") != "acknowledged":
                return {"status": "awaiting_ack", "message": "The current incoming message is still available. Reply and acknowledge it before polling again."}
        deadline = clock() + wait
        while True:
            pending = sorted(inbox.glob("*.json"), key=lambda path: path.stat().st_mtime_ns)
            for path in pending:
                message = read_json(path)
                if not isinstance(message.get("text"), str) or message.get("id") != path.stem:
                    continue
                try:
                    with (claims / path.name).open("x", encoding="utf-8") as stream:
                        json.dump({"status": "claimed"}, stream)
                except FileExistsError:
                    continue
                write_json(folder / "incoming.json", message)
                return {"status": "received", "message": "Read the incoming.json file named in the window's connection instructions, then reply and acknowledge it."}
            if clock() >= deadline:
                return {"status": "waiting", "message": "No new chat message. Poll again when ready."}
            sleep(min(0.25, max(0, deadline - clock())))


def claude_connection_text(session):
    session_id = identifier(session.id)
    incoming = ROOT / ".runtime" / "chat" / "claude" / session_id / "incoming.json"
    return (
        "Use the WoW Helper chat window as input for this existing Claude session. "
        f"Use this working directory for the commands: {ROOT}\n\n"
        f"python -m wow_helper chat-poll --session {session_id} --wait 25\n\n"
        "When status is received, read "
        f"{incoming}, handle its text as my message, "
        "and reply normally in this session so the window can display the reply. "
        "After replying, acknowledge the id from that file with:\n\n"
        f"python -m wow_helper chat-ack --session {session_id} --request-id <id from incoming.json>\n\n"
        "An awaiting_ack result means finish and acknowledge the current incoming message first. "
        "Poll again after acknowledgment, or after a waiting result, while I use the chat window. "
        "Stop polling when I ask. Do not start a second Claude session. "
        "Chat is conversation only; it must not trigger game input."
    )
