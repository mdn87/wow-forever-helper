"""Synthetic tests for typed agent sessions, capability manifests, and validated browser links.

Covers Milestones 1-4 of docs/AGENT_SESSION_CAPABILITY_PLAN.md with zero live CLI or real browser calls.
"""

import json
import subprocess
from types import SimpleNamespace
import uuid

import pytest

from test_workspace import SESSIONS, manager_factory, settle  # noqa: F401
from wow_helper import agent_sessions as agents
from wow_helper import browser_links as bl
from wow_helper import capabilities as cap
from wow_helper.activities import ActivityService, profile_settings
from wow_helper.chat import ChatError, ChatService, Message, read_json, write_json
from wow_helper.guidance import normalize_result
from wow_helper.window_state import LayoutLock


def uid(n):
    return str(uuid.UUID(int=n))


# ---- Milestone 1: Policy, migration, presets, manifests, revocation, creation-ID reuse ----

def test_m1_defaults_migration_and_preset_approval_stripping():
    # Brand-new windows use type-specific built-in research defaults.
    assert profile_settings("chat")["web_research"] is True
    assert profile_settings("quests")["web_research"] is True
    assert profile_settings("character")["web_research"] is True
    assert profile_settings("screen")["web_research"] is False
    assert profile_settings("journal")["web_research"] is False

    # Existing saved windows without web_research migrate to research On (CR-005).
    assert profile_settings("screen", {"flavor": "_forever_"})["web_research"] is True
    assert profile_settings("journal", {"flavor": "_forever_"})["web_research"] is True
    # Explicit saved False stays False.
    assert profile_settings("screen", {"flavor": "_forever_", "web_research": False})["web_research"] is False

    # Local browser approvals are stripped from portable profiles/presets.
    stripped = cap.strip_local_approvals({
        "flavor": "_forever_", "web_research": True,
        "browser_links": True, "browser_approved": True, "browser_generation": 3,
    })
    assert "browser_links" not in stripped
    assert "browser_approved" not in stripped
    assert "browser_generation" not in stripped


def test_m1_capability_store_generations_revocation_and_fail_closed(tmp_path):
    store = cap.CapabilityStore(tmp_path)
    win_id = uid(10)
    sess_id = uid(11)

    assert store.window_approval(win_id) == (False, 0)
    assert store.set_window_browser_approval(win_id, True) == (True, 0)

    manifest = cap.build_manifest(
        kind="quests", origin_window_id=win_id, web_research=True,
        browser_approved=True, browser_generation=0, purpose="interactive", platform_supported=True,
    )
    assert store.check_browser_grant(sess_id, manifest) == (True, "")

    # Turning off advances generation; turning back on NEVER revives the older manifest.
    assert store.set_window_browser_approval(win_id, False) == (False, 1)
    assert store.check_browser_grant(sess_id, manifest)[0] is False
    assert store.set_window_browser_approval(win_id, True) == (True, 1)
    assert store.check_browser_grant(sess_id, manifest)[0] is False

    # New session created at generation 1 is granted until revoked per session.
    manifest_g1 = cap.build_manifest(
        kind="quests", origin_window_id=win_id, web_research=True,
        browser_approved=True, browser_generation=1, purpose="interactive", platform_supported=True,
    )
    sess2 = uid(12)
    assert store.check_browser_grant(sess2, manifest_g1) == (True, "")
    store.revoke_session(sess2)
    assert store.check_browser_grant(sess2, manifest_g1)[0] is False

    # Background research and legacy sessions are always denied.
    research_manifest = cap.build_manifest(
        kind="quests", origin_window_id=win_id, web_research=True,
        browser_approved=True, browser_generation=1, purpose="research", platform_supported=True,
    )
    assert research_manifest["browser_links"] is False
    assert store.check_browser_grant(uid(13), research_manifest)[0] is False
    assert store.check_browser_grant(uid(13), None)[0] is False

    # Damaged capabilities.json fails closed and is preserved untouched on disk.
    store.path.write_text("{broken json", encoding="utf-8")
    before = store.path.read_bytes()
    assert store.check_browser_grant(uid(14), manifest_g1)[0] is False
    with pytest.raises(ChatError, match="unreadable"):
        store.window_approval(win_id)
    assert store.path.read_bytes() == before


