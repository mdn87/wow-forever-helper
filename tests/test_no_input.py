"""Enforce the advice-only rule: no input simulation, game-memory access, or addon automation.

See AGENTS.md. Do not weaken this denylist to make a change pass.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "tests", "docs", "build", "dist"}

PYTHON_DENY = re.compile(
    r"\b(SendInput|keybd_event|mouse_event|SetCursorPos|PostMessage\w*|SendMessage\w*|"
    r"ReadProcessMemory|WriteProcessMemory|OpenProcess|SetWindowsHookEx\w*|CreateRemoteThread|"
    r"pyautogui|pydirectinput|pynput|pydivert|WinDivert|pymem|frida)\b"
    r"|^\s*(import|from)\s+(keyboard|mouse|interception|scapy)\b"
)
LUA_DENY = re.compile(
    r"\b(CastSpell\w*|RunMacro\w*|RunScript|SendChatMessage|UseAction|UseContainerItem|"
    r"C_Container\.UseContainerItem|TargetUnit|AssistUnit|JumpOrAscendStart|MoveForwardStart|"
    r"TurnLeftStart|TurnRightStart|InteractUnit|SecureCmdOptionParse|loadstring)\b"
)


def sources(suffix):
    for path in ROOT.rglob(f"*{suffix}"):
        if not SKIP_DIRS.intersection(path.relative_to(ROOT).parts):
            yield path


def violations(suffix, pattern):
    found = []
    for path in sources(suffix):
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.search(line):
                found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    return found


def test_python_has_no_input_or_memory_access():
    assert violations(".py", PYTHON_DENY) == []


def test_addon_has_no_automation():
    assert violations(".lua", LUA_DENY) == []


def test_denylists_catch_known_names():
    assert PYTHON_DENY.search("ctypes.windll.user32.SendInput(1, ...)")
    assert PYTHON_DENY.search("import pyautogui")
    assert LUA_DENY.search('CastSpellByName("Fireball")')
    assert not PYTHON_DENY.search("mss.mss().grab(monitor)")
