"""Content-addressed private asset storage on the configured local volume."""

import hashlib
import os
import re
from pathlib import Path

from app.settings import get_settings

_KEY_RE = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{64}$")


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def storage_key_for_hash(sha256: str) -> str:
    digest = sha256.lower()
    if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid SHA-256 hex digest")
    return f"{digest[:2]}/{digest}"


def _resolve_key_path(storage_key: str) -> Path:
    if not _KEY_RE.match(storage_key):
        raise ValueError(f"Unsafe storage key: {storage_key!r}")
    root = Path(get_settings().asset_storage_path).resolve()
    target = (root / storage_key).resolve()
    if root not in target.parents:
        raise ValueError("Resolved asset path escapes storage root")
    return target


def write_asset_bytes(sha256: str, data: bytes) -> str:
    """Write ``data`` to private content-addressed storage and return ``storage_key``."""
    storage_key = storage_key_for_hash(sha256)
    target = _resolve_key_path(storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        tmp = target.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_bytes(data)
        tmp.replace(target)
    return storage_key


def read_asset_bytes(storage_key: str) -> bytes:
    target = _resolve_key_path(storage_key)
    if not target.is_file():
        raise FileNotFoundError(f"Asset blob not found: {storage_key}")
    return target.read_bytes()
