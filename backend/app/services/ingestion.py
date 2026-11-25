"""Asset ingestion, ZIP expansion, swipe extraction, exact deduplication, and versioning (FR-03..05)."""

import re
import uuid
from pathlib import PurePosixPath

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.extraction.archives import UnsafeArchiveError, iter_zip_entries
from app.adapters.extraction.documents import ExtractionError, extract_document
from app.adapters.extraction.parser import ParsedSwipe, parse_swipes
from app.models import (
    Asset,
    AssetSource,
    Job,
    JobEvent,
    Offer,
    SubjectVariant,
    Swipe,
    SwipeProvenance,
    SwipeTag,
    SwipeVersion,
    Tag,
    utcnow,
)
from app.security.filetypes import UnsupportedFileError, detect_file_type
from app.services.storage import compute_sha256, read_asset_bytes, write_asset_bytes
from app.settings import get_settings


def _clean_filename(name: str) -> str:
    base = PurePosixPath(name.replace("\\", "/")).name.strip()
    return base[:480] or "unnamed"


def _lineage_key_for_filename(filename: str) -> str:
    return f"file:{_clean_filename(filename).lower()}"


def default_progress() -> dict[str, int]:
    return {
        "pages_checked": 0,
        "assets_found": 0,
        "assets_processed": 0,
        "swipes_extracted": 0,
        "swipes_new": 0,
        "versions_new": 0,
        "duplicates": 0,
        "warnings": 0,
    }


def log_job_event(db: Session, job: Job, level: str, event_type: str, message: str) -> None:
    db.add(JobEvent(job_id=job.id, level=level, event_type=event_type, message=message))
    if level == "warning":
        prog = dict(default_progress() | (job.progress_json or {}))
        prog["warnings"] = prog.get("warnings", 0) + 1
        job.progress_json = prog


def build_search_document(
    offer: Offer,
    swipe_title: str | None,
    subjects: list[str],
    preheader: str | None,
    body_text: str,
    tag_labels: list[str],
) -> str:
    parts = [
        offer.title or "",
        offer.vendor_name or "",
        offer.niche or "",
        swipe_title or "",
        " ".join(subjects),
        preheader or "",
        body_text or "",
        " ".join(tag_labels),
    ]
    return "\n".join(p for p in parts if p).strip()


def refresh_swipe_search_document(db: Session, swipe: Swipe) -> None:
    offer = swipe.offer or db.get(Offer, swipe.offer_id)
    version = db.get(SwipeVersion, swipe.current_version_id) if swipe.current_version_id else None
    subjects = [sv.subject for sv in (version.subjects if version else [])]
    tag_rows = db.scalars(
        select(Tag.label).join(SwipeTag, SwipeTag.tag_id == Tag.id).where(SwipeTag.swipe_id == swipe.id)
    ).all()
    if offer is not None and version is not None:
        swipe.search_document = build_search_document(
            offer=offer,
            swipe_title=swipe.title,
            subjects=subjects,
            preheader=version.preheader,
            body_text=version.body_text,
            tag_labels=list(tag_rows),
        )


def store_or_reuse_asset(
    db: Session,
    *,
    offer_id: uuid.UUID,
    filename: str,
    data: bytes,
    origin: str,
    lineage_key: str,
    source_id: uuid.UUID | None = None,
    parent_asset_source_id: uuid.UUID | None = None,
    retrieval_url: str | None = None,
    notes: str | None = None,
) -> tuple[Asset, AssetSource, bool]:
    """Persist bytes by SHA-256 and create or reuse an :class:`AssetSource` for the offer.

    Returns ``(asset, asset_source, was_duplicate_for_offer)``.
    """
    detected = detect_file_type(filename, data)
    sha256 = compute_sha256(data)
    storage_key = write_asset_bytes(sha256, data)

    asset = db.scalar(select(Asset).where(Asset.sha256 == sha256))
    if asset is None:
        asset = Asset(
            sha256=sha256,
            storage_key=storage_key,
            filename=_clean_filename(filename),
            media_type=detected.media_type,
            size_bytes=len(data),
            extraction_state="pending",
        )
        db.add(asset)
        db.flush()

    existing_source = db.scalar(
        select(AssetSource).where(
            AssetSource.offer_id == offer_id,
            AssetSource.asset_id == asset.id,
            AssetSource.lineage_key == lineage_key,
        )
    )
    if existing_source is not None:
        return asset, existing_source, True

    prior_count = (
        db.scalar(
            select(func.count())
            .select_from(AssetSource)
            .where(AssetSource.offer_id == offer_id, AssetSource.lineage_key == lineage_key)
        )
        or 0
    )
    asset_source = AssetSource(
        asset_id=asset.id,
        offer_id=offer_id,
        source_id=source_id,
        parent_asset_source_id=parent_asset_source_id,
        origin=origin,
        original_filename=_clean_filename(filename),
        lineage_key=lineage_key,
        retrieval_url=retrieval_url,
        version_label=f"v{prior_count + 1}",
        notes=notes,
    )
    db.add(asset_source)
    db.flush()
    return asset, asset_source, False


