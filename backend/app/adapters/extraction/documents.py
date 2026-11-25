"""Convert supported document bytes into ordered text lines with page numbers.

Documents are parsed strictly as data: no macros, scripts or embedded commands are executed.
Hyperlinks are preserved inline as ``anchor text <https://url>`` so CTA destinations survive.
"""

import io
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

EXTRACTOR_VERSION = "1.0.0"


class ExtractionError(ValueError):
    pass


@dataclass
class Line:
    text: str
    page: int | None = None


@dataclass
class ExtractedDocument:
    lines: list[Line]
    engine: str
    engine_version: str = EXTRACTOR_VERSION
    warnings: list[str] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        return any(line.text.strip() for line in self.lines)


def _split(text: str, page: int | None = None) -> list[Line]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    return [Line(t.rstrip(), page) for t in text.split("\n")]


def decode_text(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    for enc in ("utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def extract_txt(data: bytes) -> ExtractedDocument:
    return ExtractedDocument(lines=_split(decode_text(data)), engine="text")


_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol",
    "blockquote", "section", "article", "header", "footer", "hr", "pre", "center",
}  # fmt: skip
_DROP_TAGS = ("script", "style", "noscript", "head", "template", "iframe", "object", "embed", "svg", "form")


def _html_to_text(node: Tag) -> str:
    parts: list[str] = []

    def walk(el: Tag | NavigableString) -> None:
        if isinstance(el, NavigableString):
            if el.find_parent("pre") is not None:
                parts.append(str(el))
            else:
                parts.append(re.sub(r"\s+", " ", str(el)))
            return
        name = el.name.lower() if el.name else ""
        if name in _DROP_TAGS:
            return
        if name == "br":
            parts.append("\n")
            return
        if name == "hr":
            parts.append("\n---\n")
            return
        if name in _BLOCK_TAGS:
            parts.append("\n")
        if name == "li":
            parts.append("- ")
        if name == "a":
            text = re.sub(r"\s+", " ", el.get_text(" ")).strip()
            href = (el.get("href") or "").strip()
            if href.lower().startswith(("http://", "https://")) and href != text:
                parts.append(f"{text} <{href}>" if text else f"<{href}>")
            else:
                parts.append(text)
            return
        for child in el.children:
            walk(child)
        if name in _BLOCK_TAGS:
            parts.append("\n")

    walk(node)
    text = "".join(parts)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_html(data: bytes) -> ExtractedDocument:
    soup = BeautifulSoup(decode_text(data), "html.parser")
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()
    root = soup.body or soup
    return ExtractedDocument(lines=_split(_html_to_text(root)), engine="beautifulsoup4-html")


def extract_pdf(data: bytes) -> ExtractedDocument:
    import pymupdf  # PyMuPDF; imported lazily to keep API start fast

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - malformed PDFs raise many types
        raise ExtractionError(f"PDF could not be opened: {exc.__class__.__name__}") from exc
    lines: list[Line] = []
    warnings: list[str] = []
    try:
        if doc.needs_pass:
            raise ExtractionError("PDF is password protected")
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            for link in page.get_links():
                uri = link.get("uri")
                if not uri or not str(uri).lower().startswith(("http://", "https://")) or uri in text:
                    continue
                anchor = (page.get_textbox(link["from"]) or "").strip()
                if anchor and anchor in text:
                    text = text.replace(anchor, f"{anchor} <{uri}>", 1)
                else:
                    text += f"\n<{uri}>"
            lines.extend(_split(text, page=index))
            lines.append(Line("", index))
        if not any(line.text.strip() for line in lines):
            warnings.append("PDF has no embedded text (scanned PDF?); OCR is not supported in the MVP")
    finally:
        doc.close()
    return ExtractedDocument(lines=lines, engine=f"pymupdf-{pymupdf.VersionBind}", warnings=warnings)


def _docx_paragraph_text(paragraph) -> str:  # type: ignore[no-untyped-def]
    from docx.text.hyperlink import Hyperlink

    out: list[str] = []
    try:
        items = list(paragraph.iter_inner_content())
    except AttributeError:
        return paragraph.text
    for item in items:
        if isinstance(item, Hyperlink):
            address = (item.address or "").strip()
            text = item.text
            if address.lower().startswith(("http://", "https://")) and address != text:
                out.append(f"{text} <{address}>")
            else:
                out.append(text)
        else:
            out.append(item.text)
    return "".join(out)


def extract_docx(data: bytes) -> ExtractedDocument:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"DOCX could not be opened: {exc.__class__.__name__}") from exc
    lines: list[Line] = []

    def handle_block(block) -> None:  # type: ignore[no-untyped-def]
        if isinstance(block, Paragraph):
            lines.extend(_split(_docx_paragraph_text(block)))
            if block.style is not None and (block.style.name or "").lower().startswith("heading"):
                lines.append(Line(""))
        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        lines.extend(_split(_docx_paragraph_text(p)))
                lines.append(Line(""))

    try:
        blocks = list(document.iter_inner_content())
    except AttributeError:
        blocks = list(document.paragraphs)
    for block in blocks:
        handle_block(block)
    return ExtractedDocument(lines=lines, engine="python-docx")


EXTRACTORS = {"txt": extract_txt, "html": extract_html, "pdf": extract_pdf, "docx": extract_docx}


def extract_document(kind: str, data: bytes) -> ExtractedDocument:
    try:
        extractor = EXTRACTORS[kind]
    except KeyError as exc:
        raise ExtractionError(f"No extractor for kind {kind}") from exc
    return extractor(data)
