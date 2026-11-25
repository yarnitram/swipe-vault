"""Listmonk draft-only integration adapter (Phase 3 — FR-08, AC-12).

Safety invariants:
- Strictly creates unsent draft campaigns via ``POST /api/campaigns``.
- Contains ZERO methods or endpoints for starting, scheduling, sending campaigns, or importing subscribers.
- Requires explicit list IDs (never selects all subscribers automatically).
- Uses deterministic idempotency keys so retries never create duplicate remote drafts.
- On ambiguous network errors after request dispatch, records status ``needs_reconciliation`` instead of retrying.
"""

import hashlib
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import BrandProfile, Draft, Export, User, utcnow
from app.settings import get_settings


def compute_export_idempotency_key(draft_id: str, draft_version: int, list_ids: list[int]) -> str:
    sorted_ids = ",".join(str(i) for i in sorted(set(list_ids)))
    raw = f"listmonk:{draft_id}:v{draft_version}:lists={sorted_ids}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _auth_tuple() -> tuple[str, str]:
    settings = get_settings()
    return (settings.listmonk_api_username or "", settings.listmonk_api_token or "")


def _base_url() -> str:
    settings = get_settings()
    return (settings.listmonk_base_url or "").strip().rstrip("/")


def test_listmonk_connection(
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Validate Listmonk connectivity and fetch available lists without exposing credentials."""
    settings = get_settings()
    if not settings.listmonk_enabled:
        return {
            "enabled": False,
            "configured": settings.listmonk_configured,
            "reachable": False,
            "lists": [],
            "message": (
                "Listmonk integration is disabled (LISTMONK_ENABLED=false). "
                "Local HTML/text download is active."
            ),
        }
    if not settings.listmonk_configured:
        return {
            "enabled": True,
            "configured": False,
            "reachable": False,
            "lists": [],
            "message": "Listmonk credentials or LISTMONK_BASE_URL are not configured.",
        }

    base = _base_url()
    try:
        with httpx.Client(
            timeout=settings.listmonk_timeout_seconds,
            auth=_auth_tuple(),
            transport=transport,
        ) as client:
            resp = client.get(f"{base}/api/lists")
            if resp.status_code == 401 or resp.status_code == 403:
                return {
                    "enabled": True,
                    "configured": True,
                    "reachable": False,
                    "lists": [],
                    "message": f"Listmonk authentication failed (HTTP {resp.status_code}).",
                }
            resp.raise_for_status()
            payload = resp.json()
            results = ((payload.get("data") or {}).get("results")) or []
            lists = [
                {
                    "id": int(item["id"]),
                    "name": str(item.get("name") or f"List {item['id']}"),
                    "type": str(item.get("type") or "private"),
                }
                for item in results
                if isinstance(item, dict) and "id" in item
            ]
            return {
                "enabled": True,
                "configured": True,
                "reachable": True,
                "lists": lists,
                "message": f"Connected to Listmonk ({len(lists)} list(s) available).",
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": True,
            "configured": True,
            "reachable": False,
            "lists": [],
            "message": f"Listmonk connection failed: {exc.__class__.__name__}",
        }


def export_unsent_draft_to_listmonk(
    db: Session,
    *,
    draft: Draft,
    brand: BrandProfile,
    list_ids: list[int],
    user: User,
    transport: httpx.BaseTransport | None = None,
) -> Export:
    """Create an unsent draft campaign in Listmonk idempotently (FR-08, AC-12)."""
    settings = get_settings()
    if not settings.listmonk_enabled or not settings.listmonk_configured:
        raise ApiError(
            409,
            "listmonk_disabled",
            "Listmonk remote export is disabled or unconfigured; use local HTML/text download instead",
        )

    clean_lists = sorted({int(i) for i in list_ids if int(i) > 0})
    if not clean_lists:
        raise ApiError(
            422,
            "list_selection_required",
            "At least one explicit target list ID is required; "
            "automatic selection of all subscribers is prohibited",
        )

    idem_key = compute_export_idempotency_key(str(draft.id), draft.version, clean_lists)
    existing = db.scalar(select(Export).where(Export.idempotency_key == idem_key))
    if existing is not None:
        if existing.status == "completed":
            return existing
        if existing.status == "needs_reconciliation":
            raise ApiError(
                409,
                "export_needs_reconciliation",
                "A prior export attempt encountered an ambiguous network error and needs "
                "reconciliation in Listmonk before retrying",
                details={"export_id": str(existing.id)},
            )
        export_row = existing
        export_row.status = "pending"
        export_row.error_summary = None
        export_row.updated_at = utcnow()
    else:
        export_row = Export(
            draft_id=draft.id,
            draft_version=draft.version,
            target="listmonk",
            idempotency_key=idem_key,
            status="pending",
            created_by=user.id,
        )
        db.add(export_row)
    db.commit()
    db.refresh(export_row)

    base = _base_url()
    campaign_payload: dict[str, Any] = {
        "name": f"[SwipeVault Draft v{draft.version}] {draft.title}"[:250],
        "subject": draft.subject,
        "lists": clean_lists,
        "type": "regular",
        "content_type": "html",
        "body": draft.body_html,
        "altbody": draft.body_text,
        "tags": ["swipevault", brand.slug],
    }
    if brand.sender_identity_ref:
        campaign_payload["from_email"] = brand.sender_identity_ref

    try:
        with httpx.Client(
            timeout=settings.listmonk_timeout_seconds,
            auth=_auth_tuple(),
            transport=transport,
        ) as client:
            resp = client.post(
                f"{base}/api/campaigns",
                json=campaign_payload,
                headers={"X-Idempotency-Key": idem_key},
            )
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError, httpx.NetworkError) as exc:
        # Ambiguous network failure after dispatch: never blindly retry creation (FR-08)
        export_row.status = "needs_reconciliation"
        export_row.error_summary = (
            f"Ambiguous network failure ({exc.__class__.__name__}) after sending request; "
            "verify in Listmonk whether the draft campaign was created before reconciling."
        )
        export_row.updated_at = utcnow()
        db.commit()
        db.refresh(export_row)
        return export_row
    except httpx.HTTPError as exc:
        export_row.status = "failed"
        export_row.error_summary = f"Connection failed before campaign creation: {exc.__class__.__name__}"
        export_row.updated_at = utcnow()
        db.commit()
        db.refresh(export_row)
        return export_row

    if resp.status_code >= 500:
        export_row.status = "needs_reconciliation"
        export_row.error_summary = (
            f"Listmonk returned HTTP {resp.status_code}; verify remote campaigns before retrying"
        )
        export_row.updated_at = utcnow()
        db.commit()
        db.refresh(export_row)
        return export_row

    if resp.status_code >= 400:
        export_row.status = "failed"
        export_row.error_summary = f"Listmonk rejected draft creation (HTTP {resp.status_code})"
        export_row.updated_at = utcnow()
        db.commit()
        db.refresh(export_row)
        return export_row

    body_json = resp.json() if resp.content else {}
    data_obj = body_json.get("data") or {}
    remote_id = str(data_obj.get("id") or "")
    remote_status = str(data_obj.get("status") or "draft").lower()
    if remote_status not in ("draft", ""):
        export_row.status = "failed"
        export_row.error_summary = f"Unexpected remote campaign status '{remote_status}' (expected 'draft')"
        export_row.updated_at = utcnow()
        db.commit()
        db.refresh(export_row)
        return export_row

    export_row.remote_id = remote_id or None
    export_row.remote_url = f"{base}/campaigns/{remote_id}" if remote_id else None
    export_row.status = "completed"
    export_row.error_summary = None
    export_row.updated_at = utcnow()

    draft.status = "exported"
    draft.updated_at = utcnow()
    db.commit()
    db.refresh(export_row)
    return export_row