def _ensure_provenance(
    db: Session,
    *,
    swipe_version_id: uuid.UUID,
    asset_source_id: uuid.UUID,
    page_number: int | None,
    section_label: str | None,
) -> None:
    sec = (section_label or "")[:300]
    existing = db.scalar(
        select(SwipeProvenance).where(
            SwipeProvenance.swipe_version_id == swipe_version_id,
            SwipeProvenance.asset_source_id == asset_source_id,
            SwipeProvenance.section_label == sec,
        )
    )
    if existing is None:
        db.add(
            SwipeProvenance(
                swipe_version_id=swipe_version_id,
                asset_source_id=asset_source_id,
                page_number=page_number,
                section_label=sec,
            )
        )
        db.flush()


def _create_swipe_version(
    db: Session,
    *,
    swipe: Swipe,
    version_number: int,
    parsed: ParsedSwipe,
) -> SwipeVersion:
    version = SwipeVersion(
        swipe_id=swipe.id,
        version_number=version_number,
        body_text=parsed.body_text,
        body_html_sanitized=parsed.body_html_sanitized,
        preheader=parsed.preheader,
        ctas_json=[c.to_dict() for c in parsed.ctas],
        flags_json=list(parsed.flags),
        normalized_hash=parsed.normalized_hash,
        parser_version=parsed.parser_version,
        confidence=parsed.confidence,
        section_label=parsed.section_label,
    )
    db.add(version)
    db.flush()
    for pos, subj in enumerate(parsed.subjects, start=1):
        db.add(SubjectVariant(swipe_version_id=version.id, subject=subj, position=pos))
    db.flush()
    db.refresh(version)
    return version


def _persist_parsed_swipe(
    db: Session,
    *,
    offer: Offer,
    asset_source: AssetSource,
    parsed: ParsedSwipe,
    progress: dict[str, int],
) -> None:
    # 1. Exact duplicate anywhere within the same offer? (FR-05 #2 & #5, AC-04)
    exact_version = db.scalar(
        select(SwipeVersion)
        .join(Swipe, Swipe.id == SwipeVersion.swipe_id)
        .where(
            Swipe.offer_id == offer.id,
            SwipeVersion.normalized_hash == parsed.normalized_hash,
        )
        .order_by(SwipeVersion.version_number.desc())
    )
    if exact_version is not None:
        _ensure_provenance(
            db,
            swipe_version_id=exact_version.id,
            asset_source_id=asset_source.id,
            page_number=parsed.page_number,
            section_label=parsed.section_label,
        )
        swipe = db.get(Swipe, exact_version.swipe_id)
        if swipe is not None and swipe.current_version_id != exact_version.id:
            # If the document reverted to an earlier known version, point current_version_id at it.
            pass
        progress["duplicates"] += 1
        return

    # 2. Existing swipe in the same offer + asset lineage + block identity -> new version (FR-05 #6, AC-05)
    lineage_swipe = db.scalar(
        select(Swipe).where(
            Swipe.offer_id == offer.id,
            Swipe.lineage_key == asset_source.lineage_key,
            Swipe.identity_key == parsed.identity_key,
        )
    )
    if lineage_swipe is not None:
        max_ver = (
            db.scalar(
                select(func.max(SwipeVersion.version_number)).where(
                    SwipeVersion.swipe_id == lineage_swipe.id
                )
            )
            or 0
        )
        new_version = _create_swipe_version(
            db,
            swipe=lineage_swipe,
            version_number=max_ver + 1,
            parsed=parsed,
        )
        _ensure_provenance(
            db,
            swipe_version_id=new_version.id,
            asset_source_id=asset_source.id,
            page_number=parsed.page_number,
            section_label=parsed.section_label,
        )
        lineage_swipe.current_version_id = new_version.id
        # New version requires review while prior review events stay attached to prior version.
        lineage_swipe.review_state = "pending"
        lineage_swipe.updated_at = utcnow()
        refresh_swipe_search_document(db, lineage_swipe)
        progress["versions_new"] += 1
        return

    # 3. Brand new swipe for this offer
    swipe = Swipe(
        offer_id=offer.id,
        title=parsed.title,
        review_state="pending",
        lineage_key=asset_source.lineage_key,
        identity_key=parsed.identity_key,
    )
    db.add(swipe)
    db.flush()

    version = _create_swipe_version(db, swipe=swipe, version_number=1, parsed=parsed)
    swipe.current_version_id = version.id
    _ensure_provenance(
        db,
        swipe_version_id=version.id,
        asset_source_id=asset_source.id,
        page_number=parsed.page_number,
        section_label=parsed.section_label,
    )
    refresh_swipe_search_document(db, swipe)
    progress["swipes_new"] += 1


