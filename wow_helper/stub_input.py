"""Stand-in input backend for testing without a character: records the chord, sends nothing."""

import json
from pathlib import Path
import time


class StubInput:
    stub = True

    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = path, clock

    def press(self, chord):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as log:
            log.write(json.dumps({"at": round(self.clock(), 3), "key": chord.name}) + "\n")
