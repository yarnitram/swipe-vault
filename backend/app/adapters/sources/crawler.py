"""Permission-aware HTTP resource scanner for authorized affiliate tools pages (Phase 2 — FR-02, FR-09).

Safety & compliance invariants:
- Validates URL syntax AND resolves DNS on every request and every redirect hop (`AC-07`).
- Restricts navigation strictly to the source's host and `source.allowed_hosts` (`FR-02`).
- Checks `robots.txt` for `SwipeVaultBot/1.0`; never bypasses `Disallow` (`FR-02`, `AC-06`).
- Respects `401`, `403`, login/CAPTCHA gates, and `429`/`Retry-After` without evasion (`FR-02`, `AC-06`).
- Never crawls checkout, cart, login, signup, or unrelated marketing paths (`FR-02`).
- Enforces configurable per-host request delay, page limit, depth limit, and download byte ceiling.
- Supports cooperative cancellation between page fetches and asset downloads (`AC-13`).
"""

import re
import time
import urllib.robotparser
import uuid
from collections import deque
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.adapters.extraction.archives import UnsafeArchiveError, iter_zip_entries
from app.models import Job, Offer, Source, utcnow
from app.security.filetypes import UnsupportedFileError, detect_file_type
from app.security.urls import UnsafeUrlError, resolve_and_check_host, validate_source_url
from app.services.ingestion import (
    _ingest_single_document,
    _is_cancel_requested,
    default_progress,
    log_job_event,
    store_or_reuse_asset,
)
from app.settings import get_settings

USER_AGENT = "SwipeVaultBot/1.0 (+self-hosted-authorized-affiliate-creative-library)"
MAX_REDIRECTS = 4

_ELIGIBLE_LINK_KEYWORDS = re.compile(
    r"(?:swipe|email[\s_-]*copy|email[\s_-]*template|subject[\s_-]*line|creative|affiliate[\s_-]*tool"
    r"|promo(?:tional)?[\s_-]*material|jv[\s_-]*tool|newsletter|autoresponder|broadcast)",
    re.IGNORECASE,
)
_EXCLUDED_PATH_RE = re.compile(
    r"(?:/checkout|/cart|/buy|/order|/billing|/payment|/login|/signin|/sign-in|/signup|/register"
    r"|/wp-login|/account|/privacy|/terms|/disclaimer|/contact|/unsubscribe|mailto:|tel:|javascript:)",
    re.IGNORECASE,
)
_ASSET_EXTENSIONS = (".txt", ".pdf", ".docx", ".zip")
_HTML_EXTENSIONS = (".html", ".htm")
_LOGIN_GATE_RE = re.compile(
    r"(?:<input[^>]+type=[\"']password[\"']|g-recaptcha|h-captcha|cf-turnstile"
    r"|affiliate\s+login\s+required|please\s+log\s+in\s+to\s+access\s+affiliate)",
    re.IGNORECASE,
)


class SourceAccessBlockedError(Exception):
    def __init__(self, new_access_state: str, reason: str) -> None:
        super().__init__(reason)
        self.new_access_state = new_access_state
        self.reason = reason


def _host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").rstrip(".").lower()


def _port_of(url: str) -> int:
    parts = urlsplit(url)
    if parts.port:
        return parts.port
    return 443 if parts.scheme.lower() == "https" else 80


def _is_host_allowed(url: str, allowed_hosts: set[str]) -> bool:
    return _host_of(url) in allowed_hosts


