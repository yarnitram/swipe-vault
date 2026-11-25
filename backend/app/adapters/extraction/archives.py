"""Safe ZIP expansion (FR-03): no traversal, symlinks, nested archives, bombs or executables."""

import io
import stat
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath


class UnsafeArchiveError(ValueError):
    """The whole archive is rejected."""


@dataclass
class ArchiveEntry:
    name: str
    data: bytes | None
    skipped_reason: str | None = None


_SKIP_PREFIXES = ("__MACOSX/",)
_SKIP_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
_NESTED_ARCHIVE_EXT = (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz")
MAX_COMPRESSION_RATIO = 200


def _is_unsafe_name(name: str) -> bool:
    if not name or "\x00" in name or name.startswith(("/", "\\")) or "\\" in name:
        return True
    if len(name) > 1 and name[1] == ":":
        return True
    return any(part == ".." for part in PurePosixPath(name).parts)


def iter_zip_entries(
    data: bytes,
    *,
    max_entries: int,
    max_expanded: int,
    max_entry_bytes: int,
) -> Iterator[ArchiveEntry]:
    """Validate the archive as a whole, then yield file entries (directories skipped).

    Raises :class:`UnsafeArchiveError` before yielding anything if the archive is unsafe.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnsafeArchiveError("Invalid ZIP archive") from exc
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise UnsafeArchiveError(f"Archive has {len(infos)} entries (limit {max_entries})")
    total = 0
    for info in infos:
        if _is_unsafe_name(info.filename):
            raise UnsafeArchiveError(f"Unsafe path in archive: {info.filename!r}")
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise UnsafeArchiveError(f"Symbolic link in archive: {info.filename!r}")
        if info.flag_bits & 0x1:
            raise UnsafeArchiveError("Encrypted archives are not supported")
        total += info.file_size
        if total > max_expanded:
            raise UnsafeArchiveError(f"Archive expands beyond {max_expanded} bytes")
        ratio = info.file_size / max(info.compress_size, 1) if info.compress_size else 0
        if ratio > MAX_COMPRESSION_RATIO and info.file_size > 1_000_000:
            raise UnsafeArchiveError(
                f"Suspicious compression ratio for {info.filename!r} (possible zip bomb)"
            )

    for info in infos:
        if info.is_dir():
            continue
        name = info.filename
        base = PurePosixPath(name).name
        if name.startswith(_SKIP_PREFIXES) or base in _SKIP_NAMES or base.startswith("._"):
            continue
        if name.lower().endswith(_NESTED_ARCHIVE_EXT):
            yield ArchiveEntry(name, None, "Nested archives are not supported in the MVP")
            continue
        if info.file_size > max_entry_bytes:
            yield ArchiveEntry(name, None, f"Entry exceeds {max_entry_bytes} bytes")
            continue
        # Read with a hard cap in case the header lies about the size.
        with zf.open(info) as fh:
            content = fh.read(max_entry_bytes + 1)
        if len(content) > max_entry_bytes or len(content) > info.file_size + 0:
            if len(content) != info.file_size:
                raise UnsafeArchiveError(f"Entry size mismatch for {name!r}")
        yield ArchiveEntry(name, content)
