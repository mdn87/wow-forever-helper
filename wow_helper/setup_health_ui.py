"""WoW install detection, explicit companion addon install, snapshot health check, and assistive status."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import time

from . import check, wtf
from .activities import FLAVORS
from .chat import ROOT
from .journal_ui import JournalDialog, style_journal_tree
from .savedvars import SavedVariablesError, read_stable
from .task_window import replace_text


def inspect_editions(install_roots):
    """Return path-free, account-free status rows for every supported game edition."""
    found_flavors = {}
    for root in install_roots:
        for folder in wtf.flavors(root):
            found_flavors.setdefault(folder.name, folder)
    rows = []
    now = time.time()
    for label, flavor in FLAVORS.items():
        folder = found_flavors.get(flavor)
        has_wtf = bool(folder and (folder / "WTF").is_dir())
        addon_state = "Not installed"
        if folder is not None:
            toc = folder / "Interface" / "AddOns" / wtf.ADDON / f"{wtf.ADDON}.toc"
            if toc.is_file():
                try:
                    _interfaces, version = check.toc_lines(toc)
                except OSError:
                    version = None
                if version == check.ADDON_VERSION:
                    addon_state = f"Installed ({version})"
                elif version:
                    addon_state = f"Outdated ({version}, ships {check.ADDON_VERSION})"
                else:
                    addon_state = "Installed (version unknown)"
        snap = wtf.newest(install_roots, only=flavor)
        if snap is not None:
            try:
                age_sec = max(0, int(now - snap[1].stat().st_mtime))
                snap_state = (f"Saved {age_sec}s ago" if age_sec < 60
                              else f"Saved {age_sec // 60}m ago" if age_sec < 3600
                              else f"Saved {age_sec // 3600}h ago")
            except OSError:
                snap_state = "Unreadable"
        else:
            snap_state = "None yet"
        rows.append({
            "label": label,
            "flavor": flavor,
            "folder_state": "Ready" if has_wtf else ("No WTF yet" if folder else "Not found"),
            "addon_state": addon_state,
            "snapshot_state": snap_state,
        })
    return rows


def run_snapshot_check(install_roots, flavor):
    """Run read-only snapshot verification for one flavor and return path-free report text."""
    found = wtf.newest(install_roots, only=flavor)
    if found is None:
        return (f"No saved snapshot was found for {flavor}.\n\n"
                "Install the companion addon, enable WoW Companion at character select, "
                "log in, and run /reload in game, then check again.")
    found_flavor, path = found
    try:
        parsed, mtime = read_stable(path, wait=1.0)
        result = check.report(parsed, mtime, flavor=found_flavor, now=time.time())
        return check.as_text(result)
    except SavedVariablesError as error:
        return str(error)
    except OSError:
        return "The snapshot file could not be read. Check folder permissions and try again."


def read_assist_status(assist_path):
    """Read-only status of local assistive input without creating a database when absent."""
    path = Path(assist_path)
    if not path.is_file():
        return {"configured": False, "enabled": False, "stub": False, "bindings": {}}
    try:
        from .assist import Assistant
        status = Assistant(path, None).status()
        return {"configured": True, **status}
    except (OSError, sqlite3.Error):
        return {"configured": False, "enabled": False, "stub": False, "bindings": {}, "error": True}


class SetupHealthDialog(JournalDialog):
    """In-app WoW folder setup, explicit addon installer, snapshot health check, and assistive status."""

    def __init__(self, manager, window, *, settings_path=None, assist_path=None,
                 roots_fn=None, install_fn=None):
        self.manager = manager
        self.window = window
        self.parent = window.root
        activity = manager.activity_factory()
        self.settings_path = Path(settings_path) if settings_path else activity.settings
        self.assist_path = Path(assist_path) if assist_path else ROOT / ".runtime" / "assist.sqlite"
        self.roots_fn = roots_fn or wtf.roots
        self.install_fn = install_fn or wtf.install_addon
        self.closed = False
        self.future = None
        self.after = None
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="setup-health")
        view = window.view or getattr(window.display, "views", {}).get(getattr(window.display, "active", None))
        if view is None:
            from types import SimpleNamespace
            from .appearance import DEFAULTS
            view = SimpleNamespace(tk=manager.tk, root=window.root, appearance=dict(DEFAULTS))
        super().__init__(view, "WoW setup & addon health", size=(640, 620), minimum=(460, 440))
        self.notice.set(
            f"Shipped companion addon v{check.ADDON_VERSION}. Installing copies the addon into your WoW "
            "Interface/AddOns folder only when you press Install addon; the companion never reloads WoW."
        )

        # Install folder row.
        folder_box = self.frame(self.surface, padding=6)
        folder_box.pack(fill="x", padx=4)
        self.folder_status = self.tk.StringVar(master=self.root)
        self.label(folder_box, "WoW install folder").pack(anchor="w")
        status_row = self.frame(folder_box)
        status_row.pack(fill="x", pady=(2, 0))
        folder_lbl = self.tk.Label(status_row, textvariable=self.folder_status,
                                   bg=folder_box.cget("bg"), fg=self.label(status_row, "").cget("fg"),
                                   anchor="w", justify="left")
        folder_lbl.pack(side="left", fill="x", expand=True)
        self.clear_folder_button = self.ttk.Button(status_row, text="Auto-detect", command=self.clear_folder)
        self.clear_folder_button.pack(side="right", padx=(4, 0))
        self.choose_folder_button = self.ttk.Button(status_row, text="Choose folder…", command=self.choose_folder)
        self.choose_folder_button.pack(side="right")

        # Per-edition status table.
        table_box = self.frame(self.surface, padding=6)
        table_box.pack(fill="x", padx=4)
        self.tree = self.ttk.Treeview(
            table_box, columns=("folder", "addon", "snapshot"), show="tree headings",
            height=4, selectmode="browse", style="Journal.Treeview",
        )
        style_journal_tree(self.tree)
        self.tree.heading("#0", text="Edition")
        self.tree.heading("folder", text="Install")
        self.tree.heading("addon", text="Addon")
        self.tree.heading("snapshot", text="Snapshot")
        self.tree.column("#0", width=130, minwidth=95, stretch=True)
        self.tree.column("folder", width=95, minwidth=75, stretch=False)
        self.tree.column("addon", width=180, minwidth=110, stretch=True)
        self.tree.column("snapshot", width=130, minwidth=90, stretch=False)
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self._row_selected)

        # Action bar for explicit install and snapshot check.
        controls = self.frame(self.surface, padding=6)
        controls.pack(fill="x", padx=4)
        default_edition = next(iter(FLAVORS))
        if hasattr(view, "profile") and isinstance(view.profile, dict):
            default_edition = next((k for k, v in FLAVORS.items() if v == view.profile.get("flavor")), default_edition)
        self.edition = self.tk.StringVar(master=self.root, value=default_edition)
        self.edition_choice = self.ttk.Combobox(controls, textvariable=self.edition, values=list(FLAVORS),
                                                state="readonly", width=16)
        self.edition_choice.pack(side="left")
        self.install_button = self.ttk.Button(controls, text="Install addon", style="Primary.TButton",
                                              command=self.install_addon)
        self.install_button.pack(side="left", padx=(6, 4))
        self.check_button = self.ttk.Button(controls, text="Check snapshot", command=self.check_snapshot)
        self.check_button.pack(side="left", padx=(0, 4))
        self.refresh_button = self.ttk.Button(controls, text="Refresh", command=self.refresh)
        self.refresh_button.pack(side="left")

        # Snapshot check report output.
        report_box = self.frame(self.surface, padding=6)
        report_box.pack(fill="both", expand=True, padx=4)
        report_hdr = self.frame(report_box)
        report_hdr.pack(fill="x")
        self.label(report_hdr, "Snapshot health report (path-free & safe to share)").pack(side="left")
        self.copy_report_button = self.ttk.Button(report_hdr, text="Copy report", command=self.copy_report,
                                                  state="disabled")
        self.copy_report_button.pack(side="right")
        self.report_text = self.text(
            report_box,
            "Press Check snapshot to verify the selected edition's latest WoWCompanion SavedVariables.",
        )

        # Assistive input status (read-only + explicit safety Stop).
        assist_box = self.frame(self.surface, padding=6)
        assist_box.pack(fill="x", padx=4, pady=(0, 4))
        self.assist_status = self.tk.StringVar(master=self.root)
        assist_lbl = self.tk.Label(assist_box, textvariable=self.assist_status,
                                   bg=assist_box.cget("bg"), fg=self.label(assist_box, "").cget("fg"),
                                   anchor="w", justify="left", wraplength=440)
        assist_lbl.pack(side="left", fill="x", expand=True)
        self.stop_assist_button = self.ttk.Button(assist_box, text="Stop assistive input",
                                                  command=self.stop_assistive, state="disabled")
        self.stop_assist_button.pack(side="right", padx=(6, 0))

        self.refresh()
        self.show()

    def _current_roots(self):
        settings = wtf.load_settings(self.settings_path)
        configured = settings.get("wow_root")
        return configured, self.roots_fn(configured)

    def _row_selected(self, _event=None):
        sel = self.tree.selection()
        if sel:
            label = next((k for k, v in FLAVORS.items() if v == sel[0]), None)
            if label:
                self.edition.set(label)

    def refresh(self):
        configured, found_roots = self._current_roots()
        if configured:
            self.folder_status.set(
                f"Custom folder configured · {len(found_roots)} WoW install root(s) detected."
            )
            self.clear_folder_button.configure(state="normal")
        elif found_roots:
            self.folder_status.set(f"Auto-detected {len(found_roots)} WoW install root(s).")
            self.clear_folder_button.configure(state="disabled")
        else:
            self.folder_status.set("No WoW install folder detected. Choose your World of Warcraft folder.")
            self.clear_folder_button.configure(state="disabled")

        self.tree.delete(*self.tree.get_children())
        self.rows = inspect_editions(found_roots)
        for row in self.rows:
            self.tree.insert(
                "", "end", iid=row["flavor"], text=row["label"],
                values=(row["folder_state"], row["addon_state"], row["snapshot_state"]),
            )
        selected_flavor = FLAVORS.get(self.edition.get())
        if selected_flavor and self.tree.exists(selected_flavor):
            self.tree.selection_set(selected_flavor)
        self._refresh_assist()

    def _refresh_assist(self):
        status = read_assist_status(self.assist_path)
        if status.get("error"):
            self.assist_status.set("Assistive input: local state database is unreadable.")
            self.stop_assist_button.configure(state="disabled")
            return
        if not status["configured"]:
            self.assist_status.set("Assistive input: Stopped (not configured). Configure via CLI if needed.")
            self.stop_assist_button.configure(state="disabled")
            return
        state = "Enabled" if status["enabled"] else "Stopped"
        if status["stub"]:
            state += " (stub mode)"
        bindings = ", ".join(f"{action}={chord}" for action, chord in sorted(status["bindings"].items())) or "none"
        self.assist_status.set(f"Assistive input: {state} · Bindings: {bindings}")
        self.stop_assist_button.configure(state="normal" if status["enabled"] else "disabled")

    def choose_folder(self):
        from tkinter import filedialog
        chosen = filedialog.askdirectory(parent=self.root, title="Choose your World of Warcraft install folder")
        if not chosen:
            return
        try:
            wtf.save_settings(self.settings_path, wow_root=chosen)
        except OSError:
            self.notice.set("Could not save the WoW folder setting.")
            return
        self.notice.set("Saved WoW install folder setting.")
        self.refresh()

    def clear_folder(self):
        try:
            data = wtf.load_settings(self.settings_path)
            data.pop("wow_root", None)
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            import json
            self.settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            self.notice.set("Could not update the WoW folder setting.")
            return
        self.notice.set("Cleared custom folder; using automatic WoW install detection.")
        self.refresh()

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.install_button.configure(state=state)
        self.check_button.configure(state=state)
        self.refresh_button.configure(state=state)

    def _run_bg(self, work, on_done):
        if self.future is not None or self.closed:
            self.notice.set("Wait for the current check or install to finish.")
            return False
        self._set_busy(True)
        self.future = (self.worker.submit(work), on_done)
        self._poll()
        return True

    def _poll(self):
        if self.closed or self.future is None:
            return
        fut, on_done = self.future
        if fut.done():
            self.future = None
            self.after = None
            self._set_busy(False)
            try:
                result = fut.result()
            except Exception as error:
                self.notice.set(str(error) or "That operation failed.")
                return
            on_done(result)
            return
        self.after = self.root.after(60, self._poll)

    def install_addon(self):
        label = self.edition.get()
        flavor = FLAVORS.get(label)
        _configured, found_roots = self._current_roots()
        if not found_roots:
            self.notice.set("No WoW install folder found. Choose your World of Warcraft folder first.")
            return
        self.notice.set(f"Installing WoW Companion addon v{check.ADDON_VERSION} for {label}…")

        def work():
            return self.install_fn(found_roots, only=flavor)

        def done(installed):
            self.refresh()
            if installed:
                self.notice.set(
                    f"Installed WoW Companion v{check.ADDON_VERSION} for {', '.join(installed)}. "
                    "Enable WoW Companion at character select and run /reload in game."
                )
            else:
                self.notice.set(
                    f"No active {label} WTF folder was found. Start that edition at least once so WoW creates "
                    "its WTF folder, then try Install addon again."
                )

        self._run_bg(work, done)

    def check_snapshot(self):
        label = self.edition.get()
        flavor = FLAVORS.get(label)
        _configured, found_roots = self._current_roots()
        if not found_roots:
            self.notice.set("No WoW install folder found. Choose your World of Warcraft folder first.")
            return
        self.notice.set(f"Checking latest saved snapshot for {label}…")

        def work():
            return run_snapshot_check(found_roots, flavor)

        def done(text):
            replace_text(self.report_text, text)
            self.copy_report_button.configure(state="normal")
            self.notice.set(f"Finished snapshot check for {label}. Refresh in a Quest or Character window to view data.")
            self.refresh()

        self._run_bg(work, done)

    def copy_report(self):
        text = self.report_text.get("1.0", "end-1c").strip()
        if not text:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.notice.set("Copied snapshot health report to the clipboard.")
        except self.tk.TclError:
            self.notice.set("Could not copy the report. Select the text and copy manually.")

    def stop_assistive(self):
        if not self.assist_path.is_file():
            self._refresh_assist()
            return
        try:
            from .assist import Assistant
            Assistant(self.assist_path, None).enable(False)
            self.notice.set("Assistive input stopped. No further game key chords can be sent until re-enabled.")
        except (OSError, sqlite3.Error):
            self.notice.set("Could not update assistive input state.")
        self._refresh_assist()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.after is not None:
            try:
                self.root.after_cancel(self.after)
            except Exception:
                pass
            self.after = None
        self.worker.shutdown(wait=False)
        if getattr(self.manager, "_setup_health_dialog", None) is self:
            self.manager._setup_health_dialog = None
        self.root.destroy()
