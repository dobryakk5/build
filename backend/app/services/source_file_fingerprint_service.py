"""SHA-256 fingerprinting of exact raw upload bytes before transformation."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterable

SOURCE_FILE_FINGERPRINT_ALGORITHM = "sha256"
DEFAULT_CHUNK_SIZE = 1024 * 1024


class SourceFileFingerprintError(ValueError):
    code = "source_file_fingerprint_error"


class EmptySourceFile(SourceFileFingerprintError):
    code = "empty_source_file"


@dataclass(frozen=True)
class SourceFileFingerprint:
    algorithm: str
    fingerprint: str
    size_bytes: int

    def as_dict(self) -> dict[str, str | int]:
        return {
            "source_file_fingerprint_algorithm": self.algorithm,
            "source_file_fingerprint": self.fingerprint,
            "source_file_size_bytes": self.size_bytes,
        }


def _finalize(digest: Any, size: int) -> SourceFileFingerprint:
    if size <= 0:
        raise EmptySourceFile("uploaded source file is empty")
    return SourceFileFingerprint(
        algorithm=SOURCE_FILE_FINGERPRINT_ALGORITHM,
        fingerprint=digest.hexdigest(),
        size_bytes=size,
    )


def fingerprint_raw_bytes(raw_uploaded_bytes: bytes | bytearray | memoryview) -> SourceFileFingerprint:
    raw = bytes(raw_uploaded_bytes)
    digest = hashlib.sha256()
    digest.update(raw)
    return _finalize(digest, len(raw))


def fingerprint_chunks(chunks: Iterable[bytes]) -> SourceFileFingerprint:
    digest = hashlib.sha256()
    size = 0
    for chunk in chunks:
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise TypeError("upload chunks must be bytes-like")
        raw = bytes(chunk)
        digest.update(raw)
        size += len(raw)
    return _finalize(digest, size)


def fingerprint_stream(stream: BinaryIO, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> SourceFileFingerprint:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise TypeError("binary upload stream must return bytes")
        digest.update(chunk)
        size += len(chunk)
    return _finalize(digest, size)


def fingerprint_file(path: str | Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> SourceFileFingerprint:
    with Path(path).open("rb") as stream:
        return fingerprint_stream(stream, chunk_size=chunk_size)
