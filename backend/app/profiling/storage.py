"""Local document storage (design §35: "Documents: local volume (dev) or an
S3-compatible bucket"). This phase implements the local volume; swapping in
an S3-compatible backend later only requires a new implementation of the
same `save`/`read` shape, not a caller-side change.
"""
from __future__ import annotations

from pathlib import Path

from app.config import get_settings


class DocumentStorage:
    def __init__(self, base_dir: Path | None = None) -> None:
        settings = get_settings()
        self.base_dir = base_dir if base_dir is not None else Path(settings.document_storage_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, learner_id: str, document_id: str, filename: str, content: bytes) -> str:
        learner_dir = self.base_dir / learner_id
        learner_dir.mkdir(parents=True, exist_ok=True)
        # Path(filename).name strips any directory components -- a path-traversal guard
        # against a filename like "../../etc/passwd" (design §29 "Malicious uploads").
        safe_name = Path(filename).name or "upload"
        path = learner_dir / f"{document_id}_{safe_name}"
        path.write_bytes(content)
        return str(path)

    def read(self, storage_ref: str) -> bytes:
        return Path(storage_ref).read_bytes()
