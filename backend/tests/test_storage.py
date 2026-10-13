import hashlib

import pytest

from researchos.api.errors import ApiError
from researchos.infrastructure.storage import LocalFileStore


async def chunks(data):
    for position in range(0, len(data), 3):
        yield data[position : position + 3]


def test_bounded_streaming_and_private_generated_paths(tmp_path):
    import asyncio

    data = b"%PDF-1.7\nfixture\n%%EOF\n"
    store = LocalFileStore(tmp_path)
    upload = asyncio.run(store.accept(chunks(data), 100))
    assert upload.sha256 == hashlib.sha256(data).hexdigest()
    assert upload.byte_size == len(data)
    assert store.path(upload.key).read_bytes() == data
    store.delete(upload.key)
    store.delete(upload.key)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "data,limit,status",
    [
        (b"not a PDF", 100, 422),
        (b"%PDF-1.7\nmissing end", 100, 422),
        (b"%PDF-1.7\n" + b"x" * 200, 100, 413),
    ],
)
def test_rejected_uploads_leave_no_files(tmp_path, data, limit, status):
    import asyncio

    store = LocalFileStore(tmp_path)
    with pytest.raises(ApiError) as error:
        asyncio.run(store.accept(chunks(data), limit))
    assert error.value.status_code == status
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("key", ["../escape.pdf", "/absolute.pdf", "A" * 32 + ".pdf", "bad.pdf"])
def test_storage_keys_cannot_traverse_paths(tmp_path, key):
    with pytest.raises(ValueError):
        LocalFileStore(tmp_path).path(key)


def test_interrupted_stream_is_cleaned(tmp_path):
    import asyncio

    async def interrupted():
        yield b"%PDF-1.7\n"
        raise OSError("fixture interruption")

    with pytest.raises(OSError):
        asyncio.run(LocalFileStore(tmp_path).accept(interrupted(), 100))
    assert list(tmp_path.iterdir()) == []
