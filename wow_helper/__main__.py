"""Local CLI for explicit requests from a person or their voice-command adapter."""

import argparse
import json
from pathlib import Path
import sqlite3
import time

from .assist import ACTION, Assistant, AssistError

SETTINGS = Path(__file__).resolve().parents[1] / ".runtime" / "companion.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description="WoW Forever Helper: one human request, one mapped key chord; plus a read-only quest companion.")
    commands = parser.add_subparsers(dest="command", required=True)
    chat = commands.add_parser("chat", help="Open or reveal persistent companion windows")
    chat.add_argument("--restart", action="store_true", help="Save and restart the running companion to load updates (Windows)")
    chat.add_argument("--hotkey", choices=["H", "F10"], default="H",
                      help="Windows reopen shortcut: Ctrl+Alt+H (default) or Ctrl+Alt+F10")
    poll = commands.add_parser("chat-poll", help="Read one queued chat message from an existing Claude session")
    poll.add_argument("--session", required=True, help="Session selected in the chat window's connection instructions")
    poll.add_argument("--wait", type=float, default=25, help="Wait for a message, at most 50 seconds")
    ack = commands.add_parser("chat-ack", help="Acknowledge a chat message after Claude has replied")
    ack.add_argument("--session", required=True)
    ack.add_argument("--request-id", required=True)
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
    quests.add_argument("--flavor", help="Search only this game folder for this report, for example _classic_beta_; cannot combine with --file")
    quests.add_argument("--wow-root", help="WoW install folder (the one holding _retail_ or _classic_ folders); remembered")
    quests.add_argument("--text", action="store_true", help="Print readable lines instead of JSON")
    character = commands.add_parser("character", help="Show gold, rested XP, gear, durability, and bag space from the companion addon")
    character.add_argument("--file", help="Read this SavedVariables file instead of searching the install")
    character.add_argument("--flavor", help="Search only this game folder for this report, for example _classic_beta_; cannot combine with --file")
    character.add_argument("--wow-root", help="WoW install folder; remembered")
    character.add_argument("--text", action="store_true", help="Print readable lines instead of JSON")
    check = commands.add_parser("check-snapshot", help="Report which addon assumptions the newest snapshot confirms; prints no names or paths")
    check.add_argument("--file", help="Read this SavedVariables file instead of searching the install")
    check.add_argument("--flavor", help="Search only this game folder for this report, for example _classic_beta_; cannot combine with --file")
    check.add_argument("--wow-root", help="WoW install folder; remembered")
    check.add_argument("--text", action="store_true", help="Print readable lines instead of JSON")
    addon = commands.add_parser("install-addon", help="Copy the read-only companion addon into the game's AddOns folder")
    addon.add_argument("--wow-root", help="WoW install folder; remembered")
    addon.add_argument("--flavor", help="Only this game folder, for example _classic_beta_")
    args = parser.parse_args(argv)
    if args.command in {"chat", "chat-poll", "chat-ack"}:
        from .chat import ChatError, acknowledge_claude, poll_claude
        try:
            if args.command == "chat":
                from .chat_window import launch
                launch(hotkey=args.hotkey, restart=args.restart)
            elif args.command == "chat-poll":
                print(json.dumps(poll_claude(args.session, wait=args.wait)))
            else:
                print(json.dumps(acknowledge_claude(args.session, args.request_id)))
            return 0
        except ChatError as error:
            print(json.dumps({"status": "refused", "message": str(error)}))
            return 2
        except OSError:
            print(json.dumps({"status": "error", "message": "Local chat storage is unavailable."}))
            return 3
    if args.command in {"quests", "character", "check-snapshot", "install-addon"}:
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
    """Quest and character reading, and addon install. Read-only toward the game; never touches input."""
    from . import character, check, quests, wtf
    from .savedvars import SavedVariablesError, read_stable
    settings = SETTINGS
    try:
        if args.command != "install-addon" and args.file and args.flavor is not None:
            raise SavedVariablesError("Choose either an explicit snapshot file or a game edition, not both.")
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
            found = wtf.newest(install_roots, only=args.flavor)
            if not found:
                if args.flavor is not None:
                    raise SavedVariablesError("No snapshot found for the selected game edition. Install the addon there, then /reload in that edition.")
                raise SavedVariablesError("No quest snapshot found. Install the addon, then /reload in game.")
            flavor, path = found
        parsed, mtime = read_stable(path, wait=wait)
        if args.command == "check-snapshot":
            result = check.report(parsed, mtime, flavor=flavor, now=time.time() if now is None else now)
            print(check.as_text(result) if args.text else json.dumps(result))
            return 0
        if args.command == "character":
            result = character.report(parsed, mtime, flavor=flavor, now=time.time() if now is None else now)
            print(character.as_text(result) if args.text else json.dumps(result))
            return 0
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
