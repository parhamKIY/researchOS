import hashlib
import os
import re
import uuid
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from researchos.api.errors import ApiError


@dataclass
class StoredUpload:
    key: str
    sha256: str
    byte_size: int


class FileStore(Protocol):
    async def accept(self, chunks: AsyncIterable[bytes], limit: int) -> StoredUpload: ...
    def path(self, key: str) -> Path: ...
    def delete(self, key: str) -> None: ...


class LocalFileStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def path(self, key: str) -> Path:
        if re.fullmatch(r"[a-f0-9]{32}\.pdf", key) is None:
            raise ValueError("Invalid private storage key")
        return self.root / key

    def delete(self, key: str):
        self.path(key).unlink(missing_ok=True)

    async def accept(self, chunks: AsyncIterable[bytes], limit: int) -> StoredUpload:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = f"{uuid.uuid4().hex}.pdf"
        destination = self.path(key)
        temporary = destination.with_suffix(".tmp")
        digest = hashlib.sha256()
        size = 0
        head = bytearray()
        tail = b""
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > limit:
                        raise ApiError(413, "upload_too_large", "PDF exceeds the upload size limit")
                    if len(head) < 16:
                        head.extend(chunk[: 16 - len(head)])
                    tail = (tail + chunk[-1024:])[-1024:]
                    digest.update(chunk)
                    handle.write(chunk)
                if not re.match(
                    rb"%PDF-(1\.[0-7]|2\.0)[\r\n ]", head
                ) or not tail.rstrip().endswith(b"%%EOF"):
                    raise ApiError(422, "invalid_pdf", "File must have a PDF header and end marker")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            return StoredUpload(key, digest.hexdigest(), size)
        finally:
            temporary.unlink(missing_ok=True)