def test_m1_creation_id_idempotent_vs_conflicting_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "codex_executable", lambda: "synthetic-codex")
    monkeypatch.setattr(agents, "claude_command", lambda: ["synthetic-claude"])
    store = agents.AgentSessions(tmp_path / "agents", capability_storage=tmp_path)
    m1 = cap.build_manifest(kind="chat", origin_window_id=uid(1), web_research=True,
                            browser_approved=False, platform_supported=True)
    m2 = cap.build_manifest(kind="quests", origin_window_id=uid(1), web_research=False,
                            browser_approved=False, platform_supported=True)
    cid = uid(50)
    first = store.create("codex", "Chat", creation_id=cid, manifest=m1)
    again = store.create("codex", "Chat", creation_id=cid, manifest=m1)
    assert first.key == again.key
    meta_before = (store.folder(cid) / "session.json").read_bytes()
    with pytest.raises(ChatError, match="different session setup"):
        store.create("codex", "Quests", creation_id=cid, manifest=m2)
    with pytest.raises(ChatError, match="different session setup"):
        store.create("claude", "Chat", creation_id=cid, manifest=m1)
    assert (store.folder(cid) / "session.json").read_bytes() == meta_before


# ---- Milestone 2: Provider command arrays, probe cache, structured protocol, fallback ----

def test_m2_provider_command_arrays_for_research_on_and_off(monkeypatch):
    monkeypatch.setattr(agents, "codex_executable", lambda: "synthetic-codex")
    monkeypatch.setattr(agents, "claude_command", lambda: ["synthetic-claude"])

    codex_on = agents.command("codex", web_research=True)
    codex_off = agents.command("codex", web_research=False)
    assert "--search" in codex_on and 'web_search="live"' in codex_on
    assert "--search" not in codex_off and 'web_search="disabled"' in codex_off

    claude_on = agents.command("claude", web_research=True)
    claude_off = agents.command("claude", web_research=False)
    assert claude_on[claude_on.index("--tools") + 1] == "Read,Glob,Grep,WebSearch,WebFetch"
    assert claude_on[claude_on.index("--allowedTools") + 1] == "Read,Glob,Grep,WebSearch,WebFetch"
    assert claude_off[claude_off.index("--tools") + 1] == "Read,Glob,Grep"
    assert claude_off[claude_off.index("--allowedTools") + 1] == "Read,Glob,Grep"


