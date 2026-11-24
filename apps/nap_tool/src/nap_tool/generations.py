# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Immutable output generations switched by a pointer file (ADR-0006)."""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from filelock import FileLock, Timeout

from nap_tool.data import atomic_write_bytes

VERSIONS_DIR = ".versions"  # holds output generations; see ADR-0006


def json_bytes(value: object) -> bytes:
    """Serialize a value as indented, key-sorted UTF-8 JSON with a trailing newline.

    Args:
        value: JSON-serializable value.

    Returns:
        Encoded JSON text.
    """
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def csv_bytes(rows: list[dict], headers: list[str]) -> bytes:
    """Serialize dict rows as UTF-8 CSV with LF line endings.

    Args:
        rows: Rows keyed by header name.
        headers: Column names, in output order.

    Returns:
        Encoded CSV text including the header line.
    """
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def write_pointer(pointer: Path, target: str) -> None:
    """Atomically write a pointer file that names its target.

    Args:
        pointer: Pointer file; its directory is created if missing.
        target: Name the pointer holds.

    Raises:
        PermissionError: If the pointer stays in use by another process.
    """
    pointer.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(pointer, target.encode("utf-8"))


def is_generation(scheme_id: int, name: str) -> bool:
    """Tell whether a name is an output generation of a scheme.

    Args:
        scheme_id: Harmonization scheme.
        name: Candidate directory name under `.versions/`.

    Returns:
        True for `scheme_<scheme>_<32 hex>`; separators and `..` never match.
    """
    return re.fullmatch(rf"scheme_{scheme_id}_[0-9a-f]{{32}}", name) is not None


def publish_pointer(set_directory: Path, scheme_id: int, generation: str) -> None:
    """Atomically point a scheme at an existing output generation.

    Args:
        set_directory: `<stage>/set_<set>` directory.
        scheme_id: Harmonization scheme.
        generation: Directory name under `.versions/`.

    Raises:
        ValueError: If the generation name does not belong to the scheme.
        PermissionError: If the pointer stays in use by another process.
    """
    if not is_generation(scheme_id, generation):
        raise ValueError(f"Invalid output generation for scheme {scheme_id}")
    write_pointer(_pointer(set_directory, scheme_id), generation)


def published_directory(set_directory: Path, scheme_id: int) -> Path:
    """Return the output generation a scheme's pointer names.

    Args:
        set_directory: `<stage>/set_<set>` directory.
        scheme_id: Harmonization scheme.

    Returns:
        Generation directory under `.versions/`.

    Raises:
        FileNotFoundError: If the scheme has no published output.
        ValueError: If the pointer is malformed.
    """
    pointer = _pointer(set_directory, scheme_id)
    generation = pointer.read_text(encoding="utf-8").strip()
    if not is_generation(scheme_id, generation):
        raise ValueError(f"Malformed output pointer: {pointer.name}")
    return set_directory / VERSIONS_DIR / generation


def _pointer(set_directory: Path, scheme_id: int) -> Path:
    return set_directory / f"scheme_{scheme_id}.current"


@contextmanager
def scheme_lock(set_directory: Path, scheme_id: int, busy_message: str) -> Iterator[None]:
    """Hold the per-scheme lock of a stage directory for one run.

    Args:
        set_directory: `<stage>/set_<set>` directory; created if missing.
        scheme_id: Harmonization scheme.
        busy_message: Error text when another run holds the lock.

    Raises:
        ValueError: If the lock is held by another run.
    """
    set_directory.mkdir(parents=True, exist_ok=True)
    try:
        acquired = FileLock(set_directory / f".scheme_{scheme_id}.lock", timeout=0).acquire()
    except Timeout as error:
        raise ValueError(busy_message) from error
    with acquired:
        yield


def publish_generation(
    set_directory: Path,
    scheme_id: int,
    contents: dict[str, bytes],
    check: Callable[[], None],
) -> Path:
    """Write a complete generation, re-check the inputs, then switch the pointer.

    All files switch together; on any failure the new generation is removed and the
    previous one stays current.

    Args:
        set_directory: `<stage>/set_<set>` directory.
        scheme_id: Harmonization scheme.
        contents: File name → content of the generation.
        check: Raises if the inputs changed while the run was computing.

    Returns:
        The published generation directory.

    Raises:
        Exception: Whatever `check` raises.
        ValueError: If the generation name is invalid (from `publish_pointer`).
        PermissionError: If the pointer stays in use by another process.
    """
    versions = set_directory / VERSIONS_DIR
    versions.mkdir(parents=True, exist_ok=True)
    generation = f"scheme_{scheme_id}_{uuid.uuid4().hex}"
    destination = versions / generation
    destination.mkdir()
    try:
        for name, content in contents.items():
            (destination / name).write_bytes(content)
        check()
        publish_pointer(set_directory, scheme_id, generation)
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination
