# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Paths and content hashes for the external data repository."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv


def data_dir() -> Path:
    """Return the configured data repository.

    Returns:
        Absolute data repository path.

    Raises:
        RuntimeError: If NAP_DATA_DIR is missing or invalid.
    """
    load_dotenv()
    value = os.environ.get("NAP_DATA_DIR")
    if not value:
        raise RuntimeError("NAP_DATA_DIR is required; set it to the nap_data directory")
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"NAP_DATA_DIR does not exist: {root}")
    return root


def relative_path(root: Path, path: Path) -> str:
    """Return a safe, portable path relative to the data repository.

    Args:
        root: Data repository root.
        path: Path within the repository.

    Returns:
        POSIX relative path.

    Raises:
        ValueError: If path escapes the data repository.
    """
    return path.resolve().relative_to(root.resolve()).as_posix()


def resolve_path(root: Path, value: str) -> Path:
    """Resolve a stored path and reject traversal.

    Args:
        root: Data repository root.
        value: Stored relative path.

    Returns:
        Absolute path within root.

    Raises:
        ValueError: If the stored path escapes root.
    """
    path = (root / value).resolve()
    path.relative_to(root.resolve())
    return path


def sha256_file(path: Path) -> str:
    """Hash a file without loading it wholly into memory.

    Args:
        path: File to hash.

    Returns:
        Lowercase SHA-256 hexadecimal digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bytes(root: Path, relative: str, content: bytes) -> str:
    """Write immutable content into the data repository.

    Args:
        root: Data repository root.
        relative: Relative output path.
        content: Bytes to write.

    Returns:
        SHA-256 of content.

    Raises:
        ValueError: If an existing file has different content.
    """
    destination = resolve_path(root, relative)
    digest = hashlib.sha256(content).hexdigest()
    if destination.exists():
        if sha256_file(destination) != digest:
            raise ValueError(f"Refusing to overwrite different data: {relative}")
        return digest
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as output:
            output.write(content)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return digest


def checked_file(root: Path, relative: str, digest: str) -> Path:
    """Return a file only when its content matches the recorded hash.

    Args:
        root: Data repository root.
        relative: Stored relative path.
        digest: Expected SHA-256.

    Returns:
        Verified file path.

    Raises:
        RuntimeError: If the file is missing or modified.
    """
    path = resolve_path(root, relative)
    if not path.is_file() or sha256_file(path) != digest:
        raise RuntimeError(f"Missing or modified data file: {relative}")
    return path
