"""Find WoW installs and the companion addon's SavedVariables. Paths are never printed.

An install root holds one folder per game flavour (`_retail_`, `_classic_`, `_classic_beta_`,
...). Each flavour keeps account-wide SavedVariables under `WTF/Account/<ID>/SavedVariables/`.
The numeric account folder name is only used to open the file; it is never reported.
"""

import json
import shutil
import sys
from pathlib import Path

ADDON = "WoWCompanion"
ADDON_SOURCE = Path(__file__).resolve().parents[1] / "wow_addon" / ADDON
DEFAULT_ROOTS = (r"C:\Program Files (x86)\World of Warcraft", r"C:\Program Files\World of Warcraft")
UNINSTALL = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"


def registry_roots():
    """Install folders that Battle.net registered for uninstall (Windows only)."""
    if sys.platform != "win32":
        return []
    import winreg
    found = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL) as key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                name = winreg.EnumKey(key, index)
                if "Warcraft" not in name:
                    continue
                with winreg.OpenKey(key, name) as sub:
                    try:
                        found.append(winreg.QueryValueEx(sub, "InstallLocation")[0])
                    except OSError:
                        pass
    except OSError:
        pass
    return found


def roots(configured=None):
    seen, result = set(), []
    for raw in ([configured] if configured else []) + registry_roots() + list(DEFAULT_ROOTS):
        path = Path(raw)
        key = str(path).casefold()
        if key not in seen and path.is_dir():
            seen.add(key)
            result.append(path)
    return result


def flavors(root):
    return sorted(p for p in Path(root).iterdir() if p.is_dir() and p.name.startswith("_") and p.name.endswith("_"))


def snapshots(install_roots):
    """(flavour name, file) for every companion SavedVariables file found."""
    for root in install_roots:
        for flavor in flavors(root):
            for path in flavor.glob(f"WTF/Account/*/SavedVariables/{ADDON}.lua"):
                yield flavor.name, path


def newest(install_roots, *, only=None):
    """The newest snapshot, optionally restricted to one flavour, or None."""
    found = []
    for flavor, path in snapshots(install_roots):
        if only is not None and flavor != only:
            continue
        try:
            found.append((path.stat().st_mtime, flavor, path))
        except OSError:
            continue
    if not found:
        return None
    _, flavor, path = max(found)
    return flavor, path


def flavor_of(path):
    """The flavour folder a file sits in, e.g. `_retail_`, or None."""
    for part in reversed(Path(path).parts):
        if len(part) > 2 and part.startswith("_") and part.endswith("_"):
            return part
    return None


def install_addon(install_roots, only=None):
    """Copy the addon into each flavour's Interface/AddOns. Returns the flavour names."""
    installed = []
    for root in install_roots:
        for flavor in flavors(root):
            # Only flavours the game has already run, so a stray folder is never populated.
            if (only and flavor.name != only) or not (flavor / "WTF").is_dir():
                continue
            target = flavor / "Interface" / "AddOns" / ADDON
            target.mkdir(parents=True, exist_ok=True)
            for source in ADDON_SOURCE.iterdir():
                if source.suffix in {".toc", ".lua"}:
                    shutil.copyfile(source, target / source.name)
            installed.append(flavor.name)
    return installed


def load_settings(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(path, **values):
    data = {**load_settings(path), **values}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
