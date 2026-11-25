"""Deterministic email swipe parser, deduplication hashing, CTA extraction, and review flags (FR-04/FR-05).

Never fabricates missing subjects or body copy. Low-confidence or incomplete blocks receive flags
and reduced confidence so they remain in the review queue (AC-09).
"""

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass, field

from app.adapters.extraction.documents import Line
from app.security.html import sanitize_html

PARSER_VERSION = "1.0.0"

_HEADING_RE = re.compile(
    r"^\s*(?:#{1,4}\s*)?(?:[-=*]{2,}\s*)?"
    r"(?P<label>(?:email|swipe|message|day|broadcast|follow[\s-]*up|promo)\s*#?\s*\d+[^\n]*?)"
    r"(?:\s*[-=*]{2,})?\s*$",
    re.IGNORECASE,
)
_DIVIDER_RE = re.compile(r"^\s*(?:[-=_*~]{5,})\s*$")
_SUBJECT_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:subject(?:\s*line)?(?:\s*(?:option|variant|alt|#)?\s*\d+)?|sl(?:\s*#?\s*\d+)?)"
    r"\s*[:\-–—]\s*(?P<val>.*)$",
    re.IGNORECASE,
)
_SUBJECT_HEADER_ONLY_RE = re.compile(
    r"^\s*(?:subject\s*lines?|subjects?|subject\s*line\s*options?|sl\s*options?)\s*:\s*$",
    re.IGNORECASE,
)
_ALT_SUBJECT_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:alt(?:ernate)?(?:\s*subject)?|option|variant)\s*#?\s*\d*\s*[:\-–—]\s*(?P<val>.+)$",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(?P<val>.+)$")
_PREHEADER_RE = re.compile(
    r"^\s*(?:pre[\s-]*header|preview(?:\s*text)?)\s*[:\-–—]\s*(?P<val>.*)$",
    re.IGNORECASE,
)
_BODY_HEADER_RE = re.compile(
    r"^\s*(?:email\s*)?(?:body|copy|message|content)\s*[:\-–—]\s*(?P<val>.*)$",
    re.IGNORECASE,
)

# Inline link pattern emitted by document extractors: "Anchor <https://...>" or raw URLs / placeholders
_ANGLE_LINK_RE = re.compile(r"(?P<text>[^\n<>]{0,120}?)\s*<(?P<url>https?://[^\s<>]+)>")
_RAW_URL_RE = re.compile(r"(?<![<\"'])(?P<url>https?://[^\s<>)\"']+)")
_PLACEHOLDER_RE = re.compile(
    r"(?:\[\s*(?:link|url|cta|aff(?:iliate)?[\s_-]*link|hop[\s_-]*link"
    r"|your[\s_-]*(?:aff(?:iliate)?[\s_-]*)?link"
    r"|insert[\s_-]*link[^\]]*|click[\s_-]*here[^\]]*)\s*\]"
    r"|\{\{\s*[\w.\-]*link[\w.\-]*\s*\}\}"
    r"|\{\s*(?:aff(?:iliate)?_?link|hoplink|url|cta_?link)\s*\}"
    r"|YOUR[_\s-]AFFILIATE[_\s-]LINK|AFFILIATE[_\s-]LINK[_\s-]HERE|HOPLINK[_\s-]HERE)",
    re.IGNORECASE,
)

# Editorial/compliance review hint patterns (PRD §8 — flags are hints, never legal determinations)
_HEALTH_CLAIM_RE = re.compile(
    r"\b(?:cure[sd]?|miracle|clinically\s+proven|doctor[\s-]*approved|fda[\s-]*approved"
    r"|reverse[sd]?\s+(?:diabetes|cancer|alzheimer|heart\s+disease|aging)"
    r"|melt[s]?\s+(?:away\s+)?\d+\s*(?:lbs?|pounds)|lose\s+\d+\s*(?:lbs?|pounds)\s+in\s+\d+\s+days)\b",
    re.IGNORECASE,
)
_GUARANTEE_CLAIM_RE = re.compile(
    r"\b(?:100%\s+guaranteed|guaranteed\s+results|can'?t\s+fail|no[\s-]*risk\s+guarantee"
    r"|works\s+every\s+time|instant\s+results)\b",
    re.IGNORECASE,
)
_INCOME_CLAIM_RE = re.compile(
    r"(?:\$\s?\d[\d,]*\s*(?:per|a|/)\s*(?:day|week|month|hour)|make\s+money\s+overnight)",
    re.IGNORECASE,
)
_TESTIMONIAL_RE = re.compile(
    r"(?:lost\s+\d+\s*(?:lbs?|pounds)|changed\s+my\s+life|my\s+doctor\s+was\s+shocked)",
    re.IGNORECASE,
)


@dataclass
class CTAItem:
    text: str
    url: str | None = None
    placeholder: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"text": self.text, "url": self.url, "placeholder": self.placeholder}


