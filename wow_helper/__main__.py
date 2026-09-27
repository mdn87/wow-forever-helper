"""Local CLI for explicit requests from a person or their voice-command adapter."""

import argparse
import json
from pathlib import Path
import sqlite3

from .assist import ACTION, Assistant, AssistError


def main(argv=None):
    parser = argparse.ArgumentParser(description="WoW assistive input: one human request, one mapped key chord.")
    commands = parser.add_subparsers(dest="command", required=True)
    bind = commands.add_parser("bind", help="Map a supported spell to its existing in-game keybind")
    bind.add_argument("action", choices=[ACTION])
    bind.add_argument("--key", required=True)
    commands.add_parser("enable", help="Enable explicit assistive requests")
    commands.add_parser("stop", help="Disable subsequent input; cannot undo a key already sent")
    commands.add_parser("status", help="Show enabled state and local key mappings")
    request = commands.add_parser("request", help="Preview a transcribed command; add --execute to send once")
    request.add_argument("text")
    request.add_argument("--execute", action="store_true")
    request.add_argument("--request-id", help="Stable event ID; reuse it for every delivery of the same utterance")
    request.add_argument("--issued-at", type=float, help="Unix timestamp of the original human command (15 second expiry)")
    args = parser.parse_args(argv)
    try:
        desktop = None
        if args.command == "request" and args.execute:
            from .windows_input import WindowsInput
            desktop = WindowsInput()
        # Anchor to the checkout, not caller CWD: retries share one deduplication store.
        assistant = Assistant(Path(__file__).resolve().parents[1] / ".runtime" / "assist.sqlite", desktop)
        if args.command == "bind":
            result = assistant.bind(args.action, args.key)
        elif args.command in {"enable", "stop"}:
            result = assistant.enable(args.command == "enable")
        elif args.command == "status":
            result = assistant.status()
        else:
            result = assistant.request(args.text, execute=args.execute, request_id=args.request_id, issued_at=args.issued_at)
        print(json.dumps(result))
        return 0
    except AssistError as error:
        print(json.dumps({"status": "refused", "message": str(error)}))
        return 2
    except (OSError, sqlite3.Error):
        print(json.dumps({"status": "error", "message": "Local input or state storage is unavailable; no automatic retry."}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