def test_m2_provider_probe_caching_version_invalidation_and_timeout():
    cap.clear_probe_cache()
    calls = []
    version = ["0.163.0"]

    def fake_run(args, **_kwargs):
        calls.append(args)
        if "--version" in args:
            return SimpleNamespace(returncode=0, stdout=f"codex {version[0]}\n", stderr="")
        if "resume" in args:
            return SimpleNamespace(returncode=0, stdout="Usage: resume --output-schema FILE\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="Usage: exec --output-schema FILE\n", stderr="")

    res1 = cap.probe_provider("codex", runner=fake_run, codex_exe=lambda: "codex-bin")
    assert res1.supported is True
    n_after_first = len(calls)
    res2 = cap.probe_provider("codex", runner=fake_run, codex_exe=lambda: "codex-bin")
    assert res2 == res1
    # Version checked, help results served from cache.
    assert len(calls) == n_after_first + 1

    # Version change invalidates cache and re-probes help.
    version[0] = "0.164.0"
    res3 = cap.probe_provider("codex", runner=fake_run, codex_exe=lambda: "codex-bin")
    assert res3.supported is True and "0.164.0" in res3.version
    assert len(calls) == n_after_first + 4

    # Timeout degrades gracefully to unsupported.
    def timeout_run(_args, **_kwargs):
        raise subprocess.TimeoutExpired(["codex"], 5)

    res_to = cap.probe_provider("codex", runner=timeout_run, codex_exe=lambda: "codex-bin")
    assert res_to.supported is False

    # Missing Claude --json-schema degrades gracefully.
    def claude_old(args, **_kwargs):
        if "--version" in args:
            return SimpleNamespace(returncode=0, stdout="claude 1.0.0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="--tools --allowedTools --output-format\n", stderr="")

    res_cl = cap.probe_provider("claude", runner=claude_old, claude_cmd=lambda: ["claude-bin"])
    assert res_cl.supported is False and "Manual links only" in res_cl.detail


# ---- Milestone 3: URL validation, helper launch, durable markers/receipts, reconciliation ----

def test_m3_strict_url_validation_normalization_and_rejections():
    # Unicode IDNA domain normalizes to lowercase ASCII punycode and preserves query/fragment/percent-encoded path.
    good = bl.validate_browser_url("https://Bücher.Example/wiki/Quest%20Guide?edition=classic#step-2")
    assert good.destination == "https://xn--bcher-kva.example"
    assert good.url == "https://xn--bcher-kva.example/wiki/Quest%20Guide?edition=classic#step-2"

    # Nondefault port is preserved in destination; default port is normalized away.
    with_port = bl.validate_browser_url("https://example.org:8443/path")
    assert with_port.destination == "https://example.org:8443"
    default_port = bl.validate_browser_url("https://example.org:443/path")
    assert default_port.destination == "https://example.org"

    # All forbidden URL forms are rejected.
    rejected = [
        "",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:pass@example.com/guide",
        "https://example.com/with space",
        "https://example.com/bidi\u202etest",
        "https://example.com\\backslash",
        "https://ex%61mple.com/encoded-host",
        "https://example.com/bad%ZZescape",
        "http://localhost/test",
        "http://sub.localhost/test",
        "http://127.0.0.1/test",
        "http://10.0.0.5/test",
        "http://169.254.169.254/latest",
        "http://[::1]/test",
        "http://[::ffff:127.0.0.1]/test",
        "http://intranet/single-label",
        "https://example.com/" + ("a" * 4100),
    ]
    for bad in rejected:
        with pytest.raises(bl.BrowserLinkError):
            bl.validate_browser_url(bad)

    # Reply schema validation rejects arrays, extra fields, overlong fields, while preserving usable answer.
    with pytest.raises(bl.BrowserReplyError) as exc:
        bl.validate_browser_reply({"answer": "Good answer", "browser_request": [{"url": "https://example.com", "title": "x"}]})
    assert exc.value.usable_answer == "Good answer"
    with pytest.raises(bl.BrowserReplyError) as exc2:
        bl.validate_browser_reply({"answer": "Good answer", "browser_request": None, "extra": 1})
    assert exc2.value.usable_answer == "Good answer"

    # Existing guide source-link normalization policy stays unchanged (CR-008).
    guide = normalize_result({
        "summary": "Synthetic guide", "steps": ["Go north"], "caveats": [],
        "sources": [{"title": "Guide", "url": "https://example.com/quest%201?tab=comments#top"}],
    })
    assert guide["sources"][0]["url"] == "https://example.com/quest%201?tab=comments#top"


def test_m3_helper_outcomes_reconciliation_revocation_and_manual_open(tmp_path, monkeypatch):
    # Helper launch outcomes: 0 -> launch_accepted, 2 -> failed, OSError -> failed, Timeout -> kills & unknown.
    class FakeProc:
        def __init__(self, code=0, timeout=False):
            self.returncode = code
            self._timeout = timeout
            self.killed = False
            self.seen_input = None

        def communicate(self, input=None, timeout=None):
            if input is not None:
                self.seen_input = input
            if self._timeout and not self.killed:
                raise subprocess.TimeoutExpired(["python"], timeout)
            return b"", b""

        def kill(self):
            self.killed = True

    p_ok = FakeProc(code=0)
    assert bl.launch_url("https://example.org/ok", popen=lambda *a, **kw: p_ok) == "launch_accepted"
    assert p_ok.seen_input == b"https://example.org/ok"
    assert bl.launch_url("https://example.org/no", popen=lambda *a, **kw: FakeProc(code=2)) == "failed"
    assert bl.launch_url("https://example.org/err", popen=lambda *a, **kw: (_ for _ in ()).throw(OSError("boom"))) == "failed"
    p_slow = FakeProc(timeout=True)
    assert bl.launch_url("https://example.org/slow", popen=lambda *a, **kw: p_slow) == "unknown"
    assert p_slow.killed is True

    # End-to-end turn + mid-turn revocation + crash reconciliation + manual open deduplication.
    monkeypatch.setattr(agents, "codex_executable", lambda: "synthetic-codex")
    monkeypatch.setattr(agents, "claude_command", lambda: ["synthetic-claude"])
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *a, **kw: object())

    cap_store = cap.CapabilityStore(tmp_path)
    win_id = uid(60)
    cap_store.set_window_browser_approval(win_id, True)
    manifest = cap.build_manifest(
        kind="quests", origin_window_id=win_id, web_research=True,
        browser_approved=True, browser_generation=0, purpose="interactive", platform_supported=True,
    )
    store = agents.AgentSessions(tmp_path / "agents", capability_storage=tmp_path)
    ok_probe = lambda _p: cap.ProbeResult(True, "0.163.0", "")
    session = store.create("codex", "Quest helper", creation_id=uid(61), manifest=manifest)

    # First turn: commentary + structured JSON -> launches once, records receipt, progress hidden during running.
    req1 = uid(62)
    store.send(session, "Open the quest guide", req1, platform_supported=True, probe_fn=ok_probe)
    # While running/queued, history shows progress text rather than raw protocol JSON.
    assert store.history(session)[1].text == "Preparing answer and link…"

    payload = {
        "answer": "Check https://example.org/quest-guide for steps.",
        "browser_request": {"url": "https://example.org/quest-guide", "title": "Quest Guide"},
    }
    events = [
        {"type": "thread.started", "thread_id": uid(63)},
        {"type": "item.completed", "item": {"type": "agent_message", "id": "1", "text": "Checking guide…"}},
        {"type": "item.completed", "item": {"type": "agent_message", "id": "2", "text": json.dumps(payload)}},
    ]

    class FakeCli:
        def __init__(self, args, **kwargs):
            self.args, self.returncode = args, 0
            self.inputs = []
            kwargs["stdout"].write(b"\n".join(json.dumps(e).encode() for e in events))
            kwargs["stdout"].flush()
        def communicate(self, input=None, timeout=None):
            self.inputs.append(input)
            return None, None
        def poll(self): return 0
        def kill(self): pass

    launched = []
    cli_instances = []
    def spawn_cli(args, **kwargs):
        proc = FakeCli(args, **kwargs)
        cli_instances.append(proc)
        return proc

    monkeypatch.setattr(agents.subprocess, "Popen", spawn_cli)
    agents.run_turn(store.storage, session.id, req1, launcher=lambda u: launched.append(u) or "launch_accepted",
                    platform_supported=True, probe_fn=ok_probe)
    assert launched == ["https://example.org/quest-guide"]
    assert store.history(session)[1].text == payload["answer"]
    receipts = store.browser_receipts(session)
    assert receipts[req1]["outcome"] == "launch_accepted"
    assert receipts[req1]["destination"] == "https://example.org"
    assert b"browser_request" in cli_instances[0].inputs[0]

    # Reading history or re-running turn never replays browser launch.
    agents.run_turn(store.storage, session.id, req1, launcher=lambda u: launched.append(u) or "launch_accepted",
                    platform_supported=True, probe_fn=ok_probe)
    assert len(launched) == 1

    # Second (resumed) turn: revoke session BEFORE completion -> writes `stopped` receipt, never launches!
    req2 = uid(64)
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *a, **kw: object())
    store.send(session, "Open another page", req2, platform_supported=True, probe_fn=ok_probe)

    class RevokingCli(FakeCli):
        def communicate(self, input=None, timeout=None):
            cap_store.revoke_session(session.id)
            return super().communicate(input=input, timeout=timeout)

    cli2 = []
    monkeypatch.setattr(agents.subprocess, "Popen", lambda args, **kw: (cli2.append(RevokingCli(args, **kw)) or cli2[-1]))
    agents.run_turn(store.storage, session.id, req2, launcher=lambda u: launched.append(u) or "launch_accepted",
                    platform_supported=True, probe_fn=ok_probe)
    assert len(launched) == 1  # Revocation blocked launch!
    assert b"Prior browser action receipt" in cli2[0].inputs[0]
    receipts2 = store.browser_receipts(session)
    assert receipts2[req2]["outcome"] == "stopped"
    assert "Automatic opening stopped" in receipts2[req2]["message"]

    # Crash reconciliation: torn attempt marker without receipt becomes `unknown` when run.json is unlocked.
    req3 = uid(65)
    torn_marker = bl.attempt_marker_path(store.folder(session.id), req3)
    torn_marker.write_text("{torn", encoding="utf-8")
    # While a live worker holds run.json, reconcile leaves it untouched.
    live_lock = LayoutLock(store.folder(session.id) / "run.json")
    try:
        assert store.reconcile(session.id) == []
        assert not bl.receipt_path(store.folder(session.id), req3).exists()
    finally:
        live_lock.close()
    # Once worker exits, reconcile marks durable `unknown` without launching anything.
    reconciled = store.reconcile(session.id)
    assert len(reconciled) == 1 and reconciled[0]["outcome"] == "unknown"
    assert bl.read_receipt(store.folder(session.id), req3)["outcome"] == "unknown"
    assert len(launched) == 1

    # Manual open click uses its own fresh action ID, deduplicates double-clicks, and works after revocation.
    act_id = uid(66)
    res = bl.manual_open_link(store.folder(session.id), session.id, "https://example.org/quest-guide",
                              "Quest Guide", action_id=act_id, launcher=lambda u: launched.append(u) or "launch_accepted")
    assert res["outcome"] == "launch_accepted" and len(launched) == 2
    with pytest.raises(bl.BrowserLinkError, match="already handled"):
        bl.manual_open_link(store.folder(session.id), session.id, "https://example.org/quest-guide",
                            "Quest Guide", action_id=act_id, launcher=lambda u: launched.append(u) or "launch_accepted")
    assert len(launched) == 2