@dataclass
class ParsedSwipe:
    title: str | None
    section_label: str | None
    identity_key: str
    subjects: list[str]
    preheader: str | None
    body_text: str
    body_html_sanitized: str | None
    ctas: list[CTAItem]
    flags: list[str]
    confidence: float
    normalized_hash: str
    page_number: int | None = None
    parser_version: str = PARSER_VERSION


def normalize_text(value: str) -> str:
    norm = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", norm).strip().lower()


def compute_normalized_hash(subjects: list[str], body_text: str) -> str:
    norm_subjects = sorted({normalize_text(s) for s in subjects if normalize_text(s)})
    norm_body = normalize_text(body_text)
    payload = "||".join(norm_subjects) + "\n===\n" + norm_body
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text_to_sanitized_html(body_text: str) -> str | None:
    if not body_text.strip():
        return None
    paragraphs = re.split(r"\n\s*\n", body_text.strip())
    html_parts: list[str] = []
    for para in paragraphs:
        escaped = html.escape(para.strip())
        # Turn "Text &lt;https://url&gt;" into anchors before sanitizing
        escaped = re.sub(
            r"([^&\n<>]{1,120}?)\s*&lt;(https?://[^\s&<>]+)&gt;",
            lambda m: f'<a href="{m.group(2)}">{m.group(1).strip() or m.group(2)}</a>',
            escaped,
        )
        escaped = re.sub(
            r"&lt;(https?://[^\s&<>]+)&gt;",
            lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>',
            escaped,
        )
        escaped = escaped.replace("\n", "<br>")
        html_parts.append(f"<p>{escaped}</p>")
    return sanitize_html("\n".join(html_parts))


def extract_ctas(body_text: str) -> list[CTAItem]:
    ctas: list[CTAItem] = []
    seen: set[tuple[str, str | None, str | None]] = set()

    for match in _ANGLE_LINK_RE.finditer(body_text):
        url = match.group("url").strip().rstrip(".,;)")
        text = match.group("text").strip(" -–—:•*\t") or url
        key = (text, url, None)
        if key not in seen:
            seen.add(key)
            ctas.append(CTAItem(text=text, url=url, placeholder=None))

    stripped = _ANGLE_LINK_RE.sub("", body_text)
    for match in _RAW_URL_RE.finditer(stripped):
        url = match.group("url").strip().rstrip(".,;)")
        key = (url, url, None)
        if key not in seen:
            seen.add(key)
            ctas.append(CTAItem(text=url, url=url, placeholder=None))

    for line in body_text.splitlines():
        for pmatch in _PLACEHOLDER_RE.finditer(line):
            token = pmatch.group(0).strip()
            label = line.strip()
            if len(label) > 140:
                label = token
            key = (label, None, token)
            if key not in seen:
                seen.add(key)
                ctas.append(CTAItem(text=label, url=None, placeholder=token))

    return ctas


def compute_flags_and_confidence(
    *,
    subjects: list[str],
    body_text: str,
    ctas: list[CTAItem],
    had_boundary: bool,
) -> tuple[list[str], float]:
    flags: list[str] = []
    confidence = 0.92 if had_boundary else 0.72

    if not subjects:
        flags.append("missing_subject")
        confidence -= 0.35
    if not body_text.strip():
        flags.append("missing_body")
        confidence -= 0.50
    elif len(body_text.strip()) < 60:
        flags.append("short_body")
        confidence -= 0.25
    if not had_boundary:
        flags.append("no_boundary_marker")
    if not ctas:
        flags.append("missing_cta")
        confidence -= 0.08
    if any(c.placeholder for c in ctas):
        flags.append("placeholder_link")

    combined = " ".join(subjects) + "\n" + body_text
    if _HEALTH_CLAIM_RE.search(combined):
        flags.append("health_claim")
    if _GUARANTEE_CLAIM_RE.search(combined):
        flags.append("guarantee_claim")
    if _INCOME_CLAIM_RE.search(combined):
        flags.append("income_claim")
    if _TESTIMONIAL_RE.search(combined):
        flags.append("testimonial")

    confidence = round(max(0.05, min(0.99, confidence)), 2)
    return flags, confidence


@dataclass
class _RawBlock:
    heading: str | None = None
    lines: list[Line] = field(default_factory=list)
    had_boundary: bool = False


