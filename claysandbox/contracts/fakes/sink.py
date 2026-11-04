"""In-memory event sink (the WS3 ``MemoryTracer`` plays this role in real runs)."""

from __future__ import annotations

import hashlib
import threading

from claysandbox.contracts.trace import EventT


class MemoryEventSink:
    def __init__(self, run_id: str = "run-1"):
        self.run_id = run_id
        self.events: list[EventT] = []
        self.blobs: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def emit(self, event: EventT) -> EventT:
        with self._lock:
            seq = len(self.events)
            stamped = event.model_copy(
                update={"run_id": self.run_id, "seq": seq, "event_id": f"{self.run_id}:{seq}"}
            )
            self.events.append(stamped)
            return stamped

    def put_blob(self, data: bytes) -> tuple[str, str]:
        digest = hashlib.sha256(data).hexdigest()
        with self._lock:
            self.blobs[f"blobs/{digest}"] = data
        return f"blobs/{digest}", digest

    @property
    def last_event_id(self) -> str | None:
        with self._lock:
            return self.events[-1].event_id if self.events else None

    def of_type(self, type_name: str) -> list[EventT]:
        return [e for e in self.events if e.type == type_name]