def test_m2_runtime_schema_rejection_falls_back_to_text_v1(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "codex_executable", lambda: "synthetic-codex")
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *a, **kw: object())

    cap_store = cap.CapabilityStore(tmp_path)
    win_id = uid(70)
    cap_store.set_window_browser_approval(win_id, True)
    manifest = cap.build_manifest(
        kind="chat", origin_window_id=win_id, web_research=True,
        browser_approved=True, browser_generation=0, purpose="interactive", platform_supported=True,
    )
    store = agents.AgentSessions(tmp_path / "agents", capability_storage=tmp_path)
    ok_probe = lambda _p: cap.ProbeResult(True, "0.163.0", "")
    session = store.create("codex", "Fallback chat", creation_id=uid(71), manifest=manifest)

    req1 = uid(72)
    store.send(session, "First try", req1, platform_supported=True, probe_fn=ok_probe)

    class RejectSchemaCli:
        def __init__(self, args, **kwargs):
            self.returncode = 2
            kwargs["stderr"].write(b"error: unknown option --output-schema\n")
            kwargs["stderr"].flush()
        def communicate(self, input=None, timeout=None): return None, None
        def poll(self): return 2
        def kill(self): pass

    monkeypatch.setattr(agents.subprocess, "Popen", RejectSchemaCli)
    agents.run_turn(store.storage, session.id, req1, platform_supported=True, probe_fn=ok_probe)
    assert store.result(session.id, req1)["status"] == "failed"
    assert store.session_meta(session.id).get("browser_protocol_unavailable") is True

    # Next explicit turn automatically selects text_v1 with no schema.
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *a, **kw: object())
    req2 = uid(73)
    store.send(session, "Second try", req2, platform_supported=True, probe_fn=ok_probe)
    assert store.result(session.id, req2)["protocol"] == "text_v1"
    assert store.result(session.id, req2)["schema"] is None


