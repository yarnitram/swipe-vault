"""Brand profile and campaign draft preparation, targeted CTA replacement, and review checks (FR-07)."""

import html
import re
from typing import Any
from urllib.parse import urlsplit

from app.adapters.extraction.parser import (
    _GUARANTEE_CLAIM_RE,
    _HEALTH_CLAIM_RE,
    _INCOME_CLAIM_RE,
    _PLACEHOLDER_RE,
    _TESTIMONIAL_RE,
    extract_ctas,
)
from app.models import BrandProfile, SwipeVersion
from app.security.html import sanitize_html
from app.security.urls import UnsafeUrlError, validate_source_url

_PROTECTED_URL_RE = re.compile(
    r"(?:unsubscribe|optout|opt-out|preferences|privacy|terms|disclaimer|legal|manage-subscription)",
    re.IGNORECASE,
)


def validate_affiliate_url(raw_url: str | None) -> tuple[str | None, bool, str | None]:
    """Validate an affiliate URL without fabricating network parameters."""
    if raw_url is None or not raw_url.strip():
        return None, False, None
    try:
        clean_url, _ = validate_source_url(raw_url.strip())
        return clean_url, True, None
    except UnsafeUrlError as exc:
        return raw_url.strip(), False, str(exc)


def apply_targeted_link_replacements(
    body_text: str,
    *,
    affiliate_url: str | None,
    replace_placeholders: bool = True,
    replace_urls: list[str] | None = None,
) -> str:
    """Replace ONLY recognized CTA placeholders and explicitly selected URLs (FR-07).

    Never globally replaces all URLs; unsubscribe, legal, disclosure, and unselected links stay untouched.
    """
    if not affiliate_url:
        return body_text
    updated = body_text
    if replace_placeholders:
        updated = _PLACEHOLDER_RE.sub(affiliate_url, updated)

    for target_url in replace_urls or []:
        t = (target_url or "").strip()
        if not t or _PROTECTED_URL_RE.search(t):
            continue
        updated = updated.replace(f"<{t}>", f"<{affiliate_url}>")
        updated = updated.replace(t, affiliate_url)
    return updated


def ensure_brand_disclosure_and_footer(
    body_text: str,
    brand: BrandProfile,
) -> str:
    """Append the brand's affiliate disclosure and sender footer if not already present (FR-07)."""
    out = body_text.rstrip()
    disclosure = (brand.disclosure_text or "").strip()
    footer = (brand.footer_template or "").strip()

    if disclosure and disclosure.lower() not in out.lower():
        out = f"{out}\n\n---\n{disclosure}"
    if footer and footer.lower() not in out.lower():
        out = f"{out}\n{footer}"
    return out.strip()


def render_draft_html(body_text: str) -> str:
    """Render plain text (with ``Anchor <https://url>`` or raw URLs) to sanitized HTML."""
    if not body_text.strip():
        return ""
    paragraphs = re.split(r"\n\s*\n", body_text.strip())
    blocks: list[str] = []
    for para in paragraphs:
        if para.strip() == "---":
            blocks.append("<hr>")
            continue
        escaped = html.escape(para.strip())
        escaped = re.sub(
            r"([^&\n<>]{1,120}?)\s*&lt;(https?://[^\s<>\"']+)&gt;",
            lambda m: f'<a href="{m.group(2)}">{m.group(1).strip() or m.group(2)}</a>',
            escaped,
        )
        escaped = re.sub(
            r"&lt;(https?://[^\s<>\"']+)&gt;",
            lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>',
            escaped,
        )
        escaped = re.sub(
            r"(?<!href=\")(?<!>)(https?://[^\s<>)\"']+)",
            lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>',
            escaped,
        )
        escaped = escaped.replace("\n", "<br>")
        blocks.append(f"<p>{escaped}</p>")
    return sanitize_html("\n".join(blocks))


