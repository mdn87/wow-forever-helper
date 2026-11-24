"""Validated, single-action default-browser dispatch with durable attempt markers and receipts.

This module enforces strict model-requested URL validation, executes default-browser launches
only through a short-lived bounded helper subprocess (`python -m wow_helper.browser_links`),
persists exclusive attempt markers and atomic terminal receipts separately from request
heartbeats, and reconciles interrupted attempts conservatively to `unknown` without replay.
"""

from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata
from urllib.parse import urlsplit
import uuid
import webbrowser

from .chat import ChatError, ROOT, identifier, read_json, write_json
from .codex_chat import process_options
from .window_state import LayoutLock

MAX_URL_LENGTH = 4096
MAX_TITLE_LENGTH = 160
MAX_ANSWER_LENGTH = 200_000
HELPER_TIMEOUT = 5.0
TERMINAL_OUTCOMES = ("launch_accepted", "failed", "unknown", "stopped")

_BAD_UNICODE_CATEGORIES = {"Cc", "Cf", "Cs", "Zl", "Zp"}
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_PERCENT_TOKEN = re.compile(r"%([0-9A-Fa-f]{2})?")

CHAT_BROWSER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "browser_request"],
    "properties": {
        "answer": {"type": "string", "maxLength": MAX_ANSWER_LENGTH},
        "browser_request": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["url", "title"],
                    "properties": {
                        "url": {"type": "string", "maxLength": MAX_URL_LENGTH},
                        "title": {"type": "string", "maxLength": MAX_TITLE_LENGTH},
                    },
                },
            ]
        },
    },
}

OUTCOME_TEXT = {
    "launch_accepted": "Sent link to browser. Page loading and visibility are not verified.",
    "failed": "Could not send link to browser. No successful launch was reported.",
    "unknown": "Opening status unknown. The page may already be open; opening it again may create a duplicate tab.",
    "stopped": "Automatic opening stopped — use the link.",
    "manual_only": "Manual links only — automatic opening unavailable.",
}

ACTION_BUTTON_LABEL = {
    "launch_accepted": "Open link",
    "failed": "Try opening link again",
    "unknown": "Open anyway (may open duplicate)",
    "stopped": "Open link",
    "manual_only": "Open link",
}


class BrowserLinkError(ChatError):
    """Refusal or validation error for a model-requested browser link."""


class BrowserReplyError(ChatError):
    """Structured reply validation error, optionally preserving usable answer text."""

    def __init__(self, message, *, usable_answer=""):
        super().__init__(message)
        self.usable_answer = usable_answer


@dataclass(frozen=True)
class ValidatedLink:
    url: str
    destination: str
    scheme: str
    host: str
    port: int | None


@dataclass(frozen=True)
class ValidatedRequest:
    link: ValidatedLink
    title: str


def _has_forbidden_chars(text):
    for ch in text:
        code = ord(ch)
        if code < 0x20 or code == 0x7F or ch.isspace() or ch == "\\":
            return True
        if unicodedata.category(ch) in _BAD_UNICODE_CATEGORIES:
            return True
    return False


def _validate_percent_escapes(text):
    for match in _PERCENT_TOKEN.finditer(text):
        if match.group(1) is None:
            return False
    return True


def sanitize_title(raw):
    """Strip control/format/bidi characters from a model-supplied title and render plain text."""
    if not isinstance(raw, str):
        return ""
    cleaned = []
    for ch in raw:
        if ch in "\r\n\t":
            cleaned.append(" ")
            continue
        code = ord(ch)
        if code < 0x20 or code == 0x7F:
            continue
        if unicodedata.category(ch) in _BAD_UNICODE_CATEGORIES:
            continue
        cleaned.append(ch)
    return " ".join("".join(cleaned).split())[:MAX_TITLE_LENGTH]