# ---- Milestone 4: UI Capabilities tab, receipt bar, destination-primary display, session isolation ----

def test_m4_setup_dialog_capabilities_and_browser_receipt_ui(manager_factory, monkeypatch):
    manager = manager_factory()
    view = manager.windows[0].view
    settle(view)
    view._select_session(SESSIONS[0])
    settle(view)

    # SetupDialog exposes Capabilities tab, stays usable at 460x480 minimum size, and persists settings.
    view.show_setup()
    setup = view._setup_dialog
    setup.root.geometry("460x480")
    manager.root.update()
    tab_names = [setup.book.tab(t, "text") for t in setup.book.tabs()]
    assert "Capabilities" in tab_names
    setup.book.select(tab_names.index("Capabilities"))
    setup.root.update()
    assert setup.browser_check.winfo_ismapped()
    assert setup.save_button.winfo_ismapped()
    assert setup.save_button.winfo_rooty() + setup.save_button.winfo_height() < setup.root.winfo_rooty() + 480
    setup.web_research.set(False)
    setup.browser_links.set(True)
    setup.save()
    manager.root.update()
    assert view.profile["web_research"] is False
    assert cap.CapabilityStore(view.activity.storage).window_approval(view.window_id) == (True, 0)

    # Receipt bar renders normalized ASCII destination as primary text even when model title tries to spoof domain + bidi.
    spoof_receipt = {
        "session_id": SESSIONS[0].id,
        "request_id": uid(80),
        "outcome": "unknown",
        "url": "https://xn--bcher-kva.example/guide?id=9",
        "destination": "https://xn--bcher-kva.example",
        "title": "wowhead.com\u202e\x07 Official Guide",
        "message": bl.OUTCOME_TEXT["unknown"],
        "at": 100.0,
    }
    view._effective_caps[SESSIONS[0].key] = {
        "typed": True, "kind": "chat", "web_research": True,
        "browser_enabled": True, "protocol": "chat_browser_v1", "browser_reason": "",
    }
    view._browser_receipts[SESSIONS[0].key] = {uid(80): spoof_receipt}
    view._render_browser_bar()
    manager.root.update()

    assert view.browser_bar.winfo_manager()
    assert view.browser_status.get() == "https://xn--bcher-kva.example"
    assert "\u202e" not in view.browser_detail.get() and "\x07" not in view.browser_detail.get()
    assert "Opening status unknown" in view.browser_detail.get()
    assert str(view.open_receipt_button.cget("text")) == "Open anyway (may open duplicate)"
    assert view.receipt_url_entry.get() == "https://xn--bcher-kva.example/guide?id=9"

    # Switching to another session clears the first session's receipt (no cross-session bleed).
    view._select_session(SESSIONS[1])
    settle(view)
    assert view._active_receipt is None
    assert not view.browser_bar.winfo_manager()

    # Copy full URL works via keyboard-accessible button without hover.
    view._select_session(SESSIONS[0])
    settle(view)
    view._browser_receipts[SESSIONS[0].key] = {uid(80): spoof_receipt}
    view._render_browser_bar()
    copied = []
    monkeypatch.setattr(view.root, "clipboard_clear", lambda: None)
    monkeypatch.setattr(view.root, "clipboard_append", copied.append)
    view.copy_receipt_url_button.invoke()
    assert copied == ["https://xn--bcher-kva.example/guide?id=9"]

    # Revoking browser access updates UI immediately for a managed session (external sessions are skipped).
    from wow_helper.chat import Session
    managed_sess = Session("codex", uid(99), "Managed chat", "Companion", "ready", managed=True)
    view.sessions = [*view.sessions, managed_sess]
    view._session_labels()
    view._select_session(managed_sess)
    settle(view)
    revoked = []
    view.service.revoke_browser = lambda s: revoked.append(s.key)
    view.service.effective_capabilities = lambda _s: {
        "typed": True, "kind": "chat", "web_research": True,
        "browser_enabled": False, "protocol": "text_v1",
        "browser_reason": "Automatic opening was stopped for this chat.",
    }
    view.service.browser_receipts = lambda _s: {}
    view.revoke_browser_access()
    manager.root.update()
    assert revoked == [managed_sess.key]
    assert "Manual links only" in view.browser_status.get()
    assert not view.stop_browser_button.winfo_manager()


