"""Filesystem-backed storage for local dev.

Keys are POSIX-style paths rooted under STORAGE_PATH. Subdirectories are
created on write. Reads raise FileNotFoundError if the key is absent.
"""

from pathlib import Path
from typing import Iterable


class FilesystemStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Normalize and prevent traversal outside the root.
        candidate = (self.root / key.lstrip("/")).resolve()
        if self.root not in candidate.parents and candidate != self.root:
            raise ValueError(f"key escapes storage root: {key}")
        return candidate

    def write_bytes(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def write_text(self, key: str, data: str, encoding: str = "utf-8") -> str:
        return self.write_bytes(key, data.encode(encoding))

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(key).decode(encoding)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list_keys(self, prefix: str) -> Iterable[str]:
        base = self._path(prefix)
        if not base.exists():
            return []
        if base.is_file():
            return [str(base.relative_to(self.root))]
        return [
            str(p.relative_to(self.root))
            for p in base.rglob("*")
            if p.is_file()
        ]

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()
