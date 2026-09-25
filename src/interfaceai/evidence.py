"""Run evidence: a structured trace plus every frame the model was shown.

The brief (3.5) wants enough to understand and debug a run. A screenshot the
model actually saw is the only honest record of why it chose what it chose.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class EvidenceWriter:
    """A structured log plus every frame the model actually saw.

    The brief wants enough to understand and debug a run. A screenshot the model
    was shown is the only honest record of why it chose what it chose.
    """

    def __init__(self, root: Path, goal: str, model: str = "unset") -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.dir = root / stamp
        self.dir.mkdir(parents=True, exist_ok=True)
        self.frames = self.dir / "frames"
        self.frames.mkdir(exist_ok=True)
        self._trace = self.dir / "trace.jsonl"
        self._n = 0
        self.event("run_started", goal=goal, model=model)

    def event(self, kind: str, **fields: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(), "event": kind, **fields}
        with self._trace.open("a") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    def frame(self, png: bytes, label: str) -> Path:
        self._n += 1
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:40]
        path = self.frames / f"{self._n:03d}-{safe}.png"
        path.write_bytes(png)
        return path