def test_m2_claude_chat_browser_v1_new_resumed_and_revoked_text_envelope(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "claude_command", lambda: ["synthetic-claude"])
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *a, **kw: object())

    cap_store = cap.CapabilityStore(tmp_path)
    win_id = uid(101)
    cap_store.set_window_browser_approval(win_id, True)
    manifest = cap.build_manifest(
        kind="quests", origin_window_id=win_id, web_research=True,
        browser_approved=True, browser_generation=0, purpose="interactive", platform_supported=True,
    )
    store = agents.AgentSessions(tmp_path / "agents", capability_storage=tmp_path)
    ok_probe = lambda _p: cap.ProbeResult(True, "2.1.325 (Claude Code)", "")
    session = store.create("claude", "Claude browser chat", creation_id=uid(102), manifest=manifest)

    native_sid = uid(103)
    seen_args = []
    seen_inputs = []
    launched = []

    def run_fake_claude(req_id, events):
        class FakeClaudeCli:
            def __init__(self, args, **kwargs):
                self.returncode = 0
                seen_args.append(list(args))
                kwargs["stdout"].write(b"\n".join(json.dumps(e).encode() for e in events))
                kwargs["stdout"].flush()
            def communicate(self, input=None, timeout=None):
                seen_inputs.append(input)
                return None, None
            def poll(self): return 0
            def kill(self): pass

        monkeypatch.setattr(agents.subprocess, "Popen", FakeClaudeCli)
        agents.run_turn(
            store.storage, session.id, req_id,
            launcher=lambda u: launched.append(u) or "launch_accepted",
            platform_supported=True, probe_fn=ok_probe,
        )

    # Turn 1 (new Claude session): passes --json-schema and dispatches validated link once.
    req1 = uid(104)
    store.send(session, "Open example.com", req1, platform_supported=True, probe_fn=ok_probe)
    run_fake_claude(req1, [
        {"type": "system", "session_id": native_sid},
        {"type": "result", "session_id": native_sid, "is_error": False, "structured_output": {
            "answer": "Opened https://example.com/.",
            "browser_request": {"url": "https://example.com/", "title": "Example Domain"},
        }},
    ])
    assert "--json-schema" in seen_args[0]
    assert "--resume" not in seen_args[0]
    assert launched == ["https://example.com/"]
    assert store.browser_receipts(session)[req1]["outcome"] == "launch_accepted"

    # Turn 2 (resumed Claude session): passes --resume <native_id> and --json-schema, includes prior receipt.
    req2 = uid(105)
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *a, **kw: object())
    store.send(session, "Now open example.org", req2, platform_supported=True, probe_fn=ok_probe)
    run_fake_claude(req2, [
        {"type": "result", "session_id": native_sid, "is_error": False, "structured_output": {
            "answer": "Opened https://example.org/.",
            "browser_request": {"url": "https://example.org/", "title": "Example Org"},
        }},
    ])
    assert "--resume" in seen_args[1] and native_sid in seen_args[1]
    assert "--json-schema" in seen_args[1]
    assert b"Prior browser action receipt" in seen_inputs[1]
    assert launched == ["https://example.com/", "https://example.org/"]

    # Turn 3 (after per-session revocation): switches to text_v1 without --json-schema.
    # Even if the model repeats an old JSON envelope, answer is decoded cleanly and NOTHING opens.
    cap_store.revoke_session(session.id)
    req3 = uid(106)
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *a, **kw: object())
    store.send(session, "Summarize without opening links", req3, platform_supported=True, probe_fn=ok_probe)
    assert store.result(session.id, req3)["protocol"] == "text_v1"
    run_fake_claude(req3, [
        {"type": "assistant", "session_id": native_sid, "message": {"id": "m1", "content": [{
            "type": "text",
            "text": json.dumps({
                "answer": "Readable answer after revocation.",
                "browser_request": {"url": "https://example.net/", "title": "Ignored"},
            }),
        }]}},
        {"type": "result", "session_id": native_sid, "is_error": False},
    ])
    assert "--json-schema" not in seen_args[2]
    assert store.result(session.id, req3)["response"] == "Readable answer after revocation."
    assert launched == ["https://example.com/", "https://example.org/"]


