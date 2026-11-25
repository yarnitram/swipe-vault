"""FastAPI v1 routes implementing docs/api.md (Phases 0-3)."""

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import Select, desc, func, or_, select, text
from sqlalchemy.orm import Session

from app.adapters.extraction.parser import normalize_text
from app.adapters.listmonk.client import (
    export_unsent_draft_to_listmonk,
    test_listmonk_connection,
)
from app.auth import (
    authenticate_user,
    clear_user_session,
    create_user_session,
    require_user,
)
from app.db import get_db
from app.errors import ApiError
from app.models import (
    JOB_TERMINAL_STATES,
    Asset,
    AssetSource,
    AuditEvent,
    BrandProfile,
    Draft,
    Export,
    Job,
    JobEvent,
    Network,
    Offer,
    OfferApproval,
    ReviewEvent,
    Source,
    Swipe,
    SwipeProvenance,
    SwipeTag,
    SwipeVersion,
    Tag,
    User,
    utcnow,
)
from app.schemas import (
    ApprovalCreate,
    BrandCreate,
    BrandUpdate,
    CsvCommitRequest,
    DraftApproveRequest,
    DraftCreate,
    DraftUpdate,
    ListmonkExportRequest,
    LoginRequest,
    OfferCreate,
    OfferUpdate,
    SourceCreate,
    SourceScanRequest,
    SourceUpdate,
    SwipeBulkRequest,
    SwipeReviewRequest,
    SwipeTagsRequest,
    SwipeUpdate,
)
from app.security.filetypes import UnsupportedFileError, detect_file_type
from app.security.html import sanitize_html
from app.security.urls import UnsafeUrlError, normalize_host_list, validate_source_url
from app.services.csv_import import commit_csv_rows, preview_csv_bytes
from app.services.drafts import (
    apply_targeted_link_replacements,
    build_initial_draft_content,
    compute_draft_review_checks,
    ensure_brand_disclosure_and_footer,
    render_draft_html,
    validate_affiliate_url,
)
from app.services.ingestion import (
    _lineage_key_for_filename,
    default_progress,
    enqueue_or_run_ingest_job,
    enqueue_or_run_scan_job,
    log_job_event,
    refresh_swipe_search_document,
    store_or_reuse_asset,
)
from app.services.storage import read_asset_bytes
from app.settings import get_settings

router = APIRouter(prefix="/api/v1")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse_uuid(value: str, label: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ApiError(404, "not_found", f"Invalid {label}") from exc


def _slugify_tag(raw: str) -> tuple[str, str]:
    label = re.sub(r"\s+", " ", raw.strip())[:200]
    slug = re.sub(r"[^a-z0-9:_-]+", "-", label.lower()).strip("-")[:100]
    return slug, label


# ---------- Health, Runtime Settings & Overview ----------


@router.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> JSONResponse:
    db_status = "ok"
    redis_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_status = "error"

    try:
        conn = Redis.from_url(get_settings().redis_url, socket_connect_timeout=1.5)
        conn.ping()
    except Exception:  # noqa: BLE001
        redis_status = "error"

    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
    code = 200 if overall == "ok" else 503
    return JSONResponse(
        status_code=code,
        content={"status": overall, "database": db_status, "redis": redis_status},
    )


@router.get("/settings/runtime")
def get_runtime_settings(_user: User = Depends(require_user)) -> dict[str, Any]:
    s = get_settings()
    return {
        "crawl_delay_seconds": s.crawl_delay_seconds,
        "crawl_max_pages": s.crawl_max_pages,
        "crawl_max_depth": s.crawl_max_depth,
        "crawl_timeout_seconds": s.crawl_timeout_seconds,
        "download_max_bytes": s.download_max_bytes,
        "near_duplicate_threshold": s.near_duplicate_threshold,
        "listmonk_enabled": s.listmonk_enabled,
        "listmonk_configured": s.listmonk_configured,
        "listmonk_base_url": s.listmonk_base_url if s.listmonk_base_url else None,
        "ai_provider": s.ai_provider,
    }


@router.get("/stats/overview")
def stats_overview(
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    offers_total = db.scalar(select(func.count()).select_from(Offer)) or 0
    swipes_total = db.scalar(select(func.count()).select_from(Swipe)) or 0
    pending_reviews = (
        db.scalar(select(func.count()).select_from(Swipe).where(Swipe.review_state == "pending")) or 0
    )
    needs_changes = (
        db.scalar(select(func.count()).select_from(Swipe).where(Swipe.review_state == "needs_changes")) or 0
    )
    approved = (
        db.scalar(select(func.count()).select_from(Swipe).where(Swipe.review_state == "approved")) or 0
    )
    assets_total = db.scalar(select(func.count()).select_from(Asset)) or 0
    drafts_total = db.scalar(select(func.count()).select_from(Draft)) or 0
    failed_jobs = (
        db.scalar(select(func.count()).select_from(Job).where(Job.state.in_(("failed", "partial")))) or 0
    )
    active_jobs = (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.state.in_(("queued", "running", "cancel_requested")))
        )
        or 0
    )
    last_ingested_at = db.scalar(select(func.max(AssetSource.retrieved_at)))
    return {
        "offers_total": offers_total,
        "swipes_total": swipes_total,
        "pending_reviews": pending_reviews,
        "needs_changes": needs_changes,
        "approved": approved,
        "assets_total": assets_total,
        "drafts_total": drafts_total,
        "failed_jobs": failed_jobs,
        "active_jobs": active_jobs,
        "last_ingested_at": _iso(last_ingested_at),
    }


# ---------- Auth ----------