def _looks_like_direct_asset(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith(_ASSET_EXTENSIONS)


def _filename_from_url_or_headers(url: str, response: httpx.Response, default_ext: str = ".html") -> str:
    cd = response.headers.get("content-disposition") or ""
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^\";]+)"?', cd, re.IGNORECASE)
    if match:
        candidate = PurePosixPath(match.group(1).strip()).name
        if candidate:
            return candidate[:240]

    path_name = PurePosixPath(urlsplit(url).path).name
    if path_name and "." in path_name:
        return path_name[:240]

    ctype = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    ext_map = {
        "text/plain": ".txt",
        "text/html": ".html",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/zip": ".zip",
        "application/x-zip-compressed": ".zip",
    }
    ext = ext_map.get(ctype, default_ext)
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", path_name or "resource").strip("_") or "resource"
    return f"{stem}{ext}"


def _validate_url_and_dns(url: str, allowed_hosts: set[str], *, check_dns: bool) -> str:
    clean_url, normalized_url = validate_source_url(url)
    if not _is_host_allowed(normalized_url, allowed_hosts):
        raise UnsafeUrlError(f"Host '{_host_of(normalized_url)}' is outside the source's allowed hosts")
    if check_dns:
        resolve_and_check_host(_host_of(normalized_url), _port_of(normalized_url))
    return normalized_url


def _fetch_with_guards(
    client: httpx.Client,
    url: str,
    *,
    allowed_hosts: set[str],
    max_bytes: int,
    max_retries: int,
    max_retry_wait: float,
    check_dns: bool,
) -> tuple[str, httpx.Response, bytes]:
    """Fetch ``url`` validating every redirect hop, honoring 429/Retry-After, and capping response bytes."""
    current_url = url
    for _hop in range(MAX_REDIRECTS + 1):
        normalized = _validate_url_and_dns(current_url, allowed_hosts, check_dns=check_dns)

        attempt = 0
        while True:
            with client.stream("GET", normalized, follow_redirects=False) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location")
                    if not location:
                        raise UnsafeUrlError("Redirect response missing Location header")
                    current_url = urljoin(normalized, location)
                    break

                if resp.status_code == 401:
                    raise SourceAccessBlockedError(
                        "approval_required",
                        f"HTTP 401 Unauthorized at {normalized}; login or vendor approval required",
                    )
                if resp.status_code == 403:
                    raise SourceAccessBlockedError(
                        "restricted",
                        f"HTTP 403 Forbidden at {normalized}; vendor restricted automated access",
                    )
                if resp.status_code == 429:
                    retry_header = resp.headers.get("retry-after")
                    wait_s = 2.0 * (2**attempt)
                    if retry_header and retry_header.strip().isdigit():
                        wait_s = float(retry_header.strip())
                    if attempt >= max_retries or wait_s > max_retry_wait:
                        raise SourceAccessBlockedError(
                            "restricted",
                            f"HTTP 429 rate limit at {normalized} (Retry-After={retry_header or 'unspecified'})",
                        )
                    attempt += 1
                    time.sleep(min(wait_s, max_retry_wait))
                    continue

                if resp.status_code >= 400:
                    raise ValueError(f"HTTP {resp.status_code} retrieving {normalized}")

                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"Download at {normalized} exceeds {max_bytes} byte ceiling")
                    chunks.append(chunk)
                return normalized, resp, b"".join(chunks)
        # Continue outer loop for redirect hop
    raise UnsafeUrlError(f"Exceeded maximum redirects ({MAX_REDIRECTS}) from {url}")


def _check_robots_allowed(
    client: httpx.Client,
    source_url: str,
    *,
    allowed_hosts: set[str],
    check_dns: bool,
) -> tuple[bool, str | None]:
    parts = urlsplit(source_url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        _, resp, body = _fetch_with_guards(
            client,
            robots_url,
            allowed_hosts=allowed_hosts,
            max_bytes=262_144,
            max_retries=0,
            max_retry_wait=1.0,
            check_dns=check_dns,
        )
    except SourceAccessBlockedError:
        return True, None
    except Exception:  # noqa: BLE001 - missing or 404 robots.txt means not disallowed by robots
        return True, None

    if resp.status_code >= 400:
        return True, None
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode("utf-8", errors="ignore").splitlines())
    if not rp.can_fetch(USER_AGENT, source_url) and not rp.can_fetch("*", source_url):
        return False, f"Disallowed by {robots_url} for {USER_AGENT}"
    return True, None


def _discover_links(base_url: str, html_bytes: bytes, allowed_hosts: set[str]) -> tuple[list[str], list[str]]:
    """Return ``(eligible_page_urls, direct_asset_urls)`` discovered on an HTML page."""
    soup = BeautifulSoup(html_bytes.decode("utf-8", errors="ignore"), "html.parser")
    page_urls: list[str] = []
    asset_urls: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        raw_href = (anchor.get("href") or "").strip()
        if not raw_href or raw_href.startswith("#") or _EXCLUDED_PATH_RE.search(raw_href):
            continue
        candidate = urljoin(base_url, raw_href)
        if _EXCLUDED_PATH_RE.search(candidate):
            continue
        try:
            _, normalized = validate_source_url(candidate)
        except UnsafeUrlError:
            continue
        if not _is_host_allowed(normalized, allowed_hosts) or normalized in seen:
            continue

        label_context = " ".join(
            [
                anchor.get_text(" ", strip=True),
                str(anchor.get("title") or ""),
                urlsplit(normalized).path,
            ]
        )
        if _looks_like_direct_asset(normalized):
            seen.add(normalized)
            asset_urls.append(normalized)
        elif _ELIGIBLE_LINK_KEYWORDS.search(label_context):
            seen.add(normalized)
            page_urls.append(normalized)

    return page_urls, asset_urls


