# Recording-log foundation

F19 has an internal Python log store and lifecycle controller. There is no recording UI, native capture scheduler, NVIDIA directory observer, video alignment, transcription, or agent analysis in this increment. Runtime behavior and crash recovery remain unverified: tests and live measurements were skipped at the operator's request.

## Ownership and lifecycle

`wow_helper.recording_controller.RecordingController` owns a log through an OS-released file lock. Public methods serialize access within the process. Creating a controller makes a `ready` log. `start(source_available=...)` explicitly enters `recording` or `unavailable`; these are the companion log's states, not observations of an external recorder.

`pause()` preserves a deliberate user pause. `source_changed(True)` can recover an unavailable source but cannot undo that pause. `resume(source_available=...)` is explicit. `stop()` is terminal for that log. A new recording needs a new log. No lifecycle operation launches a worker or sends a provider request.

`begin_capture()` reserves one worker slot and returns an opaque ticket. A future capture adapter must call `finish_capture(ticket, sample, captured_at=...)` **after the worker exits**, including after cancellation. Pause, source loss, stop, write failure, and close invalidate tickets. A stale completion is discarded, and a new ticket cannot be issued while an earlier worker is outstanding. `close()` retains the log lock until an outstanding worker reports its exit. An application integrating native capture must also enforce one capture worker across logs; this module owns a single log only.

The foundation accepts immutable sample bytes, at most 8,000,000 bytes each. They are opaque local blobs, not validated images. A future image adapter must encode, validate, and mask its images before using the store. A missing or rejected sample records a `capture_failed` gap while the log is active. The scheduler can explicitly record a `missed_interval` gap; the foundation never schedules catch-up captures.

## Durable format and recovery

The default destination is the project's ignored `.runtime/recording-logs/`. This foundation accepts destinations only within the project's ignored runtime directory. Selecting a bulk destination outside the project remains a later explicit user flow.

Each UUID-named directory contains:

- `index.json`: version 1, log ID, current lifecycle state, and complete ordered events.
- `owner.lock`: process ownership, released by the OS after a crash.
- `sample-<UUID>.bin`: immutable sample bytes committed before their event references them.
- Any interrupted `write-<UUID>.tmp` files, preserved for inspection.

Events contain a sequence number, wall-clock time in Unix seconds, process-run UUID, monotonic elapsed seconds within that run, an allowlisted kind, and strictly validated details. Wall-clock adjustments do not reorder events. Unknown capture times remain `null`. This format contains no external video paths or claimed video offsets.

Indexes are bounded to 4,000,000 bytes and 10,000 events. The reader rejects unsupported versions, duplicate JSON keys, invalid transitions, repeated sample IDs, missing or wrong-sized referenced samples, file links, and malformed fields. `events(after=0, limit=100)` returns a copy of at most 1,000 complete events per call. This reader does not decode or verify the contents of sample blobs.

Writes use a unique temporary file, flush and sync it, then atomically replace the destination. POSIX directory entries are synced after replacement; Windows uses file flush and atomic replacement. Power-loss durability across all filesystems is unverified. Sample commit precedes index commit, so an interrupted index write can leave an orphan sample. Recovery counts orphan files and unfinished writes without deleting or truncating them. Damaged indexes are refused and kept.

Opening a log last persisted as `recording` or `unavailable` appends a recovery event and pauses it. It never replays captures. If that pause cannot be saved, the controller still exposes complete events, disables writes, and reports `recovery.pause_saved=False`. A write failure disables further writes and invalidates pending results. Stop can still stop the in-memory lifecycle; `last_confirmed_state` reports the last acknowledged index state. Close and reopen to resolve an uncertain write rather than retrying its event.

## Storage accounting

`StoragePolicy` defaults to a 256,000,000-byte log budget, a 1,000,000,000-byte free-space reserve, and zero assumed external video growth. The last default means external recording growth has **not been configured or measured**. It is not evidence that a video file has stopped growing.

Accounting includes referenced samples, orphan files, temporary files, the index, and the lock. It refuses excessive directory entries. Before a write, it checks both the final log budget and transient space for the replacement index plus any sample, while the old index still exists. It never silently evicts data when a budget is reached.

For the log's volume, supply an external growth rate in bytes per second and a horizon (default 600 seconds). Required free space is:

`pending writes + free-space reserve + external bytes per second × horizon seconds`

External output on another volume needs a separate `volume_budget(...)` evaluation with that volume's free space, reserve, and projected growth. The future application must evaluate every affected volume before collecting data. Estimates cannot prevent another recorder from filling a disk; this foundation controls only its own writes. It never decodes, hashes, repairs, remuxes, deletes, or stops an external recording.

## Internal API

Use `RecordingController.create(policy=...)` for a fresh ready log or `RecordingController.open(log_id, policy=...)` for a retained log. Both hold the log lock until closed. `status()`, `events()`, and `storage_report()` provide bounded local information without printing paths or contacting providers. Reopening with a smaller budget can refuse a log that exceeds that budget; the files remain intact.

The controller accepts injected wall and monotonic clocks; the store accepts an injected free-space reader. A future synthetic capture adapter can submit explicit sample bytes through tickets. No fake capture runner, runtime acceptance results, real recording-growth measurements, or finalization measurements are claimed in this increment.

The next F19 work is the planned measurement of external output growth and finalization, followed by app-level ownership, a real single-window capture worker, explicit controls, and stop/reserve checks. Video links and optional analysis follow in separate stages.
