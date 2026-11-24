# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Hash-named data versions behind a pointer file, shared by the place data sources."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from nap_tool.data import atomic_write_bytes, checked_file
from nap_tool.generations import json_bytes, write_pointer

VERSION_RE = re.compile(r"[0-9a-f]{8}")
MANIFEST_FILE = "manifest.json"


@dataclass(frozen=True)
class StoreResult:
    """Outcome of ``VersionedSource.store``.

    ``changed`` is False when the current version was kept; ``repaired`` tells that the
    current version was damaged and has been rebuilt.
    """

    version: str
    changed: bool
    repaired: bool
    manifest: dict


@dataclass(frozen=True)
class VersionedSource:
    """A downloaded source stored as hash-named versions behind a pointer file.

    A version ``<directory>/<name>/<sha8>/`` holds the unchanged download (``source_file``),
    the prepared lookup (``lookup_file``) and ``manifest.json``; the manifest records the
    download's SHA-256 under ``sha256`` and the lookup's under ``lookup_key``. The pointer
    ``<directory>/<name>.current`` names the current version.

    Attributes:
        directory: Folder under the data repository root, for example ``place_data``.
        name: Source name, for example ``gn250``.
        label: Human name used in messages, for example ``place data``.
        manifest_keys: Keys a valid manifest contains.
        classes_key: Manifest key of the configured classes the lookup was built for.
        source_file: File name of the unchanged download.
        lookup_file: File name of the prepared lookup, for example ``places.csv``.
    """

    directory: str
    name: str
    label: str
    manifest_keys: tuple[str, ...]
    classes_key: str
    source_file: str
    lookup_file: str

    @property
    def lookup_key(self) -> str:
        """Manifest key of the lookup's SHA-256: ``places.csv`` -> ``places_sha256``."""
        return f"{Path(self.lookup_file).stem}_sha256"

    def relative(self, version: str) -> str:
        """Path of a version folder relative to the data repository root.

        Args:
            version: 8-hex-digit version.

        Returns:
            ``<directory>/<name>/<version>``.
        """
        return f"{self.directory}/{self.name}/{version}"

    def current_version(self, root: Path) -> str | None:
        """Version the pointer names.

        Args:
            root: Data repository root.

        Returns:
            The 8-hex-digit version, or None if there is no pointer.

        Raises:
            ValueError: If the pointer is malformed.
        """
        pointer = root / self.directory / f"{self.name}.current"
        if not pointer.is_file():
            return None
        version = pointer.read_text(encoding="utf-8").strip()
        if not VERSION_RE.fullmatch(version):
            raise ValueError(f"Malformed {self.label} pointer: {pointer}")
        return version

    def usable_version(self, root: Path) -> str | None:
        """Version the pointer names, or None if it is missing or malformed.

        Args:
            root: Data repository root.

        Returns:
            The 8-hex-digit version, or None; a malformed pointer is overwritten by the next
            ``store``.
        """
        try:
            return self.current_version(root)
        except ValueError:
            return None

    def manifest(self, root: Path, version: str) -> dict:
        """Read and validate the manifest of a version.

        Args:
            root: Data repository root.
            version: Version to read.

        Returns:
            The manifest.

        Raises:
            RuntimeError: If the manifest is unreadable, not an object, or lacks a key.
        """
        relative = f"{self.relative(version)}/{MANIFEST_FILE}"
        try:
            manifest = json.loads((root / relative).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError(f"Missing or modified {self.label} manifest: {relative}") from error
        if not isinstance(manifest, dict) or not set(self.manifest_keys) <= manifest.keys():
            raise RuntimeError(
                f"Malformed {self.label} manifest: {relative} lacks "
                f"{', '.join(self.manifest_keys)} or is not an object"
            )
        return manifest

    def verified(self, root: Path, version: str, file_name: str, digest: str) -> Path:
        """A file of a version, checked against its SHA-256.

        Args:
            root: Data repository root.
            version: Version the file belongs to.
            file_name: File name inside the version folder.
            digest: Expected SHA-256.

        Returns:
            The verified path.

        Raises:
            RuntimeError: If the file is missing or modified.
        """
        return checked_file(root, f"{self.relative(version)}/{file_name}", digest)

    def load_current(self, root: Path) -> tuple[str, dict, Path] | None:
        """The current version with its manifest and hash-checked lookup file.

        Args:
            root: Data repository root.

        Returns:
            Version, manifest and lookup path; None if there is no pointer.

        Raises:
            ValueError: If the pointer is malformed.
            RuntimeError: If the manifest is unusable or the lookup is missing or modified.
        """
        version = self.current_version(root)
        if version is None:
            return None
        manifest = self.manifest(root, version)
        path = self.verified(root, version, self.lookup_file, manifest[self.lookup_key])
        return version, manifest, path

    def write(self, root: Path, version: str, files: dict[str, bytes]) -> None:
        """Write the files of a version atomically, then make it current.

        Args:
            root: Data repository root.
            version: 8-hex-digit version.
            files: File name to content; put ``manifest.json`` last.

        Raises:
            OSError: If a file or the pointer cannot be written (PermissionError included).
        """
        folder = root / self.relative(version)
        folder.mkdir(parents=True, exist_ok=True)
        for file_name, content in files.items():
            atomic_write_bytes(folder / file_name, content)
        write_pointer(root / self.directory / f"{self.name}.current", version)

    def store(
        self,
        root: Path,
        content: bytes,
        *,
        classes: list[str] | None,
        build: Callable[[bytes], tuple[bytes, dict]],
    ) -> StoreResult:
        """Make a download the current version, building its lookup unless it is current.

        The current version is kept when it holds the same download, all its files verify
        and it was built for the same classes (in any order). A damaged current version is
        rebuilt and reported as repaired.

        Args:
            root: Data repository root.
            content: The download.
            classes: Configured classes; None always rebuilds (``--force``).
            build: Turns the download into the lookup bytes and the manifest entries; the
                download's and the lookup's SHA-256 are added here.

        Returns:
            Version (first 8 hex digits of the download's SHA-256), whether it changed,
            whether it was repaired, and the manifest.

        Raises:
            ValueError: If ``build`` rejects the download.
            OSError: If the version cannot be written (PermissionError included).
        """
        digest = hashlib.sha256(content).hexdigest()
        version = digest[:8]
        repaired = False
        if classes is not None and version == self.usable_version(root):
            manifest = self._intact_manifest(root, version, digest)
            if manifest is None:
                repaired = True
            elif set(manifest[self.classes_key] or []) == set(classes):
                return StoreResult(version, False, False, manifest)
        lookup, entries = build(content)
        manifest = {
            **entries,
            "sha256": digest,
            self.lookup_key: hashlib.sha256(lookup).hexdigest(),
        }
        files = {self.source_file: content, self.lookup_file: lookup}
        self.write(root, version, {**files, MANIFEST_FILE: json_bytes(manifest)})
        return StoreResult(version, True, repaired, manifest)

    def _intact_manifest(self, root: Path, version: str, digest: str) -> dict | None:
        """The manifest of the current version if all its files verify, else None."""
        try:
            loaded = self.load_current(root)
            self.verified(root, version, self.source_file, digest)
        except (OSError, ValueError, RuntimeError):
            return None
        return loaded[1] if loaded else None