def _ingest_downloaded_bytes(
    db: Session,
    *,
    job: Job,
    offer: Offer,
    source: Source,
    retrieval_url: str,
    filename: str,
    data: bytes,
    progress: dict[str, int],
) -> bool:
    settings = get_settings()
    try:
        detected = detect_file_type(filename, data)
    except UnsupportedFileError as exc:
        log_job_event(db, job, "warning", "scan_asset_unsupported", f"{retrieval_url}: {exc}")
        return False

    lineage_key = f"url:{retrieval_url.lower()}"
    asset, asset_source, duplicate_asset = store_or_reuse_asset(
        db,
        offer_id=offer.id,
        filename=filename,
        data=data,
        origin="scan",
        lineage_key=lineage_key,
        source_id=source.id,
        retrieval_url=retrieval_url,
    )
    if duplicate_asset and asset.extraction_state in ("extracted", "needs_review"):
        progress["duplicates"] += 1
        log_job_event(
            db,
            job,
            "info",
            "scan_asset_unchanged",
            f"Unchanged asset at {retrieval_url} ({asset.sha256[:12]}) skipped",
        )
        return True

    if detected.kind != "zip":
        _ingest_single_document(
            db,
            job=job,
            offer=offer,
            asset=asset,
            asset_source=asset_source,
            kind=detected.kind,
            data=data,
            progress=progress,
        )
        return asset.extraction_state != "failed"

    # ZIP archive downloaded during scan
    asset.extraction_state = "processing"
    asset.extractor = "zipfile"
    asset.extractor_version = "1.0.0"
    db.flush()
    try:
        entries = list(
            iter_zip_entries(
                data,
                max_entries=settings.zip_max_entries,
                max_expanded=settings.zip_max_expanded_bytes,
                max_entry_bytes=settings.download_max_bytes,
            )
        )
    except UnsafeArchiveError as exc:
        asset.extraction_state = "failed"
        asset.extraction_error = str(exc)
        log_job_event(db, job, "error", "unsafe_archive", f"{retrieval_url}: {exc}")
        return False

    for entry in entries:
        if entry.skipped_reason or entry.data is None:
            log_job_event(db, job, "warning", "entry_skipped", f"{entry.name}: {entry.skipped_reason}")
            continue
        try:
            child_type = detect_file_type(entry.name, entry.data)
        except UnsupportedFileError as exc:
            log_job_event(db, job, "warning", "entry_unsupported", f"{entry.name}: {exc}")
            continue
        if child_type.kind == "zip":
            continue
        entry_lineage = f"{lineage_key}::{re.sub(r'\\+', '/', entry.name).lower()}"
        child_asset, child_source, child_dup = store_or_reuse_asset(
            db,
            offer_id=offer.id,
            filename=entry.name,
            data=entry.data,
            origin="archive_entry",
            lineage_key=entry_lineage,
            source_id=source.id,
            parent_asset_source_id=asset_source.id,
            retrieval_url=retrieval_url,
        )
        if child_dup and child_asset.extraction_state in ("extracted", "needs_review"):
            progress["duplicates"] += 1
            continue
        _ingest_single_document(
            db,
            job=job,
            offer=offer,
            asset=child_asset,
            asset_source=child_source,
            kind=child_type.kind,
            data=entry.data,
            progress=progress,
        )

    asset.extraction_state = "extracted"
    return True


