"""Local CLI for explicit requests from a person or their voice-command adapter."""

import argparse
import json
from pathlib import Path
import sqlite3
import time

from .assist import ACTION, Assistant, AssistError

SETTINGS = Path(__file__).resolve().parents[1] / ".runtime" / "companion.json"
# live_test_guide.MOMENTS keys, listed here so building the parser imports nothing more.
LIVE_TEST_MOMENTS = ("login", "play", "fight", "town", "logout", "anytime")


def main(argv=None):
    parser = argparse.ArgumentParser(description="WoW Forever Helper: one human request, one mapped key chord; plus a read-only quest companion.")
    commands = parser.add_subparsers(dest="command", required=True)
    usage = commands.add_parser("usage-study", help="Start, stop or report local companion action counts")
    usage.add_argument("action", choices=["start", "stop", "report"])
    usage.add_argument("--days", type=int, default=7, help="Testing period, 1 to 30 days; defaults to 7")
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
    quests.add_argument("--flavor", help="Search only this game folder for this report, for example _forever_; cannot combine with --file")
    quests.add_argument("--wow-root", help="WoW install folder (the one holding _retail_ or _classic_ folders); remembered")
    quests.add_argument("--enrich-bnet", action="store_true", help="Attach Forever quest rewards and repeatability from Battle.net API")
    quests.add_argument("--text", action="store_true", help="Print readable lines instead of JSON")
    character = commands.add_parser("character", help="Show gold, rested XP, gear, durability, and bag space from the companion addon")
    character.add_argument("--file", help="Read this SavedVariables file instead of searching the install")
    character.add_argument("--flavor", help="Search only this game folder for this report, for example _forever_; cannot combine with --file")
    character.add_argument("--wow-root", help="WoW install folder; remembered")
    character.add_argument("--enrich-bnet", action="store_true", help="Resolve equipped item IDs via Battle.net Forever item API (with 404 fallback)")
    character.add_argument("--text", action="store_true", help="Print readable lines instead of JSON")
    market = commands.add_parser("market", help="Read-only Forever Auction House and commodity price lookup via Battle.net API")
    market.add_argument("--region", default="us", choices=("us", "eu", "kr", "tw"))
    market.add_argument("--ruleset", type=int, default=1, help="Forever ruleset ID (default 1)")
    market.add_argument("--house", type=int, help="Auction house ID from --list-houses")
    market.add_argument("--item", type=int, help="Numeric item ID to price")
    market.add_argument("--query", help="Item name search query")
    market.add_argument("--list-rulesets", action="store_true", help="List Forever rulesets")
    market.add_argument("--list-houses", action="store_true", help="List auction houses for --ruleset")
    market.add_argument("--compare-houses", action="store_true", help="Compare one item across auction houses for --ruleset (useful for matching your in-game AH)")
    market.add_argument("--faction", choices=("alliance", "horde", "blackwater"), help="Filter --compare-houses to one auction house faction")
    market.add_argument("--include-auctions", action="store_true", help="Also scan non-commodity auctions during --compare-houses")
    market.add_argument("--ttl", type=int, default=900, help="Cache TTL in seconds (max 30 days)")
    market.add_argument("--cache-only", action="store_true", help="Read local runtime cache only; do not call network")
    market.add_argument("--force-refresh", action="store_true", help="Bypass fresh cache and fetch anew")
    market.add_argument("--text", action="store_true", help="Print readable lines instead of JSON")
    catalog = commands.add_parser("catalog", help="Read-only Forever ruleset status and static reference catalogs via Battle.net API")
    catalog.add_argument("--region", default="us", choices=("us", "eu", "kr", "tw"))
    catalog_actions = catalog.add_subparsers(dest="catalog_action", required=True)
    cat_rs = catalog_actions.add_parser("ruleset", help="Show Forever ruleset UP status")
    cat_rs.add_argument("--ruleset", type=int, help="Specific ruleset ID (omit for all)")
    cat_rs.add_argument("--cache-only", action="store_true")
    cat_rs.add_argument("--force-refresh", action="store_true")
    cat_rs.add_argument("--text", action="store_true")
    cat_list = catalog_actions.add_parser("list", help="List or search one Forever static catalog")
    cat_list.add_argument("kind", choices=("races", "specs", "professions", "item-classes", "achievements", "mounts", "pets", "creature-families", "quest-areas", "quest-categories"))
    cat_list.add_argument("--query", help="Optional case-insensitive filter")
    cat_list.add_argument("--limit", type=int, default=20)
    cat_list.add_argument("--cache-only", action="store_true")
    cat_list.add_argument("--force-refresh", action="store_true")
    cat_list.add_argument("--text", action="store_true")
    live_test = commands.add_parser("live-test", help="Spoken walkthrough and local result log for the runbook's play-time checks")
    live_test_actions = live_test.add_subparsers(dest="live_test_action", required=True)
    lt_list = live_test_actions.add_parser("list", help="List all play-time tests and current status")
    lt_list.add_argument("--chip", help="Filter by Dias chip number, for example 21, 22, or 23")
    lt_list.add_argument("--moment", choices=LIVE_TEST_MOMENTS, help="Filter by moment in play")
    lt_list.add_argument("--text", action="store_true")
    lt_next = live_test_actions.add_parser("next", help="Print the spoken instructions for the next pending test")
    lt_next.add_argument("--text", action="store_true")
    lt_goto = live_test_actions.add_parser("goto", help="Select a test by number and print its spoken instructions")
    lt_goto.add_argument("number", type=int)
    lt_goto.add_argument("--text", action="store_true")
    lt_moment = live_test_actions.add_parser("moment", help="Select the first open test for a moment in play and print it")
    lt_moment.add_argument("moment", choices=LIVE_TEST_MOMENTS)
    lt_moment.add_argument("--text", action="store_true")
    lt_edition = live_test_actions.add_parser("edition", help="Offer one edition's tests and those that need no game, or any")
    lt_edition.add_argument("edition", choices=("retail", "forever", "any"))
    lt_edition.add_argument("--text", action="store_true")
    lt_rec = live_test_actions.add_parser("record", help="Record pass, fail, or skipped for a test")
    lt_rec.add_argument("outcome", choices=("pass", "fail", "skipped"))
    lt_rec.add_argument("--id", dest="item_id", help="Test number or runbook ID, for example 7 or 2.15 (defaults to the current test)")
    lt_rec.add_argument("--note", default="", help="Optional short observation note (never include real character names)")
    lt_rec.add_argument("--text", action="store_true")
    lt_status = live_test_actions.add_parser("status", help="Show live-test pass/fail/pending counts")
    lt_status.add_argument("--text", action="store_true")
    live_test_actions.add_parser("reset", help="Clear saved local live-test results")
    check = commands.add_parser("check-snapshot", help="Report which addon assumptions the newest snapshot confirms; prints no names or paths")
    check.add_argument("--file", help="Read this SavedVariables file instead of searching the install")
    check.add_argument("--flavor", help="Search only this game folder for this report, for example _forever_; cannot combine with --file")
    check.add_argument("--wow-root", help="WoW install folder; remembered")
    check.add_argument("--text", action="store_true", help="Print readable lines instead of JSON")
    addon = commands.add_parser("install-addon", help="Copy the read-only companion addon into the game's AddOns folder")
    addon.add_argument("--wow-root", help="WoW install folder; remembered")
    addon.add_argument("--flavor", help="Only this game folder, for example _forever_")
    addon.add_argument("--probe", action="store_true", help="Install the separate context-channel probe addon instead")
    probe = commands.add_parser("context-probe", help="Read one context packet from the clipboard, the game window or an image and report what arrived; prints no game text unless asked")
    probe.add_argument("--source", choices=("clipboard", "window", "image"), required=True)
    probe.add_argument("--flavor", help="Game folder to capture for --source window, for example _retail_ or _forever_")
    probe.add_argument("--image", help="Image file for --source image")
    probe.add_argument("--corner", choices=("topleft", "topright", "bottomleft", "bottomright", "full"), default="topleft", help="Where on the frame to look for the strip")
    probe.add_argument("--max-age", type=int, default=120, help="Seconds after which a packet counts as stale")
    probe.add_argument("--show", action="store_true", help="Include the cleaned packet content in the report")
    probe.add_argument("--no-state", action="store_true", help="Do not remember the last packet, so every run is treated as the first")
    probe.add_argument("--text", action="store_true", help="Print readable lines instead of JSON")
    recording = commands.add_parser("recording-observe", help="Measure a selected recording directory; output omits names and paths")
    recording.add_argument("--directory", required=True, help="Local source directory to observe without modifying files")
    recording.add_argument("--seconds", type=int, default=60, help="Observation duration, 1 to 3600 seconds")
    recording.add_argument("--interval", type=int, default=2, help="Metadata polling interval, 1 to 60 seconds")
    recording.add_argument("--quiet-seconds", type=int, default=10, help="Quiet period before an optional format probe, at least two intervals")
    recording.add_argument("--probe-format", action="store_true", help="Allow bounded ffprobe metadata reads after quiescence; finalization remains unverified")
    publications = commands.add_parser("published-tools", help="Manage explicit conversation-scoped Journal publications and the local read-only tool server")
    publication_actions = publications.add_subparsers(dest="publication_action", required=True)
    grant = publication_actions.add_parser("create", help="Create a private launch descriptor; provider integration remains unverified")
    grant.add_argument("--provider", choices=("codex", "claude"), required=True)
    grant.add_argument("--session-id", required=True, help="The selected source conversation UUID; never printed")
    grant.add_argument("--hours", type=int, default=24)
    publish = publication_actions.add_parser("publish", help="Explicitly publish one saved, reviewed Journal evidence selection")
    publish.add_argument("--grant-id", required=True)
    publish.add_argument("--journal-id", required=True)
    publish.add_argument("--note-id", required=True)
    revoke = publication_actions.add_parser("revoke", help="Remove future tool access; retained notes and publication snapshots are kept")
    revoke.add_argument("--grant-id", required=True)
    revoke.add_argument("--record-id", help="Omit to remove the whole grant's access")
    publication_status = publication_actions.add_parser("status", help="Show publication IDs and access state without source text or credentials")
    publication_status.add_argument("--grant-id", required=True)
    publication_server = publication_actions.add_parser("serve", help="Serve a single authenticated grant over MCP stdio")
    publication_server.add_argument("--grant-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "published-tools":
        from .publications import PublicationService
        from .chat import ChatError
        if args.publication_action == "serve":
            from .published_tools import serve
            return serve(args.grant_id)
        try:
            service = PublicationService()
            if args.publication_action == "create":
                result = service.create(args.provider, args.session_id, hours=args.hours)
            elif args.publication_action == "publish":
                result = service.publish(args.grant_id, args.journal_id, args.note_id)
            elif args.publication_action == "revoke":
                result = service.revoke(args.grant_id, args.record_id)
            else:
                result = service.status(args.grant_id)
            print(json.dumps(result, allow_nan=False))
            return 0
        except (ChatError, OSError) as error:
            print(json.dumps({"status": "error", "message": str(error) if isinstance(error, ChatError)
                              else "Tool publication storage is unavailable. Existing files are kept."}))
            return 2
    if args.command == "recording-observe":
        from .recording_observer import observe
        from .chat import ChatError
        try:
            result = observe(args.directory, seconds=args.seconds, interval=args.interval,
                             quiet_seconds=args.quiet_seconds, probe=args.probe_format)
            print(json.dumps(result, allow_nan=False))
            return 0 if result["finished_reason"] in {"duration_complete", "user_stopped"} else 3
        except KeyboardInterrupt:
            print(json.dumps({"status": "stopped", "message": "Recording observation stopped before a report was available."}))
            return 130
        except (ChatError, OSError) as error:
            print(json.dumps({"status": "error", "message": str(error) if isinstance(error, ChatError)
                              else "Recording metadata is unavailable. Source files were kept."}))
            return 2
    if args.command == "usage-study":
        from .usage_study import UsageStudy
        from .chat import ChatError
        try:
            study = UsageStudy()
            result = study.start(args.days) if args.action == "start" else getattr(study, args.action)()
            print(json.dumps(result))
            return 0
        except (ChatError, OSError) as error:
            print(json.dumps({"status": "error", "message": str(error) if isinstance(error, ChatError) else "Usage study storage is unavailable."}))
            return 2
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
    if args.command == "market":
        from .bnet_api import BnetApiError, BnetClient
        from . import bnet_market
        try:
            client = BnetClient(region=args.region)
            if args.list_rulesets:
                result = bnet_market.list_rulesets(client, cache_only=args.cache_only, force_refresh=args.force_refresh)
            elif args.list_houses:
                result = bnet_market.list_houses(client, args.ruleset, cache_only=args.cache_only, force_refresh=args.force_refresh)
            elif args.compare_houses:
                result = bnet_market.compare_houses(
                    client,
                    ruleset_id=args.ruleset,
                    faction=args.faction,
                    item_id=args.item,
                    query=args.query,
                    ttl_seconds=args.ttl,
                    include_auctions=args.include_auctions,
                    cache_only=args.cache_only,
                    force_refresh=args.force_refresh,
                )
            else:
                if args.house is None:
                    raise BnetApiError("Specify --house <id> (or use --list-houses to inspect available auction houses).")
                result = bnet_market.price_summary(
                    client,
                    ruleset_id=args.ruleset,
                    house_id=args.house,
                    item_id=args.item,
                    query=args.query,
                    ttl_seconds=args.ttl,
                    cache_only=args.cache_only,
                    force_refresh=args.force_refresh,
                )
            print(bnet_market.as_text(result) if args.text else json.dumps(result, allow_nan=False))
            return 0
        except (BnetApiError, ValueError) as error:
            print(json.dumps({"status": "error", "message": str(error)}))
            return 2
    if args.command == "catalog":
        from .bnet_api import BnetApiError, BnetClient
        from . import bnet_catalogs
        try:
            client = BnetClient(region=args.region)
            if args.catalog_action == "ruleset":
                result = bnet_catalogs.ruleset_status(
                    client,
                    args.ruleset,
                    cache_only=args.cache_only,
                    force_refresh=args.force_refresh,
                )
            elif args.query:
                result = bnet_catalogs.search_catalog(
                    client,
                    args.kind,
                    args.query,
                    limit=args.limit,
                    cache_only=args.cache_only,
                )
            else:
                result = bnet_catalogs.fetch_catalog(
                    client,
                    args.kind,
                    cache_only=args.cache_only,
                    force_refresh=args.force_refresh,
                )
            print(bnet_catalogs.as_text(result) if args.text else json.dumps(result, allow_nan=False))
            return 0
        except (BnetApiError, ValueError) as error:
            print(json.dumps({"status": "error", "message": str(error)}))
            return 2
    if args.command == "live-test":
        from . import live_test_guide
        guide = live_test_guide.LiveTestGuide()
        if args.live_test_action == "list":
            info = guide.summary(chip=args.chip, moment=args.moment)
            print(live_test_guide.as_text(info) if args.text else json.dumps(info, allow_nan=False))
            return 0
        if args.live_test_action == "next":
            spoken = guide.next_prompt()
            print(spoken if args.text else json.dumps({"status": "ok", "spoken": spoken}, allow_nan=False))
            return 0
        if args.live_test_action == "goto":
            spoken = guide.goto(args.number)
            print(spoken if args.text else json.dumps({"status": "ok", "spoken": spoken}, allow_nan=False))
            return 0
        if args.live_test_action in {"moment", "edition"}:
            if args.live_test_action == "moment":
                spoken = guide.moment(args.moment)
            else:
                spoken = guide.set_edition(None if args.edition == "any" else args.edition)
            print(spoken if args.text else json.dumps({"status": "ok", "spoken": spoken}, allow_nan=False))
            return 0
        if args.live_test_action == "record":
            state, spoken = guide.record(args.outcome, item_id=args.item_id, note=args.note)
            print(spoken if args.text else json.dumps({"status": "ok", "spoken": spoken, "current": state.get("current")}, allow_nan=False))
            return 0
        if args.live_test_action == "status":
            info = guide.summary()
            print(guide.status_spoken() if args.text else json.dumps(info, allow_nan=False))
            return 0
        spoken = guide.reset()
        print(json.dumps({"status": "ok", "spoken": spoken}, allow_nan=False))
        return 0
    if args.command in {"quests", "character", "check-snapshot", "install-addon"}:
        return companion(args)
    if args.command == "context-probe":
        from .context import probe as context_probe
        code, report = context_probe.run(
            args.source, flavor=args.flavor, image_path=args.image, corner=args.corner, max_age=args.max_age, show=args.show,
            state_file=None if args.no_state else context_probe.DEFAULT_STATE)
        print(context_probe.as_text(report) if args.text else json.dumps(report))
        return code
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
            installed = wtf.install_addon(install_roots, args.flavor, probe=args.probe)
            if not installed:
                raise SavedVariablesError("No WoW install that has been run was found; pass --wow-root.")
            follow = ("Enable WoW Companion Probe at character select, then /reload once and type /wfhprobe."
                      if args.probe else "Enable WoW Companion at character select, then /reload once.")
            print(json.dumps({"status": "installed", "flavors": installed, "next": follow}))
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
            if getattr(args, "enrich_bnet", False):
                from .bnet_api import BnetClient
                from .bnet_items import enrich_character_report
                result = enrich_character_report(result, BnetClient())
            print(character.as_text(result) if args.text else json.dumps(result))
            return 0
        result = quests.report(quests.load(parsed), mtime, flavor=flavor, now=now)
        if getattr(args, "enrich_bnet", False):
            from .bnet_api import BnetClient
            from .bnet_quests import enrich_quest_report
            result = enrich_quest_report(result, BnetClient())
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
