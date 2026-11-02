"""Ask a chosen conversation about the last fight, with an optional reviewed combat-log digest."""

import queue
import threading

from .activities import FLAVORS
from .build_tutor import bounded, discussion_packet
from .chat import ChatError
from .imports import import_record
from .notebook_ui import DiscussionNotebook

DIGEST_LIMIT = 24_000


def prepare_fight_question(form):
    edition = form.get("edition")
    if edition not in FLAVORS:
        raise ChatError("Choose a supported game edition.")
    question = bounded(form.get("question"), "Question", 4000, True)
    digest = bounded(form.get("digest", ""), "Combat log digest", DIGEST_LIMIT)
    gaps = ["Player-written question; nothing was observed in game for this request."]
    if digest:
        gaps = [form.get("digest_status") or "Digest status unknown.",
                "Digest of the end of the local combat log, reviewed and possibly edited before sending.",
                "Aggregate damage cannot establish an exact cause of death."]
    else:
        gaps.append("No combat log digest was included.")
    data = import_record("combat log digest" if digest else "question only", "Unknown", edition,
                         {"question": question, "digest": digest or None},
                         coverage="Last encounter in the read part of the combat log." if digest else "None.",
                         warnings=gaps)
    packet = discussion_packet("Ask about the last fight", edition, question, data,
        "Answer the player's question about their last fight using only the supplied digest and question. "
        "Separate what the digest shows from your interpretation, and say when it cannot answer the question. "
        "Players appear as aliases; do not guess real identities. Do not claim an exact cause of death from "
        "aggregate damage. Suggest at most three concrete changes for the next attempt and what to check in the "
        "next digest. Use edition-specific sources for mechanics and link sources actually read. Never send game "
        "input, start a capture, or ask for the raw log.")
    packet["reports"]["fight"] = packet["reports"].pop("build")
    return packet


class FightQuestion(DiscussionNotebook):
    kind, title = "fight", "Ask about the last fight"
    prepare_form = staticmethod(prepare_fight_question)

    def make_fields(self):
        edition = next(key for key, value in FLAVORS.items() if value == self.view.profile["flavor"])
        self.field("edition", "Game edition", edition, list(FLAVORS))
        self.editor("question", "Question", "What should the agent look into? For example: why did we wipe "
                    "so fast on that pull?", parent=self.inputs)
        self.editors["question"].configure(height=5)
        self.fields["names"] = self.tk.StringVar(master=self.root, value=self.initial.get("names", "0"))
        self.fields["names"].trace_add("write", lambda *_: self.changed())
        self.ttk.Checkbutton(self.inputs, text="Include player names in the digest (otherwise Player 1, 2…)",
                             variable=self.fields["names"], onvalue="1", offvalue="0").pack(anchor="w", pady=(6, 0))
        # Kept only while this dialog is open; never written to drafts or Journal.
        self.own_name = self.tk.StringVar(master=self.root)
        self.label(self.inputs, "Your character name, to label you as You (optional, not saved)").pack(anchor="w", pady=(5, 0))
        self.ttk.Entry(self.inputs, textvariable=self.own_name).pack(fill="x")
        self.fields["digest_status"] = self.tk.StringVar(master=self.root, value=self.initial.get("digest_status", ""))
        bar = self.frame(self.inputs)
        bar.pack(fill="x", pady=(8, 0))
        self.read_button = self.ttk.Button(bar, text="Read combat log", command=self.read_log)
        self.read_button.pack(side="left")
        self.ttk.Button(bar, text="Remove digest", command=self.remove_digest).pack(side="left", padx=4)
        self.log_status = self.label(self.inputs, "Turn on combat logging in game with /combatlog before the pull. "
                                     "Reading starts only when you press Read combat log.")
        self.log_status.configure(wraplength=390, justify="left")
        self.log_status.pack(anchor="w", pady=(4, 0))
        self.editor("digest", "Digest", "What will be sent from the combat log. Edit or remove anything before "
                    "preparing the review.")
        self._results = queue.Queue()

    def changed(self):
        super().changed()
        self.view.notebook_drafts.get(self.kind, {}).pop("own_name", None)

    def read_log(self):
        from . import combat_log, wtf
        flavor = FLAVORS.get(self.fields["edition"].get())
        path = combat_log.find_combat_log(wtf.roots(), flavor) if flavor else None
        if path is None:
            self.notice.set("No combat log was found for that edition. Type /combatlog in game, play the pull, then read again.")
            return
        self.read_button.configure(state="disabled")
        self.notice.set("Reading the end of the combat log…")
        options = {"include_names": self.fields["names"].get() == "1", "own_name": self.own_name.get().strip() or None}

        def work():
            try:
                self._results.put(combat_log.last_encounter_digest(path, **options))
            except ChatError as error:
                self._results.put(error)
            except Exception:  # an unexpected parser failure must still re-enable the dialog
                self._results.put(ChatError("The combat log could not be digested. Remove or edit the digest and try again."))
        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self._finish_read)

    def _finish_read(self):
        try:
            result = self._results.get_nowait()
        except queue.Empty:
            if self.root.winfo_exists():
                self.root.after(100, self._finish_read)
            return
        self.read_button.configure(state="normal")
        if isinstance(result, ChatError):
            self.notice.set(str(result))
            return
        self.apply_digest(result)

    def apply_digest(self, result):
        from .task_window import replace_text
        text = result.get("text", "")
        replace_text(self.editors["digest"], text)
        self.editors["digest"].configure(state="normal")
        labels = {"ok": "Last encounter read.", "incomplete": "The last encounter has not ended in the log yet.",
                  "no_encounter_markers": "No encounter markers; the last 3 minutes were read.",
                  "unsupported_layout": "This log's damage layout is not recognised; no numbers are included.",
                  "empty": "The combat log has no fight data yet."}
        status = labels.get(result.get("status"), "Digest status unknown.")
        gaps = [g for g in result.get("gaps", []) if isinstance(g, str)]
        self.fields["digest_status"].set(" ".join([status] + gaps)[:2000])
        self.log_status.configure(text=status + " Review the Digest tab, then Prepare review.")
        self.notice.set(status)
        self.changed()

    def remove_digest(self):
        from .task_window import replace_text
        replace_text(self.editors["digest"], "")
        self.editors["digest"].configure(state="normal")
        self.fields["digest_status"].set("")
        self.changed()
