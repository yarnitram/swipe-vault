"""Unit and security tests: URL/SSRF defenses, file validation, ZIP safety, HTML sanitization, extraction."""

import io
import stat
import zipfile

import pytest

from app.adapters.extraction.archives import UnsafeArchiveError, iter_zip_entries
from app.adapters.extraction.documents import extract_document
from app.adapters.extraction.parser import compute_normalized_hash, parse_swipes
from app.security.filetypes import UnsupportedFileError, detect_file_type
from app.security.html import sanitize_html
from app.security.urls import UnsafeUrlError, normalize_host_list, validate_source_url
from tests.conftest import make_docx_bytes, make_pdf_bytes


@pytest.mark.parametrize(
    "bad_url",
    [
        "ftp://example.com/swipes.zip",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "http://user:pass@example.com/jv",
        "http://127.0.0.1/admin",
        "http://10.0.0.15/internal",
        "http://172.16.4.2/secret",
        "http://192.168.1.1/router",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/loopback",
        "http://localhost:8000/api",
        "http://printer.local/swipes",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://2130706433/decimal-loopback",
        "https://example.com:22/ssh",
    ],
)
def test_ssrf_url_validation_blocks_unsafe_targets(bad_url: str) -> None:
    """AC-07: Private IPs, loopback, metadata hosts, non-HTTP schemes, and userinfo URLs are blocked."""
    with pytest.raises(UnsafeUrlError):
        validate_source_url(bad_url)


def test_url_validation_normalizes_valid_urls() -> None:
    clean, normalized = validate_source_url("https://Affiliates.Example.com:443/jv/tools#section")
    assert clean == "https://Affiliates.Example.com:443/jv/tools#section"
    assert normalized == "https://affiliates.example.com/jv/tools"
    assert normalize_host_list(["CDN.Example.com.", "assets.example.com"]) == [
        "cdn.example.com",
        "assets.example.com",
    ]


def test_file_signature_validation_rejects_spoofed_and_executable_files() -> None:
    """FR-03 & AC-07: Validate file type using content signature as well as extension."""
    with pytest.raises(UnsupportedFileError):
        detect_file_type("swipes.pdf", b"MZ\x90\x00executable-pretending-to-be-pdf")
    with pytest.raises(UnsupportedFileError):
        detect_file_type("swipes.txt", b"%PDF-1.7 binary pdf with txt extension")
    with pytest.raises(UnsupportedFileError):
        detect_file_type("payload.exe", b"MZ\x90\x00")
    with pytest.raises(UnsupportedFileError):
        detect_file_type("legacy.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1macro-ole")


def test_zip_safety_rejects_traversal_symlinks_and_oversized_archives() -> None:
    """FR-03 & AC-07: Reject path traversal, symlinks, and zip bombs."""
    # Path traversal
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0")
    with pytest.raises(UnsafeArchiveError):
        list(iter_zip_entries(buf.getvalue(), max_entries=50, max_expanded=1_000_000, max_entry_bytes=500_000))

    # Symlink entry
    sym_buf = io.BytesIO()
    with zipfile.ZipFile(sym_buf, "w") as zf:
        info = zipfile.ZipInfo("link.txt")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/shadow")
    with pytest.raises(UnsafeArchiveError):
        list(
            iter_zip_entries(
                sym_buf.getvalue(), max_entries=50, max_expanded=1_000_000, max_entry_bytes=500_000
            )
        )

    # Expanded size ceiling
    big_buf = io.BytesIO()
    with zipfile.ZipFile(big_buf, "w") as zf:
        zf.writestr("a.txt", "A" * 2000)
        zf.writestr("b.txt", "B" * 2000)
    with pytest.raises(UnsafeArchiveError):
        list(iter_zip_entries(big_buf.getvalue(), max_entries=50, max_expanded=3000, max_entry_bytes=2500))


def test_html_sanitizer_strips_scripts_event_handlers_and_tracking_pixels() -> None:
    """PRD §8 & AC-07: Strip active scripts, event handlers, javascript: URLs, and remote images."""
    dirty = (
        '<div><script> evil() </script>'
        '<p onclick="steal()">Hello <a href="javascript:evil()">bad</a> '
        '<a href="https://vendor.example.com/offer" onmouseover="x()">good link</a></p>'
        '<img src="https://tracker.example.com/pixel.gif" onerror="evil()">'
        '<iframe src="https://evil.example.com"></iframe></div>'
    )
    cleaned = sanitize_html(dirty)
    assert "<script" not in cleaned.lower()
    assert "evil()" not in cleaned
    assert "onclick" not in cleaned.lower()
    assert "onmouseover" not in cleaned.lower()
    assert "javascript:" not in cleaned.lower()
    assert "<img" not in cleaned.lower()
    assert "<iframe" not in cleaned.lower()
    assert 'href="https://vendor.example.com/offer"' in cleaned
    assert "noopener" in cleaned


def test_extract_and_parse_across_txt_html_pdf_and_docx() -> None:
    """AC-03 & AC-09: Extract swipes from TXT, HTML, PDF, and DOCX without fabricating missing fields."""
    sample_copy = (
        "Email 1: Morning Ritual\n"
        "Subject: 15-second metabolic morning habit\n"
        "Subject Option 2: Try this before your morning coffee\n"
        "Preheader: Quick kitchen routine inside\n"
        "Body:\n"
        "Hi First Name,\n\n"
        "Discover why nutrition coaches recommend this simple morning ritual before breakfast.\n\n"
        "Watch the metabolic briefing <https://vendor.example.com/video>\n"
        "Or use your hop link: [YOUR_AFFILIATE_LINK]\n"
    )
    html_copy = sample_copy.replace(
        "Watch the metabolic briefing <https://vendor.example.com/video>",
        '<a href="https://vendor.example.com/video">Watch the metabolic briefing</a>',
    )
    for kind, raw in (
        ("txt", sample_copy.encode("utf-8")),
        ("html", f"<html><body><pre>{html_copy}</pre></body></html>".encode()),
        ("pdf", make_pdf_bytes([sample_copy])),
        ("docx", make_docx_bytes(sample_copy.splitlines())),
    ):
        doc = extract_document(kind, raw)
        swipes = parse_swipes(doc.lines)
        assert len(swipes) == 1, f"Expected 1 swipe for {kind}"
        sw = swipes[0]
        assert len(sw.subjects) == 2
        assert sw.subjects[0] == "15-second metabolic morning habit"
        assert sw.preheader == "Quick kitchen routine inside"
        assert "morning ritual before breakfast" in sw.body_text
        assert any(c.url == "https://vendor.example.com/video" for c in sw.ctas)
        assert any(c.placeholder == "[YOUR_AFFILIATE_LINK]" for c in sw.ctas)
        assert sw.confidence >= 0.8

    # AC-09: Low-confidence block with no subject label stays flagged and never invents a subject
    ambiguous_doc = extract_document(
        "txt",
        b"Just a loose paragraph with no subject line marker and a miracle cure claim.",
    )
    ambiguous_swipes = parse_swipes(ambiguous_doc.lines)
    assert len(ambiguous_swipes) == 1
    amb = ambiguous_swipes[0]
    assert amb.subjects == []
    assert "missing_subject" in amb.flags
    assert "health_claim" in amb.flags
    assert amb.confidence < 0.5


def test_normalized_hash_is_whitespace_and_case_insensitive() -> None:
    h1 = compute_normalized_hash(["Subject A", "Subject B"], "Hello   World!\n\nParagraph two.")
    h2 = compute_normalized_hash(["subject b", "SUBJECT A"], "hello world! paragraph two.")
    assert h1 == h2