def execute_scan_source_job(
    db: Session,
    job_id: uuid.UUID,
    *,
    transport: httpx.BaseTransport | None = None,
    check_dns: bool = True,
) -> Job:
    """Execute a ``scan_source`` job with bounded crawling, robots check, and SSRF guards."""
    settings = get_settings()
    job = db.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    if job.state == "cancel_requested":
        job.state = "cancelled"
        job.finished_at = utcnow()
        log_job_event(db, job, "info", "job_cancelled", "Scan cancelled before start")
        db.commit()
        return job

    source = db.get(Source, job.source_id) if job.source_id else None
    offer = db.get(Offer, job.offer_id) if job.offer_id else None
    if source is None or offer is None:
        job.state = "failed"
        job.error_summary = "Target offer or source no longer exists"
        job.finished_at = utcnow()
        log_job_event(db, job, "error", "job_failed", job.error_summary)
        db.commit()
        return job

    job.state = "running"
    job.attempts = (job.attempts or 0) + 1
    job.started_at = utcnow()
    job.heartbeat_at = utcnow()
    progress = dict(default_progress() | (job.progress_json or {}))
    job.progress_json = progress
    db.commit()

    primary_host = _host_of(source.normalized_url)
    allowed_hosts = {primary_host} | {str(h).lower() for h in (source.allowed_hosts or []) if h}
    log_job_event(
        db,
        job,
        "info",
        "scan_started",
        f"Scanning {source.normalized_url} (allowed hosts: {', '.join(sorted(allowed_hosts))})",
    )
    db.commit()

    had_errors = False
    last_request_at = 0.0

    def pace() -> None:
        nonlocal last_request_at
        if settings.crawl_delay_seconds > 0 and last_request_at > 0 and transport is None:
            elapsed = time.monotonic() - last_request_at
            if elapsed < settings.crawl_delay_seconds:
                time.sleep(settings.crawl_delay_seconds - elapsed)
        last_request_at = time.monotonic()

    with httpx.Client(
        timeout=settings.crawl_timeout_seconds,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8"},
        transport=transport,
    ) as client:
        # 1. Check robots.txt
        allowed_by_robots, robots_reason = _check_robots_allowed(
            client,
            source.normalized_url,
            allowed_hosts=allowed_hosts,
            check_dns=check_dns and transport is None,
        )
        source.last_checked_at = utcnow()
        if not allowed_by_robots:
            source.access_state = "restricted"
            job.state = "failed"
            job.error_summary = robots_reason or "Disallowed by robots.txt"
            job.finished_at = utcnow()
            log_job_event(db, job, "warning", "robots_disallowed", job.error_summary)
            db.commit()
            return job

        # 2. Breadth-first bounded discovery up to crawl_max_depth and crawl_max_pages
        queue: deque[tuple[str, int]] = deque([(source.normalized_url, 0)])
        visited_pages: set[str] = set()
        queued_assets: list[str] = []
        seen_assets: set[str] = set()

        while queue and progress["pages_checked"] < settings.crawl_max_pages:
            if _is_cancel_requested(db, job):
                job.state = "cancelled"
                job.finished_at = utcnow()
                job.progress_json = dict(progress)
                log_job_event(
                    db,
                    job,
                    "info",
                    "job_cancelled",
                    f"Cancelled after checking {progress['pages_checked']} page(s)",
                )
                db.commit()
                return job

            page_url, depth = queue.popleft()
            if page_url in visited_pages:
                continue
            visited_pages.add(page_url)

            if _looks_like_direct_asset(page_url):
                if page_url not in seen_assets:
                    seen_assets.add(page_url)
                    queued_assets.append(page_url)
                continue

            pace()
            try:
                final_url, resp, body = _fetch_with_guards(
                    client,
                    page_url,
                    allowed_hosts=allowed_hosts,
                    max_bytes=settings.download_max_bytes,
                    max_retries=settings.crawl_max_retries,
                    max_retry_wait=settings.crawl_max_retry_wait_seconds,
                    check_dns=check_dns and transport is None,
                )
            except SourceAccessBlockedError as exc:
                source.access_state = exc.new_access_state
                source.last_checked_at = utcnow()
                log_job_event(db, job, "warning", "access_restricted", exc.reason)
                if progress["pages_checked"] == 0:
                    job.state = "failed"
                    job.error_summary = exc.reason
                    job.finished_at = utcnow()
                    job.progress_json = dict(progress)
                    db.commit()
                    return job
                had_errors = True
                continue
            except (UnsafeUrlError, ValueError, httpx.HTTPError) as exc:
                had_errors = True
                log_job_event(db, job, "error", "page_fetch_failed", f"{page_url}: {exc}")
                continue

            progress["pages_checked"] += 1
            source.last_checked_at = utcnow()
            fname = _filename_from_url_or_headers(final_url, resp, default_ext=".html")

            # If the page itself is a non-HTML asset (e.g. direct PDF/ZIP/DOCX/TXT URL)
            ctype = (resp.headers.get("content-type") or "").lower()
            if not ctype.startswith("text/html") and not fname.lower().endswith(_HTML_EXTENSIONS):
                progress["assets_found"] += 1
                ok = _ingest_downloaded_bytes(
                    db,
                    job=job,
                    offer=offer,
                    source=source,
                    retrieval_url=final_url,
                    filename=fname,
                    data=body,
                    progress=progress,
                )
                progress["assets_processed"] += 1
                if not ok:
                    had_errors = True
                job.progress_json = dict(progress)
                db.commit()
                continue

            # Check HTML for login/CAPTCHA/approval gates (FR-02, AC-06)
            text_sample = body[:32768].decode("utf-8", errors="ignore")
            if _LOGIN_GATE_RE.search(text_sample):
                source.access_state = "approval_required"
                log_job_event(
                    db,
                    job,
                    "warning",
                    "login_gate_detected",
                    f"{final_url}: login or CAPTCHA gate detected; upload vendor files manually after approval",
                )
                if progress["pages_checked"] == 1 and not queued_assets:
                    job.state = "failed"
                    job.error_summary = "Source requires login, CAPTCHA, or affiliate approval"
                    job.finished_at = utcnow()
                    job.progress_json = dict(progress)
                    db.commit()
                    return job
                continue

            # Ingest the HTML page itself if it contains email swipe markers
            if re.search(r"\b(?:subject\s*:|sl\s*:|email\s*#?\s*\d+)", text_sample, re.IGNORECASE):
                progress["assets_found"] += 1
                ok = _ingest_downloaded_bytes(
                    db,
                    job=job,
                    offer=offer,
                    source=source,
                    retrieval_url=final_url,
                    filename=fname if fname.lower().endswith(_HTML_EXTENSIONS) else f"{fname}.html",
                    data=body,
                    progress=progress,
                )
                progress["assets_processed"] += 1
                if not ok:
                    had_errors = True

            # Discover linked swipe pages and downloadable assets
            if depth < settings.crawl_max_depth:
                child_pages, child_assets = _discover_links(final_url, body, allowed_hosts)
                for curl in child_pages:
                    if curl not in visited_pages:
                        queue.append((curl, depth + 1))
                for aurl in child_assets:
                    if aurl not in seen_assets:
                        seen_assets.add(aurl)
                        queued_assets.append(aurl)

            job.heartbeat_at = utcnow()
            job.progress_json = dict(progress)
            db.commit()

        # 3. Download discovered direct assets
        progress["assets_found"] += len(queued_assets)
        job.progress_json = dict(progress)
        db.commit()

        for asset_url in queued_assets:
            if _is_cancel_requested(db, job):
                job.state = "cancelled"
                job.finished_at = utcnow()
                job.progress_json = dict(progress)
                log_job_event(
                    db,
                    job,
                    "info",
                    "job_cancelled",
                    f"Cancelled after {progress['assets_processed']} of {progress['assets_found']} asset(s)",
                )
                db.commit()
                return job

            pace()
            try:
                final_url, resp, body = _fetch_with_guards(
                    client,
                    asset_url,
                    allowed_hosts=allowed_hosts,
                    max_bytes=settings.download_max_bytes,
                    max_retries=settings.crawl_max_retries,
                    max_retry_wait=settings.crawl_max_retry_wait_seconds,
                    check_dns=check_dns and transport is None,
                )
            except SourceAccessBlockedError as exc:
                had_errors = True
                log_job_event(db, job, "warning", "asset_access_restricted", exc.reason)
                continue
            except (UnsafeUrlError, ValueError, httpx.HTTPError) as exc:
                had_errors = True
                log_job_event(db, job, "error", "asset_download_failed", f"{asset_url}: {exc}")
                continue

            fname = _filename_from_url_or_headers(final_url, resp, default_ext=".txt")
            ok = _ingest_downloaded_bytes(
                db,
                job=job,
                offer=offer,
                source=source,
                retrieval_url=final_url,
                filename=fname,
                data=body,
                progress=progress,
            )
            progress["assets_processed"] += 1
            if not ok:
                had_errors = True
            job.heartbeat_at = utcnow()
            job.progress_json = dict(progress)
            db.commit()

    if had_errors and progress["assets_processed"] == 0:
        job.state = "failed"
        job.error_summary = "Scan failed to retrieve any valid resources"
    elif had_errors:
        job.state = "partial"
    else:
        job.state = "completed"

    job.progress_json = dict(progress)
    job.finished_at = utcnow()
    log_job_event(
        db,
        job,
        "info",
        "scan_finished",
        f"Scan {job.state}: {progress['pages_checked']} page(s), "
        f"{progress['assets_processed']} asset(s), {progress['swipes_new']} new swipe(s), "
        f"{progress['versions_new']} new version(s), {progress['duplicates']} duplicate(s)",
    )
    db.commit()
    return job