def test_m3_background_research_and_attached_sessions_cannot_enter_dispatcher(tmp_path, monkeypatch):
    from wow_helper.chat import Session
    from wow_helper.guidance import Guidance

    monkeypatch.setattr(agents, "codex_executable", lambda: "synthetic-codex")
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *a, **kw: object())

    # Even when a window approves browser links, background Guidance sessions stay research/custom_schema only.
    cap_store = cap.CapabilityStore(tmp_path)
    cap_store.set_window_browser_approval(uid(110), True)
    guide_svc = Guidance(tmp_path)
    key = guide_svc.request("quest", {"quest": {"id": 1, "title": "Synthetic Quest"}}, "Classic Forever", "obvious", "codex")
    rec = guide_svc.get(key)
    meta = guide_svc.agents.session_meta(rec["session"])
    assert meta["manifest"]["purpose"] == "research"
    assert meta["manifest"]["browser_links"] is False
    req = guide_svc.agents.result(rec["session"], rec["request"])
    assert req["protocol"] == "custom_schema"

    # Attached external sessions (managed=False) never receive capability manifests, receipts, or revocation writes.
    service = ChatService(state=tmp_path)
    external = Session("codex", uid(111), "External terminal", "proj", "idle", managed=False)
    assert service.effective_capabilities(external) is None
    assert service.browser_receipts(external) == {}
    before = cap_store.path.read_bytes()
    service.revoke_browser(external)
    assert cap_store.path.read_bytes() == before


