from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class InMemoryStore:
    documents: dict[str, Any] = field(default_factory=dict)
    runs: dict[str, Any] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def save_document(self, document_id: str, payload: Any) -> None:
        with self.lock:
            self.documents[document_id] = payload

    def get_document(self, document_id: str) -> Any | None:
        with self.lock:
            return self.documents.get(document_id)

    def save_run(self, run_id: str, payload: Any) -> None:
        with self.lock:
            self.runs[run_id] = payload

    def get_run(self, run_id: str) -> Any | None:
        with self.lock:
            return self.runs.get(run_id)