def validate_browser_url(raw):
    """Strictly parse and normalize a public HTTP/HTTPS URL for model-requested browser dispatch."""
    if not isinstance(raw, str) or not raw:
        raise BrowserLinkError("The requested link is empty.")
    if len(raw) > MAX_URL_LENGTH:
        raise BrowserLinkError("The requested link exceeds the 4,096-character limit.")
    if _has_forbidden_chars(raw):
        raise BrowserLinkError("The requested link contains unsupported whitespace, control, or backslash characters.")
    try:
        parsed = urlsplit(raw)
    except ValueError:
        raise BrowserLinkError("The requested link could not be parsed.") from None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise BrowserLinkError("Only HTTP and HTTPS web links are permitted.")
    if not parsed.netloc:
        raise BrowserLinkError("The requested link has no hostname.")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise BrowserLinkError("Links with embedded credentials are not permitted.")

    netloc = parsed.netloc
    port = None
    if netloc.startswith("["):
        end = netloc.find("]")
        if end == -1:
            raise BrowserLinkError("The requested IPv6 host is malformed.")
        raw_host = netloc[1:end]
        rest = netloc[end + 1:]
        is_bracketed = True
    else:
        is_bracketed = False
        if ":" in netloc:
            raw_host, port_part = netloc.rsplit(":", 1)
            rest = ":" + port_part
        else:
            raw_host, rest = netloc, ""
    if rest:
        if not rest.startswith(":") or not rest[1:].isdigit():
            raise BrowserLinkError("The requested link port is invalid.")
        port = int(rest[1:])
        if not 1 <= port <= 65535:
            raise BrowserLinkError("The requested link port is out of range.")
    if not raw_host or "%" in raw_host:
        raise BrowserLinkError("The requested hostname is missing or percent-encoded.")

    # Reject literal non-global / local / private IP addresses and bracketed hosts.
    ip_obj = None
    try:
        ip_obj = ipaddress.ip_address(raw_host)
    except ValueError:
        if is_bracketed:
            raise BrowserLinkError("Bracketed hostnames must be valid IPv6 addresses.") from None

    if ip_obj is not None:
        if (ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local
                or ip_obj.is_multicast or ip_obj.is_reserved or ip_obj.is_unspecified
                or not ip_obj.is_global):
            raise BrowserLinkError("Local, private, and non-public IP addresses are not permitted.")
        if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
            mapped = ip_obj.ipv4_mapped
            if (mapped.is_private or mapped.is_loopback or mapped.is_link_local
                    or mapped.is_multicast or mapped.is_reserved or mapped.is_unspecified
                    or not mapped.is_global):
                raise BrowserLinkError("Local, private, and non-public IP addresses are not permitted.")
        ascii_host = f"[{ip_obj.compressed}]" if isinstance(ip_obj, ipaddress.IPv6Address) else ip_obj.compressed
    else:
        lowered = raw_host.lower()
        if lowered == "localhost" or lowered.endswith(".localhost") or lowered.endswith(".local"):
            raise BrowserLinkError("Localhost and local-network hostnames are not permitted.")
        if raw_host.startswith(".") or raw_host.endswith(".") or ".." in raw_host:
            raise BrowserLinkError("The requested hostname has empty or trailing labels.")
        try:
            ascii_host = raw_host.encode("idna").decode("ascii").lower()
            ascii_host.encode("ascii").decode("idna")
        except (UnicodeError, ValueError):
            raise BrowserLinkError("The requested hostname failed IDNA normalization.") from None
        if len(ascii_host) > 253 or "." not in ascii_host:
            raise BrowserLinkError("The requested hostname must be a valid public domain name.")
        labels = ascii_host.split(".")
        if any(not _DNS_LABEL.fullmatch(label) for label in labels):
            raise BrowserLinkError("The requested hostname contains invalid DNS labels.")
        if labels[-1] in {"localhost", "local", "internal", "arpa"}:
            raise BrowserLinkError("Local or internal domain suffixes are not permitted.")

    for part in (parsed.path, parsed.query, parsed.fragment):
        if not _validate_percent_escapes(part):
            raise BrowserLinkError("The requested link contains a malformed percent escape.")

    default_port = 80 if scheme == "http" else 443
    netloc_norm = ascii_host if (port is None or port == default_port) else f"{ascii_host}:{port}"
    destination = f"{scheme}://{netloc_norm}"
    path = parsed.path or ""
    if path and not path.startswith("/"):
        raise BrowserLinkError("The requested link path is malformed.")
    normalized = destination + path
    if parsed.query:
        normalized += "?" + parsed.query
    if parsed.fragment:
        normalized += "#" + parsed.fragment
    if len(normalized) > MAX_URL_LENGTH:
        raise BrowserLinkError("The normalized link exceeds the 4,096-character limit.")
    return ValidatedLink(url=normalized, destination=destination, scheme=scheme,
                         host=ascii_host, port=None if port == default_port else port)