def _is_cancel_requested(db: Session, job: Job) -> bool:
    db.refresh(job, attribute_names=["state"])
    return job.state == "cancel_requested"


def _ingest_single_document(
    db: Session,
    *,
    job: Job,
    offer: Offer,
    asset: Asset,
    asset_source: AssetSource,
    kind: str,
    data: bytes,
    progress: dict[str, int],
) -> None:
    asset.extraction_state = "processing"
    db.flush()

    try:
        doc = extract_document(kind, data)
    except ExtractionError as exc:
        asset.extraction_state = "failed"
        asset.extraction_error = str(exc)
        log_job_event(
            db,
            job,
            "error",
            "extraction_failed",
            f"{asset_source.original_filename}: {exc}",
        )
        return

    asset.extractor = doc.engine
    asset.extractor_version = doc.engine_version
    for warning in doc.warnings:
        log_job_event(
            db,
            job,
            "warning",
            "document_warning",
            f"{asset_source.original_filename}: {warning}",
        )

    parsed_list = parse_swipes(doc.lines)
    if not parsed_list:
        asset.extraction_state = "needs_review"
        asset.extraction_error = "No candidate email swipes could be extracted from document"
        log_job_event(
            db,
            job,
            "warning",
            "no_swipes_found",
            f"{asset_source.original_filename}: no candidate swipes found; placed in review",
        )
        return

    needs_review = False
    for parsed in parsed_list:
        progress["swipes_extracted"] += 1
        if parsed.confidence < 0.75 or "missing_subject" in parsed.flags or "missing_body" in parsed.flags:
            needs_review = True
        _persist_parsed_swipe(
            db,
            offer=offer,
            asset_source=asset_source,
            parsed=parsed,
            progress=progress,
        )

    asset.extraction_state = "needs_review" if needs_review else "extracted"
    asset.extraction_error = None


