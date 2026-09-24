"""Enforce the advice-only rule: no input simulation, game-memory access, or addon automation.

See AGENTS.md. Do not weaken these denylists to make a change pass; change the code instead.

Scans Python, Lua, and PowerShell/batch sources under the repo root. It skips tests/ (this file
names the patterns), docs/, build output, and every dot-folder, which covers .git, .venv, and
local-only state such as .runtime/ that CI must never read or print.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"tests", "docs", "build", "dist", "node_modules", "play-sessions", "captures", "WTF", "Interface"}

# Windows input and memory APIs plus the Python packages that wrap them. OpenProcess is
# deliberately not listed: with PROCESS_QUERY_LIMITED_INFORMATION it only names the executable
# behind a window, which capture needs to find the game. Reading or writing another process's
# memory, injecting threads, and installing hooks are denied.
PYTHON_DENY = re.compile(
    r"\b(SendInput|keybd_event|mouse_event|SetCursorPos|PostMessage\w*|SendMessage\w*|SendNotifyMessage\w*|"
    r"ReadProcessMemory|WriteProcessMemory|VirtualAllocEx|CreateRemoteThread\w*|NtReadVirtualMemory|"
    r"SetWindowsHookEx\w*|"
    r"pyautogui|pydirectinput|pynput|pywinauto|pydivert|WinDivert|pymem|frida|vgamepad|pyxinput)\b"
    r"|^\s*(import|from)\s+(keyboard|mouse|interception|scapy)\b"
)

# Addon Lua: anything that casts, moves, targets, chats, trades, accepts, equips, changes settings,
# or executes code. The addon only reads state into SavedVariables.
LUA_DENY = re.compile(
    r"\b(CastSpell\w*|CastPetAction|RunMacro\w*|RunScript|RunBinding|SendChatMessage|SendMail|"
    r"UseAction|UseContainerItem|UseInventoryItem|C_Container\.UseContainerItem|"
    r"TargetUnit|TargetNearest\w*|AssistUnit|StartAttack|AttackTarget|PetAttack|"
    r"JumpOrAscendStart|MoveForwardStart|MoveBackwardStart|TurnLeftStart|TurnRightStart|"
    r"StrafeLeftStart|StrafeRightStart|InteractUnit|AcceptQuest|CompleteQuest|SelectGossipOption|"
    r"C_GossipInfo\.Select\w*|EquipItemByName|SecureActionButtonTemplate|SetBinding\w*|SetCVar|"
    r"loadstring)\b"
    r"|\bload\s*\("
)

# Launch and setup scripts must not automate the game either.
SHELL_DENY = re.compile(
    r"SendKeys|SendInput|keybd_event|mouse_event|SetCursorPos|AutoHotkey|ControlSend|ControlClick|Send-Keys",
    re.IGNORECASE,
)


def sources(*suffixes):
    for suffix in suffixes:
        for path in ROOT.rglob(f"*{suffix}"):
            parents = path.relative_to(ROOT).parts[:-1]
            if any(part.startswith(".") or part in SKIP_DIRS for part in parents):
                continue
            yield path


def violations(pattern, *suffixes):
    found = []
    for path in sources(*suffixes):
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.search(line):
                found.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
    return found


def test_python_has_no_input_or_memory_access():
    assert violations(PYTHON_DENY, ".py") == []


def test_addon_has_no_automation():
    assert violations(LUA_DENY, ".lua") == []


def test_scripts_have_no_input_automation():
    assert violations(SHELL_DENY, ".ps1", ".psm1", ".cmd", ".bat") == []
    assert list(sources(".ahk")) == []


def test_denylists_catch_known_names():
    assert PYTHON_DENY.search("ctypes.windll.user32.SendInput(1, ...)")
    assert PYTHON_DENY.search("import pyautogui")
    assert PYTHON_DENY.search("from keyboard import press")
    assert PYTHON_DENY.search("kernel32.ReadProcessMemory(handle, address, buffer, size, None)")
    assert LUA_DENY.search('CastSpellByName("Fireball")')
    assert LUA_DENY.search("C_Container.UseContainerItem(0, 1)")
    assert LUA_DENY.search('local f = load("return 1")')
    assert SHELL_DENY.search('[System.Windows.Forms.SendKeys]::SendWait("x")')


def test_denylists_allow_capture_and_process_naming():
    assert not PYTHON_DENY.search("mss.mss().grab(monitor)")
    assert not PYTHON_DENY.search("handle = kernel32.OpenProcess(0x1000, False, pid)")
    assert not PYTHON_DENY.search("kernel32.QueryFullProcessImageNameW(handle, 0, buf, length)")
    assert not LUA_DENY.search("local left, bottom, width, height = ChatFrame1:GetRect()")
    assert not LUA_DENY.search("WoWCompanionDB.loaded = true  -- set on ADDON_LOADED")