def test_m3_browser_helper_requires_pythonw_on_windows(monkeypatch):
    if bl.os.name != "nt":
        pytest.skip("Windows pythonw.exe requirement check")
    seen = []

    class FakeProc:
        returncode = 0
        def communicate(self, input=None, timeout=None):
            return b"", b""

    def fake_popen(args, **kw):
        seen.append(args)
        return FakeProc()

    assert bl.launch_url("https://example.org/", popen=fake_popen) == "launch_accepted"
    assert seen and bl.Path(seen[0][0]).name.lower() == "pythonw.exe"

    monkeypatch.setattr(bl, "_helper_executable", lambda: None)
    called = []
    assert bl.launch_url("https://example.org/", popen=lambda *a, **kw: called.append(a)) == "failed"
    assert called == []


def test_m4_app_restart_reloads_receipt_without_replaying_browser_launch(tmp_path, monkeypatch, manager_factory):
    class DummyCodex:
        def sessions(self):
            return []
        def close(self):
            pass

    monkeypatch.setattr(agents, "codex_executable", lambda: "synthetic-codex")
    monkeypatch.setattr(bl, "launch_url", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not replay on restart")))

    state = tmp_path / "chat"
    cap_store = cap.CapabilityStore(state)
    win_id = uid(120)
    cap_store.set_window_browser_approval(win_id, True)
    manifest = cap.build_manifest(
        kind="chat", origin_window_id=win_id, web_research=True,
        browser_approved=True, browser_generation=0, purpose="interactive", platform_supported=True,
    )
    store = agents.AgentSessions(state / "agents", capability_storage=state)
    session = store.create("codex", "Restart test chat", creation_id=uid(121), manifest=manifest)
    req_id = uid(122)
    link = bl.validate_browser_url("https://example.org/guide")
    bl.claim_attempt(store.folder(session.id), session.id, req_id, link, "Example Guide")
    bl.write_terminal_receipt(store.folder(session.id), session.id, req_id, "launch_accepted", link, "Example Guide")
    meta = store.session_meta(session.id)
    meta["requests"] = [req_id]
    write_json(store.folder(session.id) / "session.json", meta)
    write_json(store.folder(session.id) / "requests" / (req_id + ".json"), {
        "id": req_id, "body": "Open guide", "status": "completed",
        "response": "Opened https://example.org/guide", "at": 100.0, "protocol": "chat_browser_v1",
    })

    # Reopen a fresh ChatService + WindowManager over the saved state: discovers, reconciles,
    # and renders the persisted receipt without launching the browser again.
    def make_service():
        svc = ChatService(state=state, codex=DummyCodex())
        svc.claude_home = tmp_path / "empty-claude"
        return svc

    manager = manager_factory(
        path=tmp_path / "windows-restart.json",
        service=make_service,
        activity=lambda: ActivityService(state),
    )
    view = manager.windows[0].view
    settle(view)
    found = [s for s in view.sessions if s.id == session.id]
    assert len(found) == 1
    view._select_session(found[0])
    settle(view)
    assert view.browser_bar.winfo_manager()
    assert view.browser_status.get() == "https://example.org"
    assert "Sent link to browser" in view.browser_detail.get()
