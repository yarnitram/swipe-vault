"""Pydantic request/response schemas matching docs/api.md."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ApprovalState = Literal["unknown", "requested", "approved", "denied", "revoked"]
SourceType = Literal["affiliate_page", "offer_page", "asset_url", "other"]
AccessState = Literal["unverified", "authorized", "restricted", "approval_required", "forbidden"]
ReviewState = Literal["pending", "needs_changes", "approved", "rejected", "archived"]
BulkAction = Literal["add_tags", "archive"]


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
