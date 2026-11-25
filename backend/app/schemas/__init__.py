"""Pydantic request/response schemas matching docs/api.md."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ApprovalState = Literal["unknown", "requested", "approved", "denied", "revoked"]
SourceType = Literal["affiliate_page", "offer_page", "asset_url", "other"]
AccessState = Literal["unverified", "authorized", "restricted", "approval_required", "forbidden"]
ReviewState = Literal["pending", "needs_changes", "approved", "rejected", "archived"]
BulkAction = Literal["add_tags", "archive"]
DraftEditableStatus = Literal["editing", "archived"]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: str
    email: str
    role: str


class LoginResponse(BaseModel):
    user: UserOut


class NetworkOut(BaseModel):
    id: str
    slug: str
    name: str
    enabled: bool


class OfferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network_slug: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    external_offer_id: str | None = Field(default=None, max_length=200)
    niche: str | None = Field(default=None, max_length=200)
    vendor_name: str | None = Field(default=None, max_length=300)
    offer_url: str | None = None
    affiliate_resources_url: str | None = None
    notes: str | None = None


class OfferUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network_slug: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    external_offer_id: str | None = Field(default=None, max_length=200)
    niche: str | None = Field(default=None, max_length=200)
    vendor_name: str | None = Field(default=None, max_length=300)
    offer_url: str | None = None
    affiliate_resources_url: str | None = None
    notes: str | None = None
    metrics_json: dict[str, Any] | None = None
    metrics_source: str | None = Field(default=None, max_length=300)
    metrics_as_of: datetime | None = None
    last_verified_at: datetime | None = None


class ApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ApprovalState
    notes: str | None = None


class CsvCommitRow(BaseModel):
    row_number: int
    data: dict[str, str | None]


class CsvCommitRequest(BaseModel):
    rows: list[CsvCommitRow]


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    source_type: SourceType = "affiliate_page"
    access_state: AccessState = "unverified"
    permission_notes: str | None = None
    allowed_hosts: list[str] = Field(default_factory=list)


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: SourceType | None = None
    access_state: AccessState | None = None
    permission_notes: str | None = None
    allowed_hosts: list[str] | None = None


class SourceScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_authorized: bool = False


class SwipeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class SwipeReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    decision: ReviewState
    notes: str | None = None


class SwipeTagsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[str]


class SwipeBulkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    swipe_ids: list[str] = Field(min_length=1)
    action: BulkAction
    tags: list[str] | None = None


class BrandCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    sender_identity_ref: str | None = Field(default=None, max_length=300)
    affiliate_settings_json: dict[str, Any] = Field(default_factory=dict)
    disclosure_text: str = ""
    footer_template: str = ""
    integration_ref: str | None = Field(default=None, max_length=200)


class BrandUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    sender_identity_ref: str | None = Field(default=None, max_length=300)
    affiliate_settings_json: dict[str, Any] | None = None
    disclosure_text: str | None = None
    footer_template: str | None = None
    integration_ref: str | None = Field(default=None, max_length=200)


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    swipe_id: str
    brand_id: str
    subject_position: int | None = None
    affiliate_url: str | None = None
    replace_urls: list[str] = Field(default_factory=list)
    sequence_position: int | None = Field(default=None, ge=1)
    suggested_day_offset: int | None = Field(default=None, ge=0)


class DraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    subject: str | None = Field(default=None, min_length=1)
    preheader: str | None = None
    body_text: str | None = None
    body_html: str | None = None
    affiliate_url: str | None = None
    replace_placeholders: bool = False
    replace_urls: list[str] = Field(default_factory=list)
    append_brand_footer: bool = False
    sequence_position: int | None = Field(default=None, ge=1)
    suggested_day_offset: int | None = Field(default=None, ge=0)
    status: DraftEditableStatus | None = None


class DraftApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class ListmonkExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list_ids: list[int] = Field(default_factory=list)
    confirm_unsent_draft: bool = False