def execute_ingest_job(db: Session, job_id: uuid.UUID) -> Job:
    """Run an ``ingest_asset`` job synchronously against ``db`` (called by worker or inline mode)."""
    settings = get_settings()
    job = db.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    if job.state == "cancel_requested":
        job.state = "cancelled"
        job.finished_at = utcnow()
        log_job_event(db, job, "info", "job_cancelled", "Job cancelled before start")
        db.commit()
        return job

    job.state = "running"
    job.attempts = (job.attempts or 0) + 1
    job.started_at = utcnow()
    job.heartbeat_at = utcnow()
    progress = dict(default_progress() | (job.progress_json or {}))
    job.progress_json = progress
    db.commit()

    asset_source = db.get(AssetSource, job.asset_source_id) if job.asset_source_id else None
    offer = db.get(Offer, job.offer_id) if job.offer_id else None
    if asset_source is None or offer is None:
        job.state = "failed"
        job.error_summary = "Target offer or asset source no longer exists"
        job.finished_at = utcnow()
        log_job_event(db, job, "error", "job_failed", job.error_summary)
        db.commit()
        return job

    root_asset = asset_source.asset
    try:
        data = read_asset_bytes(root_asset.storage_key)
        detected = detect_file_type(asset_source.original_filename, data)
    except (FileNotFoundError, UnsupportedFileError, ValueError) as exc:
        root_asset.extraction_state = "failed"
        root_asset.extraction_error = str(exc)
        job.state = "failed"
        job.error_summary = str(exc)
        job.finished_at = utcnow()
        log_job_event(db, job, "error", "asset_invalid", str(exc))
        db.commit()
        return job

    log_job_event(
        db,
        job,
        "info",
        "job_started",
        f"Ingesting {asset_source.original_filename} ({detected.kind}, {len(data)} bytes)",
    )

    had_errors = False
    if detected.kind != "zip":
        progress["assets_found"] = 1
        _ingest_single_document(
            db,
            job=job,
            offer=offer,
            asset=root_asset,
            asset_source=asset_source,
            kind=detected.kind,
            data=data,
            progress=progress,
        )
        progress["assets_processed"] = 1
        if root_asset.extraction_state == "failed":
            had_errors = True
        job.progress_json = dict(progress)
        db.commit()
    else:
        root_asset.extraction_state = "processing"
        root_asset.extractor = "zipfile"
        root_asset.extractor_version = "1.0.0"
        db.commit()

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
            root_asset.extraction_state = "failed"
            root_asset.extraction_error = str(exc)
            job.state = "failed"
            job.error_summary = f"Rejected unsafe archive: {exc}"
            job.finished_at = utcnow()
            log_job_event(db, job, "error", "unsafe_archive", str(exc))
            db.commit()
            return job

        progress["assets_found"] = len(entries)
        job.progress_json = dict(progress)
        db.commit()

        for entry in entries:
            if _is_cancel_requested(db, job):
                root_asset.extraction_state = "extracted" if progress["assets_processed"] else "pending"
                job.state = "cancelled"
                job.finished_at = utcnow()
                job.progress_json = dict(progress)
                log_job_event(
                    db,
                    job,
                    "info",
                    "job_cancelled",
                    f"Cancelled after processing {progress['assets_processed']} of {len(entries)} archive entries",
                )
                db.commit()
                return job

            if entry.skipped_reason or entry.data is None:
                log_job_event(
                    db,
                    job,
                    "warning",
                    "entry_skipped",
                    f"{entry.name}: {entry.skipped_reason}",
                )
                continue

            try:
                child_type = detect_file_type(entry.name, entry.data)
            except UnsupportedFileError as exc:
                log_job_event(
                    db,
                    job,
                    "warning",
                    "entry_unsupported",
                    f"{entry.name}: {exc}",
                )
                continue

            if child_type.kind == "zip":
                log_job_event(
                    db,
                    job,
                    "warning",
                    "nested_archive_skipped",
                    f"{entry.name}: nested archives are not supported in the MVP",
                )
                continue

            entry_lineage = f"{asset_source.lineage_key}::{re.sub(r'\\+', '/', entry.name).lower()}"
            child_asset, child_source, _dup = store_or_reuse_asset(
                db,
                offer_id=offer.id,
                filename=entry.name,
                data=entry.data,
                origin="archive_entry",
                lineage_key=entry_lineage,
                source_id=asset_source.source_id,
                parent_asset_source_id=asset_source.id,
            )
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
            if child_asset.extraction_state == "failed":
                had_errors = True
            progress["assets_processed"] += 1
            job.heartbeat_at = utcnow()
            job.progress_json = dict(progress)
            db.commit()

        root_asset.extraction_state = "extracted" if progress["assets_processed"] > 0 else "needs_review"
        if progress["assets_processed"] == 0:
            root_asset.extraction_error = "Archive contained no supported documents"

    if _is_cancel_requested(db, job):
        job.state = "cancelled"
        log_job_event(db, job, "info", "job_cancelled", "Cancelled before completion")
    elif had_errors and progress["swipes_extracted"] == 0:
        job.state = "failed"
        job.error_summary = root_asset.extraction_error or "Asset extraction failed"
    elif had_errors or progress.get("warnings", 0) > 0:
        job.state = "partial" if had_errors else "completed"
    else:
        job.state = "completed"

    job.progress_json = dict(progress)
    job.finished_at = utcnow()
    log_job_event(
        db,
        job,
        "info",
        "job_finished",
        f"Finished with state={job.state}: {progress['swipes_new']} new swipes, "
        f"{progress['versions_new']} new versions, {progress['duplicates']} duplicates",
    )
    db.commit()
    return job


def enqueue_or_run_ingest_job(db: Session, job: Job) -> Job:
    """Run inline when ``INGEST_INLINE=true`` or fall back cleanly if Redis is unreachable."""
    settings = get_settings()
    if settings.ingest_inline:
        return execute_ingest_job(db, job.id)
    try:
        from redis import Redis
        from rq import Queue

        conn = Redis.from_url(settings.redis_url)
        queue = Queue(settings.rq_queue_name, connection=conn)
        queue.enqueue("app.workers.tasks.run_ingest_job", str(job.id), job_timeout=600)
        return job
    except Exception as exc:  # noqa: BLE001 - if queue is down, log and run inline so upload still succeeds
        log_job_event(
            db,
            job,
            "warning",
            "queue_fallback_inline",
            f"Queue unavailable ({exc.__class__.__name__}); executing inline",
        )
        db.commit()
        return execute_ingest_job(db, job.id)


def enqueue_or_run_scan_job(db: Session, job: Job) -> Job:
    """Enqueue a ``scan_source`` job to RQ or execute inline when ``INGEST_INLINE=true``."""
    from app.adapters.sources.crawler import execute_scan_source_job

    settings = get_settings()
    if settings.ingest_inline:
        return execute_scan_source_job(db, job.id)
    try:
        from redis import Redis
        from rq import Queue

        conn = Redis.from_url(settings.redis_url)
        queue = Queue(settings.rq_queue_name, connection=conn)
        queue.enqueue("app.workers.tasks.run_scan_job", str(job.id), job_timeout=900)
        return job
    except Exception as exc:  # noqa: BLE001
        log_job_event(
            db,
            job,
            "warning",
            "queue_fallback_inline",
            f"Queue unavailable ({exc.__class__.__name__}); executing scan inline",
        )
        db.commit()
        return execute_scan_source_job(db, job.id)
