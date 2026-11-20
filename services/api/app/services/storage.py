"""Report photo storage: Azure Blob Storage (or Azurite locally), with a local-folder fallback."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("viasegura.storage")

MEDIA_NAME = re.compile(r"^[a-z0-9][a-z0-9/_-]{0,200}\.jpg$")


class MediaStorage(Protocol):
    async def save(self, name: str, data: bytes, content_type: str) -> None: ...

    async def load(self, name: str) -> bytes | None: ...


def check_name(name: str) -> str:
    if not MEDIA_NAME.fullmatch(name) or ".." in name:
        raise ValueError("invalid media name")
    return name


class LocalMediaStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        path = (self.root / check_name(name)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("invalid media name")
        return path

    async def save(self, name: str, data: bytes, content_type: str) -> None:
        path = self._path(name)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(write)

    async def load(self, name: str) -> bytes | None:
        path = self._path(name)
        return await asyncio.to_thread(path.read_bytes) if path.exists() else None


class AzureBlobMediaStorage:
    """Private container; photos are served through the API (no public blob access)."""

    def __init__(self, connection_string: str, container: str) -> None:
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient.from_connection_string(connection_string)
        self.container = service.get_container_client(container)
        self._ready = False

    def _ensure_container(self) -> None:
        from azure.core.exceptions import ResourceExistsError

        if not self._ready:
            with contextlib.suppress(ResourceExistsError):
                self.container.create_container()
            self._ready = True

    async def save(self, name: str, data: bytes, content_type: str) -> None:
        from azure.storage.blob import ContentSettings

        def upload() -> None:
            self._ensure_container()
            self.container.upload_blob(
                check_name(name),
                data,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )

        await asyncio.to_thread(upload)

    async def load(self, name: str) -> bytes | None:
        from azure.core.exceptions import ResourceNotFoundError

        def download() -> bytes | None:
            try:
                return self.container.download_blob(check_name(name)).readall()
            except ResourceNotFoundError:
                return None

        return await asyncio.to_thread(download)


def build_storage(connection_string: str, container: str, media_dir: str) -> MediaStorage:
    if connection_string:
        logger.info("media_storage", extra={"backend": "azure_blob", "container": container})
        return AzureBlobMediaStorage(connection_string, container)
    logger.info("media_storage", extra={"backend": "local", "path": media_dir})
    return LocalMediaStorage(media_dir)
