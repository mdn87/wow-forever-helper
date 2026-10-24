"""Visible controls for the optional local usage study."""

from datetime import datetime

from .chat import ChatError
from .theme import palette
from .usage_study import UsageStudy
from .window_frame import WindowFrame


class UsageDialog:
    def __init__(self, manager, window):
        from tkinter import ttk
        from .task_window import text_box
        self.manager, self.parent = manager, window.root
        self.study = UsageStudy(manager.activity_factory().storage)
        tk = manager.tk
        self.root = tk.Toplevel(self.parent)
        self.root.geometry("600x500")
        self.root.transient(self.parent)
        self.root.attributes("-topmost", self.parent.attributes("-topmost"))
        self.chrome = WindowFrame(self.root, title="Usage study", close=self.close, minimum=(480, 420))
        surface, colors = self.chrome.content, palette(self.parent)
        tk.Label(surface, text="Local feature and action counts only. No messages, screenshots, account details, or game content. Recording stops automatically at the end of the period.",
                 wraplength=440, justify="left", bg=colors.PANEL, fg=colors.TEXT).pack(fill="x", padx=12, pady=10)
        controls = tk.Frame(surface, bg=colors.PANEL)
        controls.pack(fill="x", padx=12)
        tk.Label(controls, text="Days:", bg=colors.PANEL, fg=colors.TEXT).pack(side="left")
        self.days = tk.StringVar(master=self.root, value="7")
        self.day_picker = ttk.Spinbox(controls, from_=1, to=30, textvariable=self.days, width=4)
        self.day_picker.pack(side="left", padx=5)
        self.start_button = ttk.Button(controls, text="Start study", command=self.start)
        self.start_button.pack(side="left", padx=5)
        self.stop_button = ttk.Button(controls, text="Stop recording", command=self.stop)
        self.stop_button.pack(side="left")
        footer = tk.Frame(surface, bg=colors.PANEL)
        footer.pack(side="bottom", fill="x", padx=12, pady=10)
        ttk.Button(footer, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(footer, text="Close", command=self.close).pack(side="right")
        self.report_text = text_box(tk, surface, bg=colors.PANEL, fg=colors.TEXT, font=("Segoe UI", 10))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        self.chrome.apply_native()

    def refresh(self, error=None):
        from .task_window import replace_text
        try:
            report = self.study.report()
            active = report["status"] == "active"
            self.start_button.configure(state="disabled" if active else "normal")
            self.day_picker.configure(state="disabled" if active else "normal")
            self.stop_button.configure(state="normal" if active else "disabled")
            lines = ["Status: " + report["status"].replace("_", " ")]
            if report.get("ends_at"):
                lines += ["Scheduled end: " + datetime.fromtimestamp(report["ends_at"]).astimezone().strftime("%Y-%m-%d %H:%M %Z")]
            lines += ["", "Counts show recorded actions, not attention or usefulness. Daily totals use UTC.", ""]
            for feature, actions in sorted(report.get("totals", {}).items()):
                lines += [feature.replace("_", " ").title() + ": " + ", ".join(f"{a} {n}" for a, n in sorted(actions.items()))]
            if not report.get("totals"):
                lines += ["No actions recorded yet."]
            if error:
                lines.insert(0, error)
            replace_text(self.report_text, "\n".join(lines))
        except (ChatError, OSError) as problem:
            replace_text(self.report_text, str(problem) if isinstance(problem, ChatError) else "Local study storage is unavailable.")

    def start(self):
        try:
            self.study.start(int(self.days.get()))
        except (ChatError, OSError, ValueError):
            self.refresh("Could not start the study. Choose 1–30 days and check local storage.")
        else:
            self.refresh()

    def stop(self):
        try:
            self.study.stop()
        except (ChatError, OSError):
            self.refresh("Could not save the stop request. Recording has not been confirmed stopped.")
        else:
            self.refresh()

    def close(self):
        self.manager._usage_dialog = None
        self.root.destroy()
