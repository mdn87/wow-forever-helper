"""Local CLI for explicit requests from a person or their voice-command adapter."""

import argparse
import json
from pathlib import Path
import sqlite3

from .assist import ACTION, Assistant, AssistError

SETTINGS = Path(__file__).resolve().parents[1] / ".runtime" / "companion.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description="WoW Forever Helper: one human request, one mapped key chord; plus a read-only quest companion.")
    commands = parser.add_subparsers(dest="command", required=True)
    bind = commands.add_parser("bind", help="Map a supported spell to its existing in-game keybind")
    bind.add_argument("action", choices=[ACTION])
    bind.add_argument("--key", required=True)
    commands.add_parser("enable", help="Enable explicit assistive requests")
    commands.add_parser("stop", help="Disable subsequent input; cannot undo a key already sent")
    stub = commands.add_parser("stub", help="Record key presses instead of sending them (testing without a character)")
    stub.add_argument("state", choices=["on", "off"])
    commands.add_parser("status", help="Show enabled state, stub mode and local key mappings")
    request = commands.add_parser("request", help="Preview a transcribed command; add --execute to send once")
    request.add_argument("text")
    request.add_argument("--execute", action="store_true")
    request.add_argument("--request-id", help="Stable event ID; reuse it for every delivery of the same utterance")
    request.add_argument("--issued-at", type=float, help="Unix timestamp of the original human command (15 second expiry)")
    quests = commands.add_parser("quests", help="List the current quests from the companion addon, with a suggested order")
    quests.add_argument("--file", help="Read this SavedVariables file instead of searching the install")
    quests.add_argument("--wow-root", help="WoW install folder (the one holding _retail_ or _classic_ folders); remembered")
    quests.add_argument("--text", action="store_true", help="Print readable lines instead of JSON")
    addon = commands.add_parser("install-addon", help="Copy the read-only companion addon into the game's AddOns folder")
    addon.add_argument("--wow-root", help="WoW install folder; remembered")
    addon.add_argument("--flavor", help="Only this game folder, for example _classic_beta_")
    args = parser.parse_args(argv)
    if args.command in {"quests", "install-addon"}:
        return companion(args)
    try:
        # Anchor to the checkout, not caller CWD: retries share one deduplication store.
        store = Path(__file__).resolve().parents[1] / ".runtime" / "assist.sqlite"
        assistant = Assistant(store, None)
        if args.command == "request" and args.execute:
            if assistant.stubbed():
                from .stub_input import StubInput
                assistant.desktop = StubInput(assistant.path.parent / "stub-presses.jsonl")
            else:
                from .windows_input import WindowsInput
                assistant.desktop = WindowsInput()
        if args.command == "bind":
            result = assistant.bind(args.action, args.key)
        elif args.command in {"enable", "stop"}:
            result = assistant.enable(args.command == "enable")
        elif args.command == "stub":
            result = assistant.set_stub(args.state == "on")
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


def companion(args, *, now=None, wait=1.0):
    """Quest reading and addon install. Read-only toward the game; never touches input."""
    from . import quests, wtf
    from .savedvars import SavedVariablesError, read_stable
    settings = SETTINGS
    try:
        if args.wow_root:
            wtf.save_settings(settings, wow_root=str(Path(args.wow_root).resolve()))
        install_roots = wtf.roots(wtf.load_settings(settings).get("wow_root"))
        if args.command == "install-addon":
            installed = wtf.install_addon(install_roots, args.flavor)
            if not installed:
                raise SavedVariablesError("No WoW install that has been run was found; pass --wow-root.")
            print(json.dumps({"status": "installed", "flavors": installed,
                              "next": "Enable WoW Companion at character select, then /reload once."}))
            return 0
        if args.file:
            path, flavor = Path(args.file), wtf.flavor_of(args.file)
        else:
            found = wtf.newest(install_roots)
            if not found:
                raise SavedVariablesError("No quest snapshot found. Install the addon, then /reload in game.")
            flavor, path = found
        parsed, mtime = read_stable(path, wait=wait)
        result = quests.report(quests.load(parsed), mtime, flavor=flavor, now=now)
        print(quests.as_text(result) if args.text else json.dumps(result))
        return 0
    except SavedVariablesError as error:
        print(json.dumps({"status": "refused", "message": str(error)}))
        return 2
    except OSError:
        print(json.dumps({"status": "error", "message": "The WoW folder could not be read or written."}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
