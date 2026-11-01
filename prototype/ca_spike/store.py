"""Storage adapter boundary. The evidence model never depends on a concrete store.

``FileArtifactStore`` keeps one directory per run with one JSON artifact per logical
relation group. A future PostgreSQL adapter implements the same three methods; see
docs/spikes/CA-SPIKE-001.md for the mapping intent.
"""

import json
from pathlib import Path

from .canonical import canonical_bytes, loads_strict

MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


class ArtifactMissing(FileNotFoundError):
    pass


class FileArtifactStore:
    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)

    def put(self, name, obj):
        canonical_bytes(obj)  # refuse anything that is not canonically encodable
        self.run_dir.mkdir(parents=True, exist_ok=True)
        text = json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
        (self.run_dir / name).write_bytes(text.encode("utf-8"))

    def get(self, name):
        path = self.run_dir / name
        if not path.is_file():
            raise ArtifactMissing(name)
        return loads_strict(path.read_bytes(), max_bytes=MAX_ARTIFACT_BYTES)

    def has(self, name):
        return (self.run_dir / name).is_file()
