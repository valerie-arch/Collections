"""Storage backend protocol."""

from typing import Iterable, Protocol


class Storage(Protocol):
    """Object/file storage interface — swappable filesystem ↔ S3."""

    def write_bytes(self, key: str, data: bytes) -> str:
        """Write bytes at `key`. Returns a canonical path/URI."""

    def write_text(self, key: str, data: str, encoding: str = "utf-8") -> str:
        ...

    def read_bytes(self, key: str) -> bytes:
        ...

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        ...

    def exists(self, key: str) -> bool:
        ...

    def list_keys(self, prefix: str) -> Iterable[str]:
        ...

    def delete(self, key: str) -> None:
        ...