def _split_into_blocks(lines: list[Line]) -> list[_RawBlock]:
    blocks: list[_RawBlock] = []
    current = _RawBlock()
    seen_subject_in_current = False
    seen_body_in_current = False

    for line in lines:
        raw = line.text
        stripped = raw.strip()

        hmatch = _HEADING_RE.match(stripped)
        if hmatch:
            if current.lines or current.heading:
                blocks.append(current)
            clean_heading = re.sub(r"\s+", " ", hmatch.group("label")).strip(" :-–—")
            current = _RawBlock(heading=clean_heading, had_boundary=True)
            seen_subject_in_current = False
            seen_body_in_current = False
            continue

        if _DIVIDER_RE.match(stripped):
            if seen_subject_in_current and seen_body_in_current:
                blocks.append(current)
                current = _RawBlock(had_boundary=True)
                seen_subject_in_current = False
                seen_body_in_current = False
            continue

        if _SUBJECT_RE.match(stripped) or _SUBJECT_HEADER_ONLY_RE.match(stripped):
            if seen_subject_in_current and seen_body_in_current:
                blocks.append(current)
                current = _RawBlock(had_boundary=True)
                seen_body_in_current = False
            seen_subject_in_current = True
            current.had_boundary = True
        elif (
            seen_subject_in_current
            and stripped
            and not _PREHEADER_RE.match(stripped)
            and not _ALT_SUBJECT_RE.match(stripped)
        ):
            seen_body_in_current = True

        current.lines.append(line)

    if current.lines or current.heading:
        blocks.append(current)

    # Filter out trivial preface blocks before the first real heading/subject block
    non_empty = [b for b in blocks if any(ln.text.strip() for ln in b.lines)]
    if len(non_empty) > 1:
        first = non_empty[0]
        first_text = "\n".join(ln.text for ln in first.lines).strip()
        has_subj = any(_SUBJECT_RE.match(ln.text) or _SUBJECT_HEADER_ONLY_RE.match(ln.text) for ln in first.lines)
        if not first.heading and not has_subj and len(first_text) < 160:
            non_empty = non_empty[1:]
    return non_empty


def _parse_block(block: _RawBlock, index: int) -> ParsedSwipe | None:
    subjects: list[str] = []
    preheader: str | None = None
    body_lines: list[str] = []
    first_page: int | None = None

    in_subject_list = False
    in_body = False

    for line in block.lines:
        if first_page is None and line.page is not None:
            first_page = line.page
        text = line.text
        stripped = text.strip()

        if not in_body:
            if _SUBJECT_HEADER_ONLY_RE.match(stripped):
                in_subject_list = True
                block.had_boundary = True
                continue

            smatch = _SUBJECT_RE.match(stripped)
            if smatch:
                val = smatch.group("val").strip()
                if val:
                    subjects.append(val)
                    in_subject_list = False
                else:
                    in_subject_list = True
                block.had_boundary = True
                continue

            amatch = _ALT_SUBJECT_RE.match(stripped)
            if amatch and (subjects or in_subject_list):
                subjects.append(amatch.group("val").strip())
                continue

            pmatch = _PREHEADER_RE.match(stripped)
            if pmatch:
                preheader = pmatch.group("val").strip() or None
                in_subject_list = False
                continue

            bmatch = _BODY_HEADER_RE.match(stripped)
            if bmatch:
                in_body = True
                in_subject_list = False
                rest = bmatch.group("val").strip()
                if rest:
                    body_lines.append(rest)
                continue

            if in_subject_list:
                if not stripped:
                    if subjects:
                        in_subject_list = False
                    continue
                bitem = _BULLET_RE.match(stripped)
                if bitem and len(stripped) <= 180:
                    subjects.append(bitem.group("val").strip())
                    continue
                if len(stripped) <= 140 and not stripped.endswith((".", "!", "?")) and len(subjects) < 5:
                    subjects.append(stripped)
                    continue
                in_subject_list = False

            if not stripped and not body_lines:
                continue

            in_body = True

        body_lines.append(text)

    # Deduplicate subjects while preserving order
    unique_subjects: list[str] = []
    seen_subj: set[str] = set()
    for s in subjects:
        cleaned = s.strip().strip('"“”')
        key = normalize_text(cleaned)
        if cleaned and key not in seen_subj:
            seen_subj.add(key)
            unique_subjects.append(cleaned)

    body_text = "\n".join(body_lines).strip()
    body_text = re.sub(r"\n{3,}", "\n\n", body_text)

    if not unique_subjects and not body_text:
        return None

    ctas = extract_ctas(body_text)
    flags, confidence = compute_flags_and_confidence(
        subjects=unique_subjects,
        body_text=body_text,
        ctas=ctas,
        had_boundary=block.had_boundary,
    )
    section_label = block.heading or f"Swipe {index}"
    identity_key = normalize_text(block.heading) if block.heading else f"swipe-{index}"
    title = block.heading or (unique_subjects[0][:120] if unique_subjects else f"Untitled Swipe {index}")

    return ParsedSwipe(
        title=title,
        section_label=section_label,
        identity_key=identity_key,
        subjects=unique_subjects,
        preheader=preheader,
        body_text=body_text,
        body_html_sanitized=_text_to_sanitized_html(body_text),
        ctas=ctas,
        flags=flags,
        confidence=confidence,
        normalized_hash=compute_normalized_hash(unique_subjects, body_text),
        page_number=first_page,
    )


def parse_swipes(lines: list[Line]) -> list[ParsedSwipe]:
    """Deterministically parse candidate email swipes from extracted document lines."""
    if not any(ln.text.strip() for ln in lines):
        return []
    blocks = _split_into_blocks(lines)
    parsed: list[ParsedSwipe] = []
    for idx, block in enumerate(blocks, start=1):
        item = _parse_block(block, idx)
        if item is not None:
            parsed.append(item)
    return parsed
