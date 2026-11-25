"""CSV preview and commit service for offer catalog imports (FR-01, AC-02)."""

import csv
import io
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import AuditEvent, Network, Offer, User
from app.security.urls import UnsafeUrlError, validate_source_url

REQUIRED_COLUMNS = (
    "network",
    "external_offer_id",
    "title",
    "niche",
    "vendor_name",
    "offer_url",
    "affiliate_resources_url",
    "notes",
)


def _clean_cell(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def validate_offer_row(
    db: Session,
    *,
    raw: dict[str, Any],
    networks_by_slug: dict[str, Network],
    seen_external_ids: set[tuple[str, str]],
    seen_titles: set[tuple[str, str]],
) -> tuple[dict[str, str | None], str, list[str], str | None]:
    data = {col: _clean_cell(str(raw.get(col) or "")) for col in REQUIRED_COLUMNS}
    errors: list[str] = []
    existing_offer_id: str | None = None

    net_slug = (data["network"] or "").lower()
    data["network"] = net_slug or None
    network = networks_by_slug.get(net_slug) if net_slug else None
    if not net_slug:
        errors.append("network is required")
    elif network is None:
        errors.append(f"unknown network '{net_slug}'")

    title = data["title"]
    if not title:
        errors.append("title is required")
    elif len(title) > 500:
        errors.append("title exceeds 500 characters")

    for url_field in ("offer_url", "affiliate_resources_url"):
        val = data[url_field]
        if val:
            try:
                clean_url, _ = validate_source_url(val)
                data[url_field] = clean_url
            except UnsafeUrlError as exc:
                errors.append(f"{url_field}: {exc}")

    if errors:
        return data, "invalid", errors, None

    assert network is not None
    assert title is not None
    ext_id = data["external_offer_id"]

    # Check in-file duplicates first
    if ext_id:
        ext_key = (net_slug, ext_id.lower())
        if ext_key in seen_external_ids:
            return data, "duplicate_in_file", [f"Duplicate external_offer_id '{ext_id}' in file"], None
        seen_external_ids.add(ext_key)
    else:
        title_key = (net_slug, title.lower())
        if title_key in seen_titles:
            return data, "duplicate_in_file", [f"Duplicate title '{title}' in file"], None
        seen_titles.add(title_key)

    # Check database duplicates
    if ext_id:
        existing = db.scalar(
            select(Offer).where(
                Offer.network_id == network.id,
                func.lower(Offer.external_offer_id) == ext_id.lower(),
            )
        )
        if existing is not None:
            existing_offer_id = str(existing.id)
            return (
                data,
                "duplicate_existing",
                [f"Offer with external_offer_id '{ext_id}' already exists"],
                existing_offer_id,
            )
    else:
        existing = db.scalar(
            select(Offer).where(
                Offer.network_id == network.id,
                func.lower(Offer.title) == title.lower(),
            )
        )
        if existing is not None:
            existing_offer_id = str(existing.id)
            return (
                data,
                "duplicate_existing",
                [f"Offer titled '{title}' already exists for {net_slug}"],
                existing_offer_id,
            )

    return data, "valid", [], None


def preview_csv_bytes(db: Session, content: bytes) -> dict[str, Any]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApiError(400, "invalid_csv_encoding", "CSV must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ApiError(400, "invalid_csv_header", "CSV has no header row")

    normalized_headers = [h.strip() for h in reader.fieldnames if h]
    missing = [col for col in REQUIRED_COLUMNS if col not in normalized_headers]
    if missing:
        raise ApiError(
            400,
            "invalid_csv_header",
            f"CSV header is missing required columns: {', '.join(missing)}",
            details={"missing_columns": missing, "required_columns": list(REQUIRED_COLUMNS)},
        )

    networks = db.scalars(select(Network)).all()
    networks_by_slug = {n.slug.lower(): n for n in networks}
    seen_external_ids: set[tuple[str, str]] = set()
    seen_titles: set[tuple[str, str]] = set()

    rows_out: list[dict[str, Any]] = []
    counts = {"total": 0, "valid": 0, "invalid": 0, "duplicates": 0}

    for idx, raw_row in enumerate(reader, start=2):
        cleaned_map = {(k.strip() if k else ""): v for k, v in raw_row.items()}
        if not any((v or "").strip() for v in cleaned_map.values()):
            continue
        counts["total"] += 1
        data, status, errors, existing_id = validate_offer_row(
            db,
            raw=cleaned_map,
            networks_by_slug=networks_by_slug,
            seen_external_ids=seen_external_ids,
            seen_titles=seen_titles,
        )
        if status == "valid":
            counts["valid"] += 1
        elif status == "invalid":
            counts["invalid"] += 1
        else:
            counts["duplicates"] += 1
        rows_out.append(
            {
                "row_number": idx,
                "data": data,
                "status": status,
                "errors": errors,
                "existing_offer_id": existing_id,
            }
        )

    return {"rows": rows_out, "summary": counts}


def commit_csv_rows(db: Session, rows: list[dict[str, Any]], user: User) -> dict[str, Any]:
    networks = db.scalars(select(Network)).all()
    networks_by_slug = {n.slug.lower(): n for n in networks}
    seen_external_ids: set[tuple[str, str]] = set()
    seen_titles: set[tuple[str, str]] = set()

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in rows:
        row_number = int(item.get("row_number") or 0)
        raw_data = item.get("data") or {}
        data, status, errors, _ = validate_offer_row(
            db,
            raw=raw_data,
            networks_by_slug=networks_by_slug,
            seen_external_ids=seen_external_ids,
            seen_titles=seen_titles,
        )
        if status != "valid":
            reason = "; ".join(errors) if errors else status
            skipped.append({"row_number": row_number, "reason": reason})
            continue

        network = networks_by_slug[data["network"] or ""]
        offer = Offer(
            network_id=network.id,
            external_offer_id=data["external_offer_id"],
            title=data["title"] or "",
            niche=data["niche"],
            vendor_name=data["vendor_name"],
            offer_url=data["offer_url"],
            affiliate_resources_url=data["affiliate_resources_url"],
            notes=data["notes"],
        )
        db.add(offer)
        db.flush()
        created.append({"row_number": row_number, "offer_id": str(offer.id)})

    db.add(
        AuditEvent(
            user_id=user.id,
            action="offers.csv_import",
            entity_type="offer",
            entity_id=None,
            metadata_json={"created_count": len(created), "skipped_count": len(skipped)},
        )
    )
    db.commit()
    return {"created": created, "skipped": skipped}
