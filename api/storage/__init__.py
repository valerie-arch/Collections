"""Storage abstraction (filesystem dev, S3-compatible prod)."""

from api.storage.base import Storage
from api.storage.filesystem import FilesystemStorage
from api.storage.factory import get_storage

__all__ = ["Storage", "FilesystemStorage", "get_storage"]
