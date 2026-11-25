"""File type detection by extension *and* content signature (FR-03)."""

from dataclasses import dataclass

SUPPORTED_KINDS = ("txt", "html", "pdf", "docx", "zip")

_EXT_TO_KIND = {
    ".txt": "txt",
    ".text": "txt",
    ".md": "txt",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".docx": "docx",
    ".zip": "zip",
}
MEDIA_TYPES = {
    "txt": "text/plain",
    "html": "text/html",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "zip": "application/zip",
}

# Signatures of content we never accept regardless of extension.
_EXECUTABLE_SIGNATURES = (
    b"MZ",  # Windows PE
    b"\x7fELF",  # ELF
    b"\xcf\xfa\xed\xfe",  # Mach-O
    b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe",  # Mach-O fat / Java class
    b"#!",  # shell scripts
)
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc/.xls (macro-capable)
_RAR_SIGNATURES = (b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c", b"\x1f\x8b")


class UnsupportedFileError(ValueError):
    pass


@dataclass(frozen=True)
class DetectedType:
    kind: str
    media_type: str


def _ext(filename: str) -> str:
    name = filename.lower().rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


def _looks_textual(data: bytes) -> bool:
    sample = data[:8192]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        # Allow single-byte encodings (cp1252) as long as there are few control characters.
        controls = sum(1 for b in sample if b < 9 or (13 < b < 32))
        return controls <= len(sample) * 0.01


def detect_file_type(filename: str, data: bytes) -> DetectedType:
    """Return the detected kind or raise :class:`UnsupportedFileError`."""
    if not data:
        raise UnsupportedFileError("File is empty")
    if data.startswith(_EXECUTABLE_SIGNATURES):
        raise UnsupportedFileError("Executable or script content is not allowed")
    if data.startswith(_OLE_SIGNATURE):
        raise UnsupportedFileError("Legacy Office (OLE) documents are not supported; convert to DOCX or PDF")
    if data.startswith(_RAR_SIGNATURES):
        raise UnsupportedFileError("Only ZIP archives are supported")

    ext_kind = _EXT_TO_KIND.get(_ext(filename))
    if ext_kind is None:
        raise UnsupportedFileError(f"Unsupported file extension: {_ext(filename) or '(none)'}")

    if ext_kind == "pdf":
        if not data[:1024].lstrip().startswith(b"%PDF-"):
            raise UnsupportedFileError("File extension says PDF but content is not a PDF")
    elif ext_kind in ("docx", "zip"):
        if not data.startswith(b"PK\x03\x04"):
            raise UnsupportedFileError(
                f"File extension says {ext_kind.upper()} but content is not a ZIP container"
            )
        if ext_kind == "docx" and b"word/" not in data[:65536] and b"[Content_Types].xml" not in data[:65536]:
            raise UnsupportedFileError("ZIP container does not look like a Word document")
    elif ext_kind in ("txt", "html"):
        if data.startswith((b"%PDF-", b"PK\x03\x04")) or not _looks_textual(data):
            raise UnsupportedFileError("File extension says text but content is binary")
    return DetectedType(kind=ext_kind, media_type=MEDIA_TYPES[ext_kind])