@router.post("/auth/login")
def auth_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    client_host = (request.client.host if request.client else None) or "local"
    user = authenticate_user(db, str(payload.email), payload.password, client_host)
    create_user_session(db, user, response)
    return {"user": {"id": str(user.id), "email": user.email, "role": user.role}}


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def auth_logout(
    request: Request,
    response: Response,
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    clear_user_session(db, request, response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/auth/me")
def auth_me(user: User = Depends(require_user)) -> dict[str, Any]:
    return {"id": str(user.id), "email": user.email, "role": user.role}


# ---------- Networks ----------


@router.get("/networks")
def list_networks(
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = db.scalars(select(Network).order_by(Network.enabled.desc(), Network.name.asc())).all()
    return [{"id": str(n.id), "slug": n.slug, "name": n.name, "enabled": n.enabled} for n in rows]


# ---------- Offers ----------


def _serialize_offer(db: Session, offer: Offer) -> dict[str, Any]:
    swipe_count = (
        db.scalar(select(func.count()).select_from(Swipe).where(Swipe.offer_id == offer.id)) or 0
    )
    asset_count = (
        db.scalar(select(func.count()).select_from(AssetSource).where(AssetSource.offer_id == offer.id)) or 0
    )
    source_count = (
        db.scalar(select(func.count()).select_from(Source).where(Source.offer_id == offer.id)) or 0
    )
    net = offer.network
    return {
        "id": str(offer.id),
        "network": {"id": str(net.id), "slug": net.slug, "name": net.name},
        "external_offer_id": offer.external_offer_id,
        "title": offer.title,
        "niche": offer.niche,
        "vendor_name": offer.vendor_name,
        "offer_url": offer.offer_url,
        "affiliate_resources_url": offer.affiliate_resources_url,
        "approval_state": offer.approval_state,
        "metrics_json": offer.metrics_json,
        "metrics_source": offer.metrics_source,
        "metrics_as_of": _iso(offer.metrics_as_of),
        "notes": offer.notes,
        "last_verified_at": _iso(offer.last_verified_at),
        "created_at": _iso(offer.created_at),
        "updated_at": _iso(offer.updated_at),
        "swipe_count": swipe_count,
        "asset_count": asset_count,
        "source_count": source_count,
    }


@router.get("/offers/niches")
def list_offer_niches(
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[str]:
    rows = db.scalars(
        select(func.distinct(Offer.niche))
        .where(Offer.niche.is_not(None), Offer.niche != "")
        .order_by(Offer.niche.asc())
    ).all()
    return [r for r in rows if r]


@router.get("/offers")
def list_offers(
    q: str | None = None,
    network: str | None = None,
    niche: str | None = None,
    approval_state: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt: Select[tuple[Offer]] = select(Offer).join(Network, Network.id == Offer.network_id)
    if q and q.strip():
        pat = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Offer.title.ilike(pat),
                Offer.vendor_name.ilike(pat),
                Offer.external_offer_id.ilike(pat),
                Offer.niche.ilike(pat),
            )
        )
    if network:
        stmt = stmt.where(func.lower(Network.slug) == network.strip().lower())
    if niche:
        stmt = stmt.where(func.lower(Offer.niche) == niche.strip().lower())
    if approval_state:
        stmt = stmt.where(Offer.approval_state == approval_state.strip().lower())

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Offer.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [_serialize_offer(db, o) for o in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _clean_optional_url(raw: str | None, field_name: str) -> str | None:
    if raw is None or not raw.strip():
        return None
    try:
        clean, _ = validate_source_url(raw)
        return clean
    except UnsafeUrlError as exc:
        raise ApiError(422, "unsafe_url", f"{field_name}: {exc}") from exc


@router.post("/offers", status_code=status.HTTP_201_CREATED)
def create_offer(
    payload: OfferCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    net = db.scalar(select(Network).where(func.lower(Network.slug) == payload.network_slug.strip().lower()))
    if net is None:
        raise ApiError(422, "unknown_network", f"Unknown network '{payload.network_slug}'")

    ext_id = (payload.external_offer_id or "").strip() or None
    if ext_id is not None:
        dup = db.scalar(
            select(Offer).where(
                Offer.network_id == net.id,
                func.lower(Offer.external_offer_id) == ext_id.lower(),
            )
        )
        if dup is not None:
            raise ApiError(
                409,
                "duplicate_offer",
                f"Offer with external_offer_id '{ext_id}' already exists for {net.slug}",
                details={"existing_offer_id": str(dup.id)},
            )

    offer = Offer(
        network_id=net.id,
        external_offer_id=ext_id,
        title=payload.title.strip(),
        niche=(payload.niche or "").strip() or None,
        vendor_name=(payload.vendor_name or "").strip() or None,
        offer_url=_clean_optional_url(payload.offer_url, "offer_url"),
        affiliate_resources_url=_clean_optional_url(
            payload.affiliate_resources_url, "affiliate_resources_url"
        ),
        notes=(payload.notes or "").strip() or None,
    )
    db.add(offer)
    db.flush()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="offer.create",
            entity_type="offer",
            entity_id=str(offer.id),
            metadata_json={"title": offer.title, "network": net.slug},
        )
    )
    db.commit()
    db.refresh(offer)
    return _serialize_offer(db, offer)


@router.get("/offers/{offer_id}")
def get_offer(
    offer_id: str,
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    oid = _parse_uuid(offer_id, "offer_id")
    offer = db.get(Offer, oid)
    if offer is None:
        raise ApiError(404, "not_found", "Offer not found")
    return _serialize_offer(db, offer)


@router.patch("/offers/{offer_id}")
def update_offer(
    offer_id: str,
    payload: OfferUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    oid = _parse_uuid(offer_id, "offer_id")
    offer = db.get(Offer, oid)
    if offer is None:
        raise ApiError(404, "not_found", "Offer not found")

    fields = payload.model_dump(exclude_unset=True)
    if "network_slug" in fields and fields["network_slug"] is not None:
        net = db.scalar(
            select(Network).where(func.lower(Network.slug) == fields["network_slug"].strip().lower())
        )
        if net is None:
            raise ApiError(422, "unknown_network", f"Unknown network '{fields['network_slug']}'")
        offer.network_id = net.id

    if "external_offer_id" in fields:
        ext_id = (fields["external_offer_id"] or "").strip() or None
        if ext_id is not None:
            dup = db.scalar(
                select(Offer).where(
                    Offer.network_id == offer.network_id,
                    func.lower(Offer.external_offer_id) == ext_id.lower(),
                    Offer.id != offer.id,
                )
            )
            if dup is not None:
                raise ApiError(409, "duplicate_offer", f"External ID '{ext_id}' is already used")
        offer.external_offer_id = ext_id

    if "title" in fields and fields["title"] is not None:
        offer.title = fields["title"].strip()
    if "niche" in fields:
        offer.niche = (fields["niche"] or "").strip() or None
    if "vendor_name" in fields:
        offer.vendor_name = (fields["vendor_name"] or "").strip() or None
    if "offer_url" in fields:
        offer.offer_url = _clean_optional_url(fields["offer_url"], "offer_url")
    if "affiliate_resources_url" in fields:
        offer.affiliate_resources_url = _clean_optional_url(
            fields["affiliate_resources_url"], "affiliate_resources_url"
        )
    if "notes" in fields:
        offer.notes = (fields["notes"] or "").strip() or None
    if "metrics_json" in fields:
        offer.metrics_json = fields["metrics_json"]
    if "metrics_source" in fields:
        offer.metrics_source = (fields["metrics_source"] or "").strip() or None
    if "metrics_as_of" in fields:
        offer.metrics_as_of = fields["metrics_as_of"]
    if "last_verified_at" in fields:
        offer.last_verified_at = fields["last_verified_at"]

    offer.updated_at = utcnow()
    for swipe in db.scalars(select(Swipe).where(Swipe.offer_id == offer.id)).all():
        refresh_swipe_search_document(db, swipe)

    db.add(
        AuditEvent(
            user_id=user.id,
            action="offer.update",
            entity_type="offer",
            entity_id=str(offer.id),
            metadata_json={"updated_fields": sorted(fields.keys())},
        )
    )
    db.commit()
    db.refresh(offer)
    return _serialize_offer(db, offer)


@router.get("/offers/{offer_id}/approvals")
def list_offer_approvals(
    offer_id: str,
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    oid = _parse_uuid(offer_id, "offer_id")
    offer = db.get(Offer, oid)
    if offer is None:
        raise ApiError(404, "not_found", "Offer not found")
    rows = db.scalars(
        select(OfferApproval)
        .where(OfferApproval.offer_id == oid)
        .order_by(OfferApproval.created_at.desc())
    ).all()
    return [
        {
            "id": str(a.id),
            "state": a.state,
            "notes": a.notes,
            "user_email": a.user.email if a.user else None,
            "created_at": _iso(a.created_at),
        }
        for a in rows
    ]


@router.post("/offers/{offer_id}/approvals", status_code=status.HTTP_201_CREATED)
def create_offer_approval(
    offer_id: str,
    payload: ApprovalCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    oid = _parse_uuid(offer_id, "offer_id")
    offer = db.get(Offer, oid)
    if offer is None:
        raise ApiError(404, "not_found", "Offer not found")

    approval = OfferApproval(
        offer_id=offer.id,
        state=payload.state,
        notes=(payload.notes or "").strip() or None,
        user_id=user.id,
    )
    offer.approval_state = payload.state
    offer.updated_at = utcnow()
    db.add(approval)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="offer.approval",
            entity_type="offer",
            entity_id=str(offer.id),
            metadata_json={"state": payload.state},
        )
    )
    db.commit()
    db.refresh(approval)
    return {
        "id": str(approval.id),
        "state": approval.state,
        "notes": approval.notes,
        "user_email": user.email,
        "created_at": _iso(approval.created_at),
    }


@router.post("/offers/import/preview")
async def preview_offers_csv(
    file: UploadFile = File(...),
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    content = await file.read(5_000_000)
    if not content:
        raise ApiError(400, "empty_csv", "Uploaded CSV file is empty")
    return preview_csv_bytes(db, content)


@router.post("/offers/import/commit")
def commit_offers_csv(
    payload: CsvCommitRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = [{"row_number": r.row_number, "data": r.data} for r in payload.rows]
    return commit_csv_rows(db, rows, user)


# ---------- Sources & Phase 2 Permission-Aware Scanning ----------


def _serialize_source(src: Source) -> dict[str, Any]:
    return {
        "id": str(src.id),
        "offer_id": str(src.offer_id),
        "url": src.url,
        "normalized_url": src.normalized_url,
        "source_type": src.source_type,
        "access_state": src.access_state,
        "permission_notes": src.permission_notes,
        "allowed_hosts": list(src.allowed_hosts or []),
        "last_checked_at": _iso(src.last_checked_at),
        "created_at": _iso(src.created_at),
    }


@router.get("/offers/{offer_id}/sources")
def list_offer_sources(
    offer_id: str,
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    oid = _parse_uuid(offer_id, "offer_id")
    if db.get(Offer, oid) is None:
        raise ApiError(404, "not_found", "Offer not found")
    rows = db.scalars(
        select(Source).where(Source.offer_id == oid).order_by(Source.created_at.desc())
    ).all()
    return [_serialize_source(s) for s in rows]


@router.post("/offers/{offer_id}/sources", status_code=status.HTTP_201_CREATED)
def create_offer_source(
    offer_id: str,
    payload: SourceCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    oid = _parse_uuid(offer_id, "offer_id")
    if db.get(Offer, oid) is None:
        raise ApiError(404, "not_found", "Offer not found")
    try:
        clean_url, normalized_url = validate_source_url(payload.url)
        allowed_hosts = normalize_host_list(payload.allowed_hosts)
    except UnsafeUrlError as exc:
        raise ApiError(422, "unsafe_url", str(exc)) from exc

    existing = db.scalar(
        select(Source).where(Source.offer_id == oid, Source.normalized_url == normalized_url)
    )
    if existing is not None:
        raise ApiError(409, "duplicate_source", "This source URL is already registered for the offer")

    source = Source(
        offer_id=oid,
        url=clean_url,
        normalized_url=normalized_url,
        source_type=payload.source_type,
        access_state=payload.access_state,
        permission_notes=(payload.permission_notes or "").strip() or None,
        allowed_hosts=allowed_hosts,
    )
    db.add(source)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="source.create",
            entity_type="source",
            entity_id=str(source.id),
            metadata_json={"offer_id": str(oid), "url": normalized_url},
        )
    )
    db.commit()
    db.refresh(source)
    return _serialize_source(source)


@router.patch("/sources/{source_id}")
def update_source(
    source_id: str,
    payload: SourceUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sid = _parse_uuid(source_id, "source_id")
    source = db.get(Source, sid)
    if source is None:
        raise ApiError(404, "not_found", "Source not found")

    fields = payload.model_dump(exclude_unset=True)
    if "source_type" in fields and fields["source_type"] is not None:
        source.source_type = fields["source_type"]
    if "access_state" in fields and fields["access_state"] is not None:
        source.access_state = fields["access_state"]
    if "permission_notes" in fields:
        source.permission_notes = (fields["permission_notes"] or "").strip() or None
    if "allowed_hosts" in fields and fields["allowed_hosts"] is not None:
        try:
            source.allowed_hosts = normalize_host_list(fields["allowed_hosts"])
        except UnsafeUrlError as exc:
            raise ApiError(422, "unsafe_url", str(exc)) from exc

    db.add(
        AuditEvent(
            user_id=user.id,
            action="source.update",
            entity_type="source",
            entity_id=str(source.id),
            metadata_json={"updated_fields": sorted(fields.keys())},
        )
    )
    db.commit()
    db.refresh(source)
    return _serialize_source(source)


@router.post("/sources/{source_id}/scan", status_code=status.HTTP_202_ACCEPTED)
def start_source_scan(
    source_id: str,
    payload: SourceScanRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sid = _parse_uuid(source_id, "source_id")
    source = db.get(Source, sid)
    if source is None:
        raise ApiError(404, "not_found", "Source not found")

    if not payload.confirm_authorized:
        raise ApiError(
            400,
            "authorization_required",
            "Explicit confirmation of authorization to retrieve and use vendor resources is required",
        )

    if source.access_state in ("restricted", "approval_required", "forbidden"):
        raise ApiError(
            409,
            "source_not_scannable",
            f"Source is marked '{source.access_state}' and cannot be scanned automatically; "
            "upload vendor-supplied files manually after approval",
        )

    # Per-offer and per-source job locking to avoid overlapping scans (FR-09)
    active = db.scalar(
        select(Job).where(
            Job.type == "scan_source",
            Job.state.in_(("queued", "running", "cancel_requested")),
            or_(Job.source_id == source.id, Job.offer_id == source.offer_id),
        )
    )
    if active is not None:
        raise ApiError(
            409,
            "scan_already_running",
            "A resource scan is already queued or running for this offer or source",
            details={"active_job_id": str(active.id)},
        )

    if source.access_state == "unverified":
        source.access_state = "authorized"

    job = Job(
        offer_id=source.offer_id,
        source_id=source.id,
        type="scan_source",
        state="queued",
        progress_json=default_progress(),
        created_by=user.id,
    )
    db.add(job)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="source.scan",
            entity_type="source",
            entity_id=str(source.id),
            metadata_json={"offer_id": str(source.offer_id), "url": source.normalized_url},
        )
    )
    db.commit()
    db.refresh(job)

    job = enqueue_or_run_scan_job(db, job)
    return _serialize_job(job)


# ---------- Assets ----------


def _serialize_asset_source(db: Session, asset_source: AssetSource) -> dict[str, Any]:
    asset = asset_source.asset
    parent_asset_id: str | None = None
    if asset_source.parent_asset_source_id:
        parent_as = db.get(AssetSource, asset_source.parent_asset_source_id)
        if parent_as is not None:
            parent_asset_id = str(parent_as.asset_id)
    swipe_count = (
        db.scalar(
            select(func.count(func.distinct(SwipeVersion.swipe_id)))
            .join(SwipeProvenance, SwipeProvenance.swipe_version_id == SwipeVersion.id)
            .where(SwipeProvenance.asset_source_id == asset_source.id)
        )
        or 0
    )
    return {
        "id": str(asset.id),
        "asset_source_id": str(asset_source.id),
        "sha256": asset.sha256,
        "filename": asset_source.original_filename,
        "media_type": asset.media_type,
        "size_bytes": asset.size_bytes,
        "extraction_state": asset.extraction_state,
        "extraction_error": asset.extraction_error,
        "parent_asset_id": parent_asset_id,
        "origin": asset_source.origin,
        "retrieval_url": asset_source.retrieval_url,
        "version_label": asset_source.version_label,
        "retrieved_at": _iso(asset_source.retrieved_at),
        "swipe_count": swipe_count,
    }


@router.get("/offers/{offer_id}/assets")
def list_offer_assets(
    offer_id: str,
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    oid = _parse_uuid(offer_id, "offer_id")
    if db.get(Offer, oid) is None:
        raise ApiError(404, "not_found", "Offer not found")
    rows = db.scalars(
        select(AssetSource)
        .where(AssetSource.offer_id == oid)
        .order_by(AssetSource.retrieved_at.desc())
    ).all()
    return [_serialize_asset_source(db, r) for r in rows]


@router.post("/offers/{offer_id}/assets", status_code=status.HTTP_202_ACCEPTED)
async def upload_offer_asset(
    offer_id: str,
    file: UploadFile = File(...),
    confirm_authorized: str = Form(default="false"),
    source_id: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    oid = _parse_uuid(offer_id, "offer_id")
    offer = db.get(Offer, oid)
    if offer is None:
        raise ApiError(404, "not_found", "Offer not found")

    if confirm_authorized.strip().lower() not in ("true", "1", "yes", "on"):
        raise ApiError(
            400,
            "authorization_required",
            "Operator confirmation of authorization to store and use these materials is required",
        )

    src_uuid: uuid.UUID | None = None
    if source_id and source_id.strip():
        src_uuid = _parse_uuid(source_id.strip(), "source_id")
        src = db.get(Source, src_uuid)
        if src is None or src.offer_id != oid:
            raise ApiError(404, "not_found", "Source not found for offer")

    settings = get_settings()
    data = await file.read(settings.download_max_bytes + 1)
    if len(data) > settings.download_max_bytes:
        raise ApiError(
            413,
            "file_too_large",
            f"File exceeds the {settings.download_max_bytes} byte limit",
        )

    filename = file.filename or "upload.bin"
    try:
        detect_file_type(filename, data)
    except UnsupportedFileError as exc:
        raise ApiError(415, "unsupported_file_type", str(exc)) from exc

    lineage_key = _lineage_key_for_filename(filename)
    asset, asset_source, duplicate_asset = store_or_reuse_asset(
        db,
        offer_id=offer.id,
        filename=filename,
        data=data,
        origin="upload",
        lineage_key=lineage_key,
        source_id=src_uuid,
        notes=(notes or "").strip() or None,
    )

    job = Job(
        offer_id=offer.id,
        source_id=src_uuid,
        asset_source_id=asset_source.id,
        type="ingest_asset",
        state="queued",
        progress_json=default_progress(),
        created_by=user.id,
    )
    db.add(job)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="asset.upload",
            entity_type="asset",
            entity_id=str(asset.id),
            metadata_json={
                "offer_id": str(offer.id),
                "filename": asset_source.original_filename,
                "sha256": asset.sha256,
                "duplicate_asset": duplicate_asset,
            },
        )
    )
    db.commit()
    db.refresh(job)

    if duplicate_asset and asset.extraction_state in ("extracted", "needs_review"):
        prog = default_progress()
        prog["assets_found"] = 1
        prog["assets_processed"] = 1
        prog["duplicates"] = 1
        job.state = "completed"
        job.started_at = utcnow()
        job.finished_at = utcnow()
        job.progress_json = prog
        log_job_event(
            db,
            job,
            "info",
            "duplicate_asset_skipped",
            f"Unchanged asset {asset_source.original_filename} ({asset.sha256[:12]}) already ingested",
        )
        db.commit()
        db.refresh(job)
    else:
        job = enqueue_or_run_ingest_job(db, job)
        db.refresh(asset)
        db.refresh(asset_source)

    return {
        "job": _serialize_job(job),
        "asset": _serialize_asset_source(db, asset_source),
        "duplicate_asset": duplicate_asset,
    }


@router.get("/assets/{asset_id}/download")
def download_asset(
    asset_id: str,
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    aid = _parse_uuid(asset_id, "asset_id")
    asset = db.get(Asset, aid)
    if asset is None:
        raise ApiError(404, "not_found", "Asset not found")
    try:
        blob = read_asset_bytes(asset.storage_key)
    except FileNotFoundError as exc:
        raise ApiError(404, "asset_blob_missing", "Stored asset bytes are missing") from exc
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", asset.filename) or "asset.bin"
    return Response(
        content=blob,
        media_type=asset.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------- Jobs ----------


def _serialize_job(job: Job) -> dict[str, Any]:
    elapsed: float | None = None
    if job.started_at is not None:
        end = job.finished_at or utcnow()
        elapsed = round(max(0.0, (end - job.started_at).total_seconds()), 2)
    return {
        "id": str(job.id),
        "offer_id": str(job.offer_id) if job.offer_id else None,
        "source_id": str(job.source_id) if job.source_id else None,
        "type": job.type,
        "state": job.state,
        "progress": default_progress() | (job.progress_json or {}),
        "attempts": job.attempts,
        "error_summary": job.error_summary,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "elapsed_seconds": elapsed,
        "offer_title": job.offer.title if job.offer else None,
    }


@router.get("/jobs")
def list_jobs(
    state: str | None = None,
    offer_id: str | None = None,
    type: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt: Select[tuple[Job]] = select(Job)
    if state:
        stmt = stmt.where(Job.state == state.strip().lower())
    if offer_id:
        oid = _parse_uuid(offer_id, "offer_id")
        stmt = stmt.where(Job.offer_id == oid)
    if type:
        stmt = stmt.where(Job.type == type.strip().lower())

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Job.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [_serialize_job(j) for j in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    jid = _parse_uuid(job_id, "job_id")
    job = db.get(Job, jid)
    if job is None:
        raise ApiError(404, "not_found", "Job not found")
    events = db.scalars(
        select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.created_at.asc())
    ).all()
    out = _serialize_job(job)
    out["events"] = [
        {
            "id": str(ev.id),
            "level": ev.level,
            "event_type": ev.event_type,
            "message": ev.message,
            "created_at": _iso(ev.created_at),
        }
        for ev in events
    ]
    return out


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    jid = _parse_uuid(job_id, "job_id")
    job = db.get(Job, jid)
    if job is None:
        raise ApiError(404, "not_found", "Job not found")
    if job.state in JOB_TERMINAL_STATES:
        raise ApiError(409, "job_already_terminal", f"Cannot cancel job in state '{job.state}'")

    if job.state == "queued":
        job.state = "cancelled"
        job.finished_at = utcnow()
        log_job_event(db, job, "info", "job_cancelled", "Cancelled while queued")
    else:
        job.state = "cancel_requested"
        log_job_event(db, job, "info", "cancel_requested", "Operator requested cancellation")

    db.add(
        AuditEvent(
            user_id=user.id,
            action="job.cancel",
            entity_type="job",
            entity_id=str(job.id),
            metadata_json={"new_state": job.state},
        )
    )
    db.commit()
    db.refresh(job)
    return _serialize_job(job)


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_job(
    job_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    jid = _parse_uuid(job_id, "job_id")
    prior = db.get(Job, jid)
    if prior is None:
        raise ApiError(404, "not_found", "Job not found")
    if prior.state not in ("failed", "partial", "cancelled"):
        raise ApiError(409, "job_not_retryable", f"Job in state '{prior.state}' cannot be retried")

    new_job = Job(
        offer_id=prior.offer_id,
        source_id=prior.source_id,
        asset_source_id=prior.asset_source_id,
        retry_of_id=prior.id,
        type=prior.type,
        state="queued",
        progress_json=default_progress(),
        created_by=user.id,
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    if new_job.type == "scan_source":
        new_job = enqueue_or_run_scan_job(db, new_job)
    else:
        new_job = enqueue_or_run_ingest_job(db, new_job)
    return _serialize_job(new_job)


# ---------- Swipes & Tags ----------


def _get_swipe_tag_labels(db: Session, swipe_id: uuid.UUID) -> list[str]:
    return list(
        db.scalars(
            select(Tag.label)
            .join(SwipeTag, SwipeTag.tag_id == Tag.id)
            .where(SwipeTag.swipe_id == swipe_id)
            .order_by(Tag.label.asc())
        ).all()
    )


def _serialize_swipe_summary(db: Session, swipe: Swipe) -> dict[str, Any]:
    offer = swipe.offer or db.get(Offer, swipe.offer_id)
    assert offer is not None
    version = db.get(SwipeVersion, swipe.current_version_id) if swipe.current_version_id else None
    assert version is not None
    subjects = [sv.subject for sv in version.subjects]
    version_count = (
        db.scalar(
            select(func.count()).select_from(SwipeVersion).where(SwipeVersion.swipe_id == swipe.id)
        )
        or 1
    )
    excerpt = re.sub(r"\s+", " ", version.body_text or "").strip()[:220]
    return {
        "id": str(swipe.id),
        "offer": {
            "id": str(offer.id),
            "title": offer.title,
            "vendor_name": offer.vendor_name,
            "niche": offer.niche,
            "network_slug": offer.network.slug,
        },
        "title": swipe.title,
        "review_state": swipe.review_state,
        "current_version": {
            "id": str(version.id),
            "version_number": version.version_number,
            "primary_subject": subjects[0] if subjects else None,
            "subject_count": len(subjects),
            "preheader": version.preheader,
            "body_excerpt": excerpt,
            "confidence": version.confidence,
            "flags": list(version.flags_json or []),
        },
        "version_count": version_count,
        "tags": _get_swipe_tag_labels(db, swipe.id),
        "created_at": _iso(swipe.created_at),
        "updated_at": _iso(swipe.updated_at),
    }


def _serialize_swipe_detail(db: Session, swipe: Swipe) -> dict[str, Any]:
    summary = _serialize_swipe_summary(db, swipe)
    summary.pop("current_version", None)

    versions = db.scalars(
        select(SwipeVersion)
        .where(SwipeVersion.swipe_id == swipe.id)
        .order_by(SwipeVersion.version_number.desc())
    ).all()

    versions_out: list[dict[str, Any]] = []
    current_version: SwipeVersion | None = None
    for ver in versions:
        if ver.id == swipe.current_version_id:
            current_version = ver
        prov_rows = db.scalars(
            select(SwipeProvenance)
            .where(SwipeProvenance.swipe_version_id == ver.id)
            .order_by(SwipeProvenance.created_at.asc())
        ).all()
        prov_out = []
        for p in prov_rows:
            asrc = p.asset_source
            prov_out.append(
                {
                    "id": str(p.id),
                    "asset_id": str(asrc.asset_id),
                    "asset_filename": asrc.original_filename,
                    "origin": asrc.origin,
                    "retrieval_url": asrc.retrieval_url,
                    "retrieved_at": _iso(asrc.retrieved_at),
                    "page_number": p.page_number,
                    "section_label": p.section_label or None,
                }
            )
        rev_rows = db.scalars(
            select(ReviewEvent)
            .where(ReviewEvent.swipe_version_id == ver.id)
            .order_by(ReviewEvent.created_at.desc())
        ).all()
        rev_out = [
            {
                "id": str(rv.id),
                "decision": rv.decision,
                "notes": rv.notes,
                "user_email": rv.user.email if rv.user else None,
                "created_at": _iso(rv.created_at),
            }
            for rv in rev_rows
        ]
        versions_out.append(
            {
                "id": str(ver.id),
                "version_number": ver.version_number,
                "subjects": [
                    {"id": str(sv.id), "subject": sv.subject, "position": sv.position}
                    for sv in ver.subjects
                ],
                "preheader": ver.preheader,
                "body_text": ver.body_text,
                "body_html_sanitized": ver.body_html_sanitized,
                "ctas": list(ver.ctas_json or []),
                "normalized_hash": ver.normalized_hash,
                "parser_version": ver.parser_version,
                "confidence": ver.confidence,
                "flags": list(ver.flags_json or []),
                "section_label": ver.section_label,
                "created_at": _iso(ver.created_at),
                "provenance": prov_out,
                "review_events": rev_out,
            }
        )

    exact_other: list[dict[str, Any]] = []
    near_dups: list[dict[str, Any]] = []
    if current_version is not None:
        other_rows = db.execute(
            select(Swipe.id, Offer.id, Offer.title)
            .join(SwipeVersion, SwipeVersion.id == Swipe.current_version_id)
            .join(Offer, Offer.id == Swipe.offer_id)
            .where(
                SwipeVersion.normalized_hash == current_version.normalized_hash,
                Swipe.offer_id != swipe.offer_id,
            )
            .limit(10)
        ).all()
        exact_other = [
            {"swipe_id": str(sid), "offer_id": str(oid), "offer_title": otitle}
            for sid, oid, otitle in other_rows
        ]

        if len((current_version.body_text or "").strip()) >= 40:
            threshold = get_settings().near_duplicate_threshold
            sim_expr = func.similarity(SwipeVersion.body_text, current_version.body_text)
            near_rows = db.execute(
                select(Swipe.id, Offer.title, Swipe.title, sim_expr.label("sim"))
                .join(SwipeVersion, SwipeVersion.id == Swipe.current_version_id)
                .join(Offer, Offer.id == Swipe.offer_id)
                .where(
                    Swipe.id != swipe.id,
                    SwipeVersion.normalized_hash != current_version.normalized_hash,
                    sim_expr >= threshold,
                )
                .order_by(desc("sim"))
                .limit(10)
            ).all()
            near_dups = [
                {
                    "swipe_id": str(sid),
                    "offer_title": otitle,
                    "title": stitle,
                    "similarity": round(float(sim), 3),
                }
                for sid, otitle, stitle, sim in near_rows
            ]

    return {
        **summary,
        "notes": swipe.notes,
        "current_version_id": str(swipe.current_version_id) if swipe.current_version_id else None,
        "versions": versions_out,
        "duplicates": {"exact_other_offers": exact_other, "near": near_dups},
    }


@router.get("/swipes")
def list_swipes(
    q: str | None = None,
    network: str | None = None,
    niche: str | None = None,
    review_state: str | None = None,
    offer_id: str | None = None,
    tag: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: str = Query(default="newest"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt: Select[tuple[Swipe]] = (
        select(Swipe)
        .join(Offer, Offer.id == Swipe.offer_id)
        .join(Network, Network.id == Offer.network_id)
        .join(SwipeVersion, SwipeVersion.id == Swipe.current_version_id)
    )

    rank_expr = None
    if q and q.strip():
        query_text = q.strip()
        tsq = func.websearch_to_tsquery("english", query_text)
        pat = f"%{query_text}%"
        stmt = stmt.where(or_(Swipe.search_tsv.op("@@")(tsq), Swipe.search_document.ilike(pat)))
        rank_expr = func.ts_rank_cd(Swipe.search_tsv, tsq) + func.similarity(
            Swipe.search_document, query_text
        )

    if network:
        stmt = stmt.where(func.lower(Network.slug) == network.strip().lower())
    if niche:
        stmt = stmt.where(func.lower(Offer.niche) == niche.strip().lower())
    if review_state:
        stmt = stmt.where(Swipe.review_state == review_state.strip().lower())
    if offer_id:
        oid = _parse_uuid(offer_id, "offer_id")
        stmt = stmt.where(Swipe.offer_id == oid)
    if tag and tag.strip():
        slug, label = _slugify_tag(tag)
        stmt = stmt.where(
            Swipe.id.in_(
                select(SwipeTag.swipe_id)
                .join(Tag, Tag.id == SwipeTag.tag_id)
                .where(or_(Tag.slug == slug, func.lower(Tag.label) == label.lower()))
            )
        )
    if created_from is not None:
        stmt = stmt.where(Swipe.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Swipe.created_at <= created_to)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    if sort == "confidence":
        stmt = stmt.order_by(SwipeVersion.confidence.asc(), Swipe.created_at.desc())
    elif sort == "relevance" and rank_expr is not None:
        stmt = stmt.order_by(rank_expr.desc(), Swipe.created_at.desc())
    else:
        stmt = stmt.order_by(Swipe.created_at.desc())

    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [_serialize_swipe_summary(db, s) for s in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/swipes/{swipe_id}")
def get_swipe(
    swipe_id: str,
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sid = _parse_uuid(swipe_id, "swipe_id")
    swipe = db.get(Swipe, sid)
    if swipe is None:
        raise ApiError(404, "not_found", "Swipe not found")
    return _serialize_swipe_detail(db, swipe)


@router.patch("/swipes/{swipe_id}")
def update_swipe(
    swipe_id: str,
    payload: SwipeUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sid = _parse_uuid(swipe_id, "swipe_id")
    swipe = db.get(Swipe, sid)
    if swipe is None:
        raise ApiError(404, "not_found", "Swipe not found")

    fields = payload.model_dump(exclude_unset=True)
    if "title" in fields:
        swipe.title = (fields["title"] or "").strip() or None
    if "notes" in fields:
        swipe.notes = (fields["notes"] or "").strip() or None
    swipe.updated_at = utcnow()
    refresh_swipe_search_document(db, swipe)

    db.add(
        AuditEvent(
            user_id=user.id,
            action="swipe.update",
            entity_type="swipe",
            entity_id=str(swipe.id),
            metadata_json={"updated_fields": sorted(fields.keys())},
        )
    )
    db.commit()
    db.refresh(swipe)
    return _serialize_swipe_detail(db, swipe)


@router.post("/swipes/{swipe_id}/review")
def review_swipe(
    swipe_id: str,
    payload: SwipeReviewRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sid = _parse_uuid(swipe_id, "swipe_id")
    vid = _parse_uuid(payload.version_id, "version_id")
    swipe = db.get(Swipe, sid)
    if swipe is None:
        raise ApiError(404, "not_found", "Swipe not found")
    if swipe.current_version_id != vid:
        raise ApiError(
            409,
            "stale_version",
            "Review decision must target the swipe's current version",
            details={"current_version_id": str(swipe.current_version_id)},
        )

    event = ReviewEvent(
        swipe_version_id=vid,
        user_id=user.id,
        decision=payload.decision,
        notes=(payload.notes or "").strip() or None,
    )
    swipe.review_state = payload.decision
    swipe.updated_at = utcnow()
    db.add(event)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="swipe.review",
            entity_type="swipe",
            entity_id=str(swipe.id),
            metadata_json={"version_id": str(vid), "decision": payload.decision},
        )
    )
    db.commit()
    db.refresh(swipe)
    return _serialize_swipe_detail(db, swipe)


def _set_swipe_tags(db: Session, swipe: Swipe, raw_tags: list[str], replace: bool) -> None:
    if replace:
        db.query(SwipeTag).where(SwipeTag.swipe_id == swipe.id).delete()
        db.flush()

    existing_tag_ids = {
        tid
        for tid in db.scalars(select(SwipeTag.tag_id).where(SwipeTag.swipe_id == swipe.id)).all()
    }
    for raw in raw_tags:
        slug, label = _slugify_tag(raw)
        if not slug:
            continue
        tag = db.scalar(select(Tag).where(Tag.slug == slug))
        if tag is None:
            tag = Tag(slug=slug, label=label)
            db.add(tag)
            db.flush()
        if tag.id not in existing_tag_ids:
            db.add(SwipeTag(swipe_id=swipe.id, tag_id=tag.id))
            existing_tag_ids.add(tag.id)
    db.flush()
    refresh_swipe_search_document(db, swipe)


@router.post("/swipes/{swipe_id}/tags")
def set_swipe_tags(
    swipe_id: str,
    payload: SwipeTagsRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sid = _parse_uuid(swipe_id, "swipe_id")
    swipe = db.get(Swipe, sid)
    if swipe is None:
        raise ApiError(404, "not_found", "Swipe not found")
    _set_swipe_tags(db, swipe, payload.tags, replace=True)
    swipe.updated_at = utcnow()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="swipe.tags",
            entity_type="swipe",
            entity_id=str(swipe.id),
            metadata_json={"tags": payload.tags},
        )
    )
    db.commit()
    db.refresh(swipe)
    return _serialize_swipe_detail(db, swipe)


@router.post("/swipes/bulk")
def bulk_update_swipes(
    payload: SwipeBulkRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    uuids = [_parse_uuid(raw, "swipe_id") for raw in payload.swipe_ids]
    swipes = db.scalars(select(Swipe).where(Swipe.id.in_(uuids))).all()
    updated = 0
    for swipe in swipes:
        if payload.action == "archive":
            swipe.review_state = "archived"
            swipe.updated_at = utcnow()
            if swipe.current_version_id is not None:
                db.add(
                    ReviewEvent(
                        swipe_version_id=swipe.current_version_id,
                        user_id=user.id,
                        decision="archived",
                        notes="Bulk archive",
                    )
                )
            updated += 1
        elif payload.action == "add_tags":
            _set_swipe_tags(db, swipe, payload.tags or [], replace=False)
            swipe.updated_at = utcnow()
            updated += 1

    db.add(
        AuditEvent(
            user_id=user.id,
            action=f"swipes.bulk_{payload.action}",
            entity_type="swipe",
            entity_id=None,
            metadata_json={"updated": updated},
        )
    )
    db.commit()
    return {"updated": updated}


@router.get("/tags")
def list_tags(
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Tag.id, Tag.slug, Tag.label, func.count(SwipeTag.swipe_id).label("cnt"))
        .outerjoin(SwipeTag, SwipeTag.tag_id == Tag.id)
        .group_by(Tag.id, Tag.slug, Tag.label)
        .order_by(Tag.label.asc())
    ).all()
    return [
        {"id": str(tid), "slug": slug, "label": label, "swipe_count": int(cnt or 0)}
        for tid, slug, label, cnt in rows
    ]


# ---------- Brand Profiles (Phase 3 — FR-07) ----------


def _serialize_brand(brand: BrandProfile) -> dict[str, Any]:
    return {
        "id": str(brand.id),
        "name": brand.name,
        "slug": brand.slug,
        "sender_identity_ref": brand.sender_identity_ref,
        "affiliate_settings_json": dict(brand.affiliate_settings_json or {}),
        "disclosure_text": brand.disclosure_text,
        "footer_template": brand.footer_template,
        "integration_ref": brand.integration_ref,
        "created_at": _iso(brand.created_at),
        "updated_at": _iso(brand.updated_at),
    }


@router.get("/brands")
def list_brands(
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = db.scalars(select(BrandProfile).order_by(BrandProfile.name.asc())).all()
    return [_serialize_brand(b) for b in rows]


@router.post("/brands", status_code=status.HTTP_201_CREATED)
def create_brand(
    payload: BrandCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    name = payload.name.strip()
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:100] or "brand"
    dup = db.scalar(
        select(BrandProfile).where(
            or_(func.lower(BrandProfile.name) == name.lower(), BrandProfile.slug == slug)
        )
    )
    if dup is not None:
        raise ApiError(409, "duplicate_brand", f"Brand '{name}' already exists")

    brand = BrandProfile(
        name=name,
        slug=slug,
        sender_identity_ref=(payload.sender_identity_ref or "").strip() or None,
        affiliate_settings_json=payload.affiliate_settings_json,
        disclosure_text=payload.disclosure_text.strip(),
        footer_template=payload.footer_template.strip(),
        integration_ref=(payload.integration_ref or "").strip() or None,
    )
    db.add(brand)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="brand.create",
            entity_type="brand",
            entity_id=str(brand.id),
            metadata_json={"name": brand.name},
        )
    )
    db.commit()
    db.refresh(brand)
    return _serialize_brand(brand)


@router.patch("/brands/{brand_id}")
def update_brand(
    brand_id: str,
    payload: BrandUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    bid = _parse_uuid(brand_id, "brand_id")
    brand = db.get(BrandProfile, bid)
    if brand is None:
        raise ApiError(404, "not_found", "Brand profile not found")

    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] is not None:
        name = fields["name"].strip()
        slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:100] or brand.slug
        dup = db.scalar(
            select(BrandProfile).where(
                BrandProfile.id != brand.id,
                or_(func.lower(BrandProfile.name) == name.lower(), BrandProfile.slug == slug),
            )
        )
        if dup is not None:
            raise ApiError(409, "duplicate_brand", f"Brand '{name}' already exists")
        brand.name = name
        brand.slug = slug
    if "sender_identity_ref" in fields:
        brand.sender_identity_ref = (fields["sender_identity_ref"] or "").strip() or None
    if "affiliate_settings_json" in fields and fields["affiliate_settings_json"] is not None:
        brand.affiliate_settings_json = fields["affiliate_settings_json"]
    if "disclosure_text" in fields and fields["disclosure_text"] is not None:
        brand.disclosure_text = fields["disclosure_text"].strip()
    if "footer_template" in fields and fields["footer_template"] is not None:
        brand.footer_template = fields["footer_template"].strip()
    if "integration_ref" in fields:
        brand.integration_ref = (fields["integration_ref"] or "").strip() or None

    brand.updated_at = utcnow()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="brand.update",
            entity_type="brand",
            entity_id=str(brand.id),
            metadata_json={"updated_fields": sorted(fields.keys())},
        )
    )
    db.commit()
    db.refresh(brand)
    return _serialize_brand(brand)


# ---------- Campaign Drafts & Listmonk Draft Export (Phase 3 — FR-07, FR-08) ----------


def _serialize_export(exp: Export) -> dict[str, Any]:
    return {
        "id": str(exp.id),
        "draft_id": str(exp.draft_id),
        "draft_version": exp.draft_version,
        "target": exp.target,
        "idempotency_key": exp.idempotency_key,
        "remote_id": exp.remote_id,
        "remote_url": exp.remote_url,
        "status": exp.status,
        "error_summary": exp.error_summary,
        "created_at": _iso(exp.created_at),
        "updated_at": _iso(exp.updated_at),
    }


def _serialize_draft(db: Session, draft: Draft, *, include_detail: bool = False) -> dict[str, Any]:
    ver = draft.swipe_version or db.get(SwipeVersion, draft.swipe_version_id)
    assert ver is not None
    swipe = db.get(Swipe, ver.swipe_id)
    assert swipe is not None
    offer = swipe.offer or db.get(Offer, swipe.offer_id)
    assert offer is not None
    brand = draft.brand or db.get(BrandProfile, draft.brand_id)
    assert brand is not None

    out: dict[str, Any] = {
        "id": str(draft.id),
        "swipe_id": str(swipe.id),
        "swipe_version_id": str(ver.id),
        "swipe_version_number": ver.version_number,
        "offer": {
            "id": str(offer.id),
            "title": offer.title,
            "vendor_name": offer.vendor_name,
            "network_slug": offer.network.slug,
        },
        "brand": {"id": str(brand.id), "name": brand.name, "slug": brand.slug},
        "title": draft.title,
        "subject": draft.subject,
        "preheader": draft.preheader,
        "affiliate_url": draft.affiliate_url,
        "body_html": draft.body_html,
        "body_text": draft.body_text,
        "status": draft.status,
        "version": draft.version,
        "approved_version": draft.approved_version,
        "approved_at": _iso(draft.approved_at),
        "review_checks": dict(draft.review_checks_json or {}),
        "sequence_position": draft.sequence_position,
        "suggested_day_offset": draft.suggested_day_offset,
        "created_at": _iso(draft.created_at),
        "updated_at": _iso(draft.updated_at),
    }
    if include_detail:
        out["available_subjects"] = [sv.subject for sv in ver.subjects]
        out["source_ctas"] = list(ver.ctas_json or [])
        exports = db.scalars(
            select(Export).where(Export.draft_id == draft.id).order_by(Export.created_at.desc())
        ).all()
        out["exports"] = [_serialize_export(e) for e in exports]
    return out


@router.get("/drafts")
def list_drafts(
    brand_id: str | None = None,
    offer_id: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt: Select[tuple[Draft]] = (
        select(Draft)
        .join(SwipeVersion, SwipeVersion.id == Draft.swipe_version_id)
        .join(Swipe, Swipe.id == SwipeVersion.swipe_id)
    )
    if brand_id:
        bid = _parse_uuid(brand_id, "brand_id")
        stmt = stmt.where(Draft.brand_id == bid)
    if offer_id:
        oid = _parse_uuid(offer_id, "offer_id")
        stmt = stmt.where(Swipe.offer_id == oid)
    if status:
        stmt = stmt.where(Draft.status == status.strip().lower())

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Draft.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [_serialize_draft(db, d) for d in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/drafts", status_code=status.HTTP_201_CREATED)
def create_draft(
    payload: DraftCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sid = _parse_uuid(payload.swipe_id, "swipe_id")
    bid = _parse_uuid(payload.brand_id, "brand_id")
    swipe = db.get(Swipe, sid)
    if swipe is None or swipe.current_version_id is None:
        raise ApiError(404, "not_found", "Swipe not found")
    if swipe.review_state != "approved":
        raise ApiError(
            409,
            "swipe_not_approved",
            "Only approved swipes can be used to create campaign drafts (FR-06/FR-07)",
        )

    brand = db.get(BrandProfile, bid)
    if brand is None:
        raise ApiError(404, "not_found", "Brand profile not found")

    version = db.get(SwipeVersion, swipe.current_version_id)
    assert version is not None

    clean_aff, aff_valid, aff_err = validate_affiliate_url(payload.affiliate_url)
    if payload.affiliate_url and not aff_valid:
        raise ApiError(422, "unsafe_url", f"affiliate_url: {aff_err}")

    subject, body_text, body_html, checks = build_initial_draft_content(
        version=version,
        brand=brand,
        subject_position=payload.subject_position,
        affiliate_url=clean_aff,
        replace_urls=payload.replace_urls,
    )

    draft = Draft(
        swipe_version_id=version.id,
        brand_id=brand.id,
        title=f"{brand.name} — {swipe.title or subject[:80]}"[:500],
        subject=subject,
        preheader=version.preheader,
        affiliate_url=clean_aff,
        body_text=body_text,
        body_html=body_html,
        status="editing",
        version=1,
        review_checks_json=checks,
        sequence_position=payload.sequence_position,
        suggested_day_offset=payload.suggested_day_offset,
        created_by=user.id,
    )
    db.add(draft)
    db.flush()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="draft.create",
            entity_type="draft",
            entity_id=str(draft.id),
            metadata_json={"swipe_id": str(swipe.id), "brand": brand.slug},
        )
    )
    db.commit()
    db.refresh(draft)
    return _serialize_draft(db, draft, include_detail=True)


@router.get("/drafts/{draft_id}")
def get_draft(
    draft_id: str,
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    did = _parse_uuid(draft_id, "draft_id")
    draft = db.get(Draft, did)
    if draft is None:
        raise ApiError(404, "not_found", "Draft not found")
    return _serialize_draft(db, draft, include_detail=True)


@router.patch("/drafts/{draft_id}")
def update_draft(
    draft_id: str,
    payload: DraftUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    did = _parse_uuid(draft_id, "draft_id")
    draft = db.get(Draft, did)
    if draft is None:
        raise ApiError(404, "not_found", "Draft not found")

    brand = draft.brand or db.get(BrandProfile, draft.brand_id)
    assert brand is not None

    fields = payload.model_dump(exclude_unset=True)
    material_changed = False

    if "affiliate_url" in fields:
        clean_aff, aff_valid, aff_err = validate_affiliate_url(fields["affiliate_url"])
        if fields["affiliate_url"] and not aff_valid:
            raise ApiError(422, "unsafe_url", f"affiliate_url: {aff_err}")
        if clean_aff != draft.affiliate_url:
            draft.affiliate_url = clean_aff
            material_changed = True

    if "title" in fields and fields["title"] is not None:
        draft.title = fields["title"].strip()

    if "subject" in fields and fields["subject"] is not None:
        new_subj = fields["subject"].strip()
        if new_subj != draft.subject:
            draft.subject = new_subj
            material_changed = True

    if "preheader" in fields:
        new_pre = (fields["preheader"] or "").strip() or None
        if new_pre != draft.preheader:
            draft.preheader = new_pre
            material_changed = True

    body_text = (
        fields["body_text"]
        if "body_text" in fields and fields["body_text"] is not None
        else draft.body_text
    )
    if payload.replace_placeholders or payload.replace_urls:
        body_text = apply_targeted_link_replacements(
            body_text,
            affiliate_url=draft.affiliate_url,
            replace_placeholders=payload.replace_placeholders,
            replace_urls=payload.replace_urls,
        )
    if payload.append_brand_footer:
        body_text = ensure_brand_disclosure_and_footer(body_text, brand)

    if body_text != draft.body_text:
        draft.body_text = body_text
        material_changed = True

    if "body_html" in fields and fields["body_html"] is not None and not (
        payload.replace_placeholders or payload.replace_urls or payload.append_brand_footer
    ):
        sanitized = sanitize_html(fields["body_html"])
        if sanitized != draft.body_html:
            draft.body_html = sanitized
            material_changed = True
    elif material_changed:
        draft.body_html = render_draft_html(draft.body_text)

    if "sequence_position" in fields:
        draft.sequence_position = fields["sequence_position"]
    if "suggested_day_offset" in fields:
        draft.suggested_day_offset = fields["suggested_day_offset"]

    # Material draft edits increment version and invalidate prior approval (FR-07, AC-11)
    if material_changed:
        draft.version = (draft.version or 1) + 1
        draft.approved_version = None
        draft.approved_at = None
        draft.approved_by = None
        draft.status = "editing"
    elif "status" in fields and fields["status"] is not None:
        draft.status = fields["status"]
        if draft.status == "editing":
            draft.approved_version = None
            draft.approved_at = None

    draft.review_checks_json = compute_draft_review_checks(
        subject=draft.subject,
        preheader=draft.preheader,
        body_text=draft.body_text,
        body_html=draft.body_html,
        affiliate_url=draft.affiliate_url,
        brand=brand,
    )
    draft.updated_at = utcnow()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="draft.update",
            entity_type="draft",
            entity_id=str(draft.id),
            metadata_json={"version": draft.version, "material_changed": material_changed},
        )
    )
    db.commit()
    db.refresh(draft)
    return _serialize_draft(db, draft, include_detail=True)


@router.post("/drafts/{draft_id}/approve")
def approve_draft(
    draft_id: str,
    payload: DraftApproveRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    did = _parse_uuid(draft_id, "draft_id")
    draft = db.get(Draft, did)
    if draft is None:
        raise ApiError(404, "not_found", "Draft not found")

    if payload.version != draft.version:
        raise ApiError(
            409,
            "stale_draft_version",
            f"Approval request targets version {payload.version}, but current draft is version {draft.version}",
            details={"current_version": draft.version},
        )

    brand = draft.brand or db.get(BrandProfile, draft.brand_id)
    assert brand is not None
    checks = compute_draft_review_checks(
        subject=draft.subject,
        preheader=draft.preheader,
        body_text=draft.body_text,
        body_html=draft.body_html,
        affiliate_url=draft.affiliate_url,
        brand=brand,
    )
    draft.review_checks_json = checks
    if not checks.get("ready_for_approval"):
        raise ApiError(
            422,
            "draft_checks_failed",
            "Draft cannot be approved until affiliate link, disclosure, footer, and placeholder checks pass",
            details=checks,
        )

    draft.status = "approved"
    draft.approved_version = draft.version
    draft.approved_at = utcnow()
    draft.approved_by = user.id
    draft.updated_at = utcnow()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="draft.approve",
            entity_type="draft",
            entity_id=str(draft.id),
            metadata_json={"approved_version": draft.version},
        )
    )
    db.commit()
    db.refresh(draft)
    return _serialize_draft(db, draft, include_detail=True)


def _require_approved_draft(draft: Draft) -> None:
    if draft.status not in ("approved", "exported") or draft.approved_version != draft.version:
        raise ApiError(
            409,
            "draft_not_approved",
            "Draft must be approved at its current version before exporting or downloading (AC-11)",
            details={"current_version": draft.version, "approved_version": draft.approved_version},
        )


@router.get("/drafts/{draft_id}/download")
def download_draft(
    draft_id: str,
    format: str = Query(default="html"),
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    did = _parse_uuid(draft_id, "draft_id")
    draft = db.get(Draft, did)
    if draft is None:
        raise ApiError(404, "not_found", "Draft not found")
    _require_approved_draft(draft)

    fmt = format.strip().lower()
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", draft.title)[:80] or "draft"
    if fmt == "txt":
        content = f"Subject: {draft.subject}\nPreheader: {draft.preheader or ''}\n\n{draft.body_text}"
        return Response(
            content=content.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{slug}_v{draft.version}.txt"'},
        )
    html_doc = (
        f"<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>{draft.subject}</title></head>\n"
        f"<body>\n{draft.body_html}\n</body></html>"
    )
    return Response(
        content=html_doc.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}_v{draft.version}.html"'},
    )


@router.post("/integrations/listmonk/test")
def test_listmonk(_user: User = Depends(require_user)) -> dict[str, Any]:
    return test_listmonk_connection()


@router.post("/drafts/{draft_id}/export/listmonk")
def export_draft_listmonk(
    draft_id: str,
    payload: ListmonkExportRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    did = _parse_uuid(draft_id, "draft_id")
    draft = db.get(Draft, did)
    if draft is None:
        raise ApiError(404, "not_found", "Draft not found")
    _require_approved_draft(draft)

    if not payload.confirm_unsent_draft:
        raise ApiError(
            400,
            "confirmation_required",
            "Explicit confirmation to create an unsent Listmonk draft campaign is required",
        )

    brand = draft.brand or db.get(BrandProfile, draft.brand_id)
    assert brand is not None
    export_row = export_unsent_draft_to_listmonk(
        db,
        draft=draft,
        brand=brand,
        list_ids=payload.list_ids,
        user=user,
    )
    db.add(
        AuditEvent(
            user_id=user.id,
            action="draft.export_listmonk",
            entity_type="draft",
            entity_id=str(draft.id),
            metadata_json={
                "export_id": str(export_row.id),
                "draft_version": draft.version,
                "status": export_row.status,
                "remote_id": export_row.remote_id,
            },
        )
    )
    db.commit()
    return _serialize_export(export_row)


@router.get("/exports/{export_id}")
def get_export(
    export_id: str,
    _user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    eid = _parse_uuid(export_id, "export_id")
    exp = db.get(Export, eid)
    if exp is None:
        raise ApiError(404, "not_found", "Export not found")
    return _serialize_export(exp)


__all__ = ["router", "normalize_text"]