def compute_draft_review_checks(
    *,
    subject: str,
    preheader: str | None,
    body_text: str,
    body_html: str,
    affiliate_url: str | None,
    brand: BrandProfile,
) -> dict[str, Any]:
    clean_aff, aff_valid, aff_error = validate_affiliate_url(affiliate_url)
    has_affiliate_url = bool(clean_aff and (clean_aff in body_text or clean_aff in body_html))

    disclosure = (brand.disclosure_text or "").strip()
    has_disclosure = bool(
        (disclosure and disclosure[:40].lower() in body_text.lower())
        or re.search(r"affiliate\s+disclosure|earn\s+a\s+commission|affiliate\s+link", body_text, re.IGNORECASE)
    )

    footer = (brand.footer_template or "").strip()
    has_sender_footer = bool(
        (footer and footer[:25].lower() in body_text.lower())
        or (brand.name.lower() in body_text.lower() and "unsubscribe" in body_text.lower())
    )

    unresolved_placeholders = sorted({m.group(0) for m in _PLACEHOLDER_RE.finditer(body_text + "\n" + body_html)})

    allowed_hosts = {
        h.strip().lower()
        for h in ((brand.affiliate_settings_json or {}).get("allowed_affiliate_hosts") or [])
        if isinstance(h, str) and h.strip()
    }
    if clean_aff and aff_valid:
        aff_host = (urlsplit(clean_aff).hostname or "").lower()
        if aff_host:
            allowed_hosts.add(aff_host)

    unexpected_hosts: list[str] = []
    for cta in extract_ctas(body_text):
        if cta.url:
            host = (urlsplit(cta.url).hostname or "").lower()
            if host and allowed_hosts and host not in allowed_hosts and host not in unexpected_hosts:
                unexpected_hosts.append(host)

    combined = f"{subject}\n{preheader or ''}\n{body_text}"
    claim_flags: list[str] = []
    if _HEALTH_CLAIM_RE.search(combined):
        claim_flags.append("health_claim")
    if _GUARANTEE_CLAIM_RE.search(combined):
        claim_flags.append("guarantee_claim")
    if _INCOME_CLAIM_RE.search(combined):
        claim_flags.append("income_claim")
    if _TESTIMONIAL_RE.search(combined):
        claim_flags.append("testimonial")

    warnings: list[str] = []
    if aff_error:
        warnings.append(f"Invalid affiliate URL: {aff_error}")
    if not has_affiliate_url:
        warnings.append("Approved affiliate URL is not present in draft body")
    if unresolved_placeholders:
        warnings.append(f"Unresolved link placeholder(s): {', '.join(unresolved_placeholders)}")
    if not has_disclosure:
        warnings.append("Missing affiliate disclosure in draft body")
    if not has_sender_footer:
        warnings.append("Missing sender identification / unsubscribe footer")
    if unexpected_hosts:
        warnings.append(f"Outbound link host(s) differ from brand affiliate hosts: {', '.join(unexpected_hosts)}")

    ready_for_approval = bool(
        subject.strip()
        and body_text.strip()
        and has_affiliate_url
        and aff_valid
        and has_disclosure
        and has_sender_footer
        and not unresolved_placeholders
    )

    return {
        "has_affiliate_url": has_affiliate_url,
        "affiliate_url_valid": aff_valid,
        "has_disclosure": has_disclosure,
        "has_sender_footer": has_sender_footer,
        "unresolved_placeholders": unresolved_placeholders,
        "unexpected_hosts": unexpected_hosts,
        "claim_flags": claim_flags,
        "warnings": warnings,
        "ready_for_approval": ready_for_approval,
    }


def build_initial_draft_content(
    *,
    version: SwipeVersion,
    brand: BrandProfile,
    subject_position: int | None,
    affiliate_url: str | None,
    replace_urls: list[str] | None,
) -> tuple[str, str, str, dict[str, Any]]:
    subjects = [sv.subject for sv in version.subjects]
    chosen_subject = subjects[0] if subjects else "Untitled Subject"
    if subject_position is not None:
        for sv in version.subjects:
            if sv.position == subject_position:
                chosen_subject = sv.subject
                break

    clean_aff, aff_valid, aff_err = validate_affiliate_url(affiliate_url)
    if affiliate_url and not aff_valid:
        raise ValueError(aff_err or "Invalid affiliate URL")

    body_text = apply_targeted_link_replacements(
        version.body_text,
        affiliate_url=clean_aff,
        replace_placeholders=True,
        replace_urls=replace_urls,
    )
    if clean_aff and clean_aff not in body_text:
        body_text = f"{body_text.rstrip()}\n\n<{clean_aff}>"

    body_text = ensure_brand_disclosure_and_footer(body_text, brand)
    body_html = render_draft_html(body_text)
    checks = compute_draft_review_checks(
        subject=chosen_subject,
        preheader=version.preheader,
        body_text=body_text,
        body_html=body_html,
        affiliate_url=clean_aff,
        brand=brand,
    )
    return chosen_subject, body_text, body_html, checks