def validate_browser_reply(data):
    """Validate a complete `chat_browser_v1` JSON object before any display truncation."""
    if not isinstance(data, dict):
        raise BrowserReplyError("The structured reply was not a JSON object.")
    usable = data.get("answer") if (isinstance(data.get("answer"), str)
                                    and len(data.get("answer")) <= MAX_ANSWER_LENGTH
                                    and "\0" not in data.get("answer")) else ""
    if set(data) != {"answer", "browser_request"}:
        raise BrowserReplyError("The structured reply contained unexpected or missing fields.", usable_answer=usable)
    answer = data["answer"]
    if not isinstance(answer, str) or len(answer) > MAX_ANSWER_LENGTH or "\0" in answer:
        raise BrowserReplyError("The reply answer exceeded limits or contained invalid characters.")
    raw_req = data["browser_request"]
    if raw_req is None:
        return answer, None
    if not isinstance(raw_req, dict) or set(raw_req) != {"url", "title"}:
        raise BrowserReplyError(
            "The browser link request was malformed; only one object with url and title is permitted.",
            usable_answer=answer,
        )
    raw_url, raw_title = raw_req["url"], raw_req["title"]
    if not isinstance(raw_url, str) or len(raw_url) > MAX_URL_LENGTH:
        raise BrowserReplyError("The requested link URL exceeded limits or had an invalid type.", usable_answer=answer)
    if not isinstance(raw_title, str) or len(raw_title) > MAX_TITLE_LENGTH:
        raise BrowserReplyError("The requested link title exceeded limits or had an invalid type.", usable_answer=answer)
    try:
        link = validate_browser_url(raw_url)
    except BrowserLinkError as error:
        raise BrowserReplyError(str(error), usable_answer=answer) from None
    return answer, ValidatedRequest(link=link, title=sanitize_title(raw_title))


