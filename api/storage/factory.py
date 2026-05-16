"""Storage backend selector."""

from functools import lru_cache

from api.config import settings
from api.storage.base import Storage
from api.storage.filesystem import FilesystemStorage


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    backend = settings.STORAGE_BACKEND.lower()
    if backend == "filesystem":
        return FilesystemStorage(settings.STORAGE_PATH)
    if backend == "s3":
        raise NotImplementedError("S3 backend lands in Sprint 5; set STORAGE_BACKEND=filesystem")
    raise ValueError(f"unknown STORAGE_BACKEND: {settings.STORAGE_BACKEND}")
