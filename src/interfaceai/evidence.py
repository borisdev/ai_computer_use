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

    def __init__(
        self, root: Path, goal: str, model: str | None = None, requested_by: str = "cli"
    ) -> None:
        if model is None:
            # Local import: vision_llm imports settings, and settings is read
            # by everything -- resolving here keeps evidence importable alone.
            from interfaceai.vision_llm import active_model

            model = active_model()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.dir = root / stamp
        self.dir.mkdir(parents=True, exist_ok=True)
        self.frames = self.dir / "frames"
        self.frames.mkdir(exist_ok=True)
        self._trace = self.dir / "trace.jsonl"
        self._n = 0
        # ⚠️ WHO ASKED IS EVIDENCE, NEVER A BRANCH. A developer at a terminal,
        # a test, and an agent calling this as a library all produce the SAME
        # run -- what differs is who to ask when it stops, and that is supplied
        # as an `operator`, not sniffed from a caller id. The moment behaviour
        # forks on this field, the tested path and the production path diverge
        # and the tested one is the one nobody runs.
        #
        # It is recorded because a run nobody can attribute is a run nobody can
        # question. The original schema had it on `jobs`; this is that field.
        self.event("run_started", goal=goal, model=model, requested_by=requested_by)

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