def launch_url(url, *, timeout=HELPER_TIMEOUT, popen=None):
    """Launch a validated URL via a short-lived bounded helper subprocess (`shell=False`)."""
    link = validate_browser_url(url)
    spawn = popen or subprocess.Popen
    try:
        proc = spawn(
            [sys.executable, "-m", "wow_helper.browser_links"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            **process_options(),
        )
    except OSError:
        return "failed"
    try:
        proc.communicate(input=link.url.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.communicate(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return "unknown"
    except OSError:
        return "unknown"
    if proc.returncode == 0:
        return "launch_accepted"
    if proc.returncode == 2:
        return "failed"
    return "unknown"


def _links_dir(folder):
    return Path(folder) / "browser-links"


def attempt_marker_path(folder, request_id):
    return _links_dir(folder) / (identifier(request_id) + ".attempt.json")


def receipt_path(folder, request_id):
    return _links_dir(folder) / (identifier(request_id) + ".receipt.json")


def read_receipt(folder, request_id):
    """Read a persisted receipt, falling back conservatively to unknown if a torn/orphan attempt marker exists."""
    rpath = receipt_path(folder, request_id)
    if rpath.exists():
        data = read_json(rpath)
        if isinstance(data, dict) and data.get("outcome") in TERMINAL_OUTCOMES:
            return data
    apath = attempt_marker_path(folder, request_id)
    if apath.exists():
        marker = read_json(apath)
        return {
            "session_id": marker.get("session_id", ""),
            "request_id": identifier(request_id),
            "outcome": "unknown",
            "url": marker.get("url", ""),
            "destination": marker.get("destination", ""),
            "title": marker.get("title", ""),
            "message": OUTCOME_TEXT["unknown"],
            "reconciled": False,
        }
    return None


def write_terminal_receipt(folder, session_id, request_id, outcome, link, title, *, extra=None):
    """Atomically write a terminal receipt without overwriting an already-recorded terminal outcome."""
    if outcome not in TERMINAL_OUTCOMES:
        raise BrowserLinkError("Unsupported browser action outcome.")
    rpath = receipt_path(folder, request_id)
    if rpath.exists():
        existing = read_json(rpath)
        if existing.get("outcome") in TERMINAL_OUTCOMES:
            return existing
    record = {
        "version": 1,
        "session_id": identifier(session_id),
        "request_id": identifier(request_id),
        "outcome": outcome,
        "url": link.url if isinstance(link, ValidatedLink) else str(link or ""),
        "destination": link.destination if isinstance(link, ValidatedLink) else "",
        "title": sanitize_title(title),
        "message": OUTCOME_TEXT[outcome],
        "at": time.time(),
    }
    if extra:
        record.update(extra)
    write_json(rpath, record)
    return record


def claim_attempt(folder, session_id, request_id, link, title):
    """Exclusively create and fsync the per-request attempt marker before any external launch."""
    directory = _links_dir(folder)
    directory.mkdir(parents=True, exist_ok=True)
    apath = attempt_marker_path(folder, request_id)
    payload = {
        "version": 1,
        "status": "attempting",
        "session_id": identifier(session_id),
        "request_id": identifier(request_id),
        "url": link.url,
        "destination": link.destination,
        "title": sanitize_title(title),
        "at": time.time(),
    }
    with apath.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    return apath


def reconcile_session_links(folder, session_id):
    """Reconcile any orphaned attempt marker to durable `unknown` when no live worker owns run.json."""
    folder = Path(folder)
    directory = _links_dir(folder)
    if not directory.is_dir():
        return []
    try:
        worker_lock = LayoutLock(folder / "run.json")
    except ChatError:
        # A live worker currently holds run.json; leave its in-progress attempt untouched.
        return []
    reconciled = []
    try:
        for apath in sorted(directory.glob("*.attempt.json")):
            stem = apath.name.removesuffix(".attempt.json")
            if stem.startswith("manual-"):
                continue
            try:
                req_id = identifier(stem)
            except ChatError:
                continue
            rpath = receipt_path(folder, req_id)
            if rpath.exists() and read_json(rpath).get("outcome") in TERMINAL_OUTCOMES:
                continue
            marker = read_json(apath)
            record = {
                "version": 1,
                "session_id": identifier(session_id),
                "request_id": req_id,
                "outcome": "unknown",
                "url": marker.get("url", "") if isinstance(marker, dict) else "",
                "destination": marker.get("destination", "") if isinstance(marker, dict) else "",
                "title": sanitize_title(marker.get("title", "")) if isinstance(marker, dict) else "",
                "message": OUTCOME_TEXT["unknown"],
                "reconciled": True,
                "at": time.time(),
            }
            try:
                write_json(rpath, record)
                reconciled.append(record)
            except OSError:
                # Retain the attempt marker so read_receipt conservatively reports Opening status unknown.
                reconciled.append({**record, "reconciled": False})
    finally:
        worker_lock.close()
    return reconciled


def manual_open_link(folder, session_id, url, title="", *, action_id=None, launcher=None):
    """Explicit player-initiated browser open with its own fresh ID and double-click deduplication."""
    link = validate_browser_url(url)
    clean_title = sanitize_title(title)
    act_id = identifier(action_id or uuid.uuid4())
    directory = _links_dir(folder)
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / f"manual-{act_id}.attempt.json"
    try:
        with marker.open("x", encoding="utf-8") as stream:
            json.dump({"version": 1, "action_id": act_id, "session_id": identifier(session_id),
                       "url": link.url, "destination": link.destination, "title": clean_title, "at": time.time()},
                      stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise BrowserLinkError("That manual open click was already handled.") from None
    except OSError:
        raise BrowserLinkError("Could not record this manual open action. Nothing was launched.") from None
    outcome = (launcher or launch_url)(link.url)
    return {
        "action_id": act_id,
        "outcome": outcome,
        "url": link.url,
        "destination": link.destination,
        "title": clean_title,
        "message": OUTCOME_TEXT[outcome],
    }


def _helper_main():
    raw = sys.stdin.read(MAX_URL_LENGTH + 1)
    try:
        link = validate_browser_url(raw.strip())
    except BrowserLinkError:
        return 2
    try:
        opened = bool(webbrowser.open(link.url, new=2, autoraise=False))
    except Exception:
        return 2
    return 0 if opened else 2


if __name__ == "__main__":
    raise SystemExit(_helper_main())
