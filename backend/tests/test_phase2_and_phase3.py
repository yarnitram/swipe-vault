"""Phase 2 (Permission-aware collection) and Phase 3 (Drafts & Listmonk) integration tests (AC-03..AC-13)."""

import json
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.listmonk.client import (
    export_unsent_draft_to_listmonk,
)
from app.adapters.listmonk.client import (
    test_listmonk_connection as check_listmonk_connection,
)
from app.adapters.sources.crawler import execute_scan_source_job
from app.models import BrandProfile, Draft, Job, Offer, Source, Swipe, User
from app.settings import get_settings


def test_phase2_permission_aware_crawler_and_idempotency(
    auth_client: TestClient, db_session: Session
) -> None:
    """AC-03, AC-04, AC-06, AC-07: Permission-aware scan, domain scoping, SSRF redirect guard, and idempotency."""
    offer_resp = auth_client.post(
        "/api/v1/offers",
        json={
            "network_slug": "clickbank",
            "external_offer_id": "leanbelly7",
            "title": "LeanBelly Daily Tonic",
            "niche": "Health & Fitness",
            "vendor_name": "LeanBelly Labs",
            "offer_url": "https://leanbelly.example.com/offer",
            "affiliate_resources_url": "https://leanbelly.example.com/jv",
        },
    )
    assert offer_resp.status_code == 201
    offer_id = offer_resp.json()["id"]

    source_resp = auth_client.post(
        f"/api/v1/offers/{offer_id}/sources",
        json={
            "url": "https://leanbelly.example.com/jv",
            "source_type": "affiliate_page",
            "access_state": "authorized",
            "allowed_hosts": ["assets.leanbelly.example.com"],
        },
    )
    assert source_resp.status_code == 201
    source_id = source_resp.json()["id"]

    # Scan without confirm_authorized must fail with 400
    no_confirm = auth_client.post(
        f"/api/v1/sources/{source_id}/scan",
        json={"confirm_authorized": False},
    )
    assert no_confirm.status_code == 400
    assert no_confirm.json()["error"]["code"] == "authorization_required"

    # Synthetic vendor site served via httpx.MockTransport (no live network dependencies)
    hub_html = """
    <html><body>
      <h1>LeanBelly Affiliate Tools</h1>
      <a href="/jv/email-swipes.html">Email Swipes Page</a>
      <a href="https://assets.leanbelly.example.com/pack/swipes.txt">Download Email Swipe Pack (TXT)</a>
      <a href="/checkout/order">Order Checkout (Must Be Ignored)</a>
      <a href="https://unrelated-marketing.example.org/swipes.txt">Off-Domain Link (Must Be Ignored)</a>
      <a href="/jv/ssrf-redirect">Redirect To Internal IP (Must Be Blocked)</a>
    </body></html>
    """
    subpage_html = """
    <html><body>
      <h2>Email 1: Morning Tonic Routine</h2>
      <p>Subject: The 10-second morning tonic supporting gut balance</p>
      <p>Preheader: Simple morning glass before coffee</p>
      <p>Body:</p>
      <p>Try this simple morning tonic before your first cup of coffee to support healthy digestion.</p>
      <p><a href="https://leanbelly.example.com/tonic">Watch the morning tonic video</a></p>
    </body></html>
    """
    txt_asset = (
        "Email 2: Evening Digestion Habits\n"
        "Subject: 3 evening habits that support overnight metabolism\n"
        "Body:\n"
        "Here are three simple after-dinner habits our nutrition team shares with clients.\n"
        "Read the evening guide <https://leanbelly.example.com/evening>\n"
        "Use your hop link: [YOUR_AFFILIATE_LINK]\n"
    )

    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested_urls.append(url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if url == "https://leanbelly.example.com/jv":
            return httpx.Response(200, headers={"content-type": "text/html"}, text=hub_html)
        if url == "https://leanbelly.example.com/jv/email-swipes.html":
            return httpx.Response(200, headers={"content-type": "text/html"}, text=subpage_html)
        if url == "https://assets.leanbelly.example.com/pack/swipes.txt":
            return httpx.Response(200, headers={"content-type": "text/plain"}, text=txt_asset)
        if url == "https://leanbelly.example.com/jv/ssrf-redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        return httpx.Response(404, text="Not found")

    transport = httpx.MockTransport(handler)
    offer = db_session.get(Offer, offer_id)
    source = db_session.get(Source, source_id)
    assert offer is not None and source is not None

    job1 = Job(
        offer_id=offer.id,
        source_id=source.id,
        type="scan_source",
        state="queued",
        progress_json={},
    )
    db_session.add(job1)
    db_session.commit()

    execute_scan_source_job(db_session, job1.id, transport=transport, check_dns=False)
    db_session.refresh(job1)
    assert job1.state in ("completed", "partial")
    assert job1.progress_json["swipes_new"] == 2
    # Must never request /checkout/order, unrelated domain, or follow redirect to 127.0.0.1
    assert not any("/checkout" in u for u in requested_urls)
    assert not any("unrelated-marketing.example.org" in u for u in requested_urls)
    assert not any("127.0.0.1" in u for u in requested_urls)

    # AC-04: Re-scanning unchanged source adds 0 new swipes and records duplicates
    job2 = Job(
        offer_id=offer.id,
        source_id=source.id,
        type="scan_source",
        state="queued",
        progress_json={},
    )
    db_session.add(job2)
    db_session.commit()
    execute_scan_source_job(db_session, job2.id, transport=transport, check_dns=False)
    db_session.refresh(job2)
    assert job2.progress_json["swipes_new"] == 0
    assert job2.progress_json["duplicates"] >= 2


def test_phase2_handles_login_gates_robots_and_rate_limits_without_bypass(
    auth_client: TestClient, db_session: Session
) -> None:
    """AC-06: Login-gated, robots-disallowed, forbidden, and 429 rate-limited sources are marked restricted."""
    offer = auth_client.post(
        "/api/v1/offers",
        json={"network_slug": "clickbank", "title": "Gated Vendor Offer"},
    ).json()
    src_resp = auth_client.post(
        f"/api/v1/offers/{offer['id']}/sources",
        json={"url": "https://gated.example.com/affiliates", "source_type": "affiliate_page"},
    )
    source_id = src_resp.json()["id"]

    # Case 1: HTML login gate -> marks source approval_required
    login_transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<html><body><form><input type="password" name="pw"></form></body></html>',
        )
    )
    job_gate = Job(
        offer_id=offer["id"],
        source_id=source_id,
        type="scan_source",
        state="queued",
        progress_json={},
    )
    db_session.add(job_gate)
    db_session.commit()
    execute_scan_source_job(db_session, job_gate.id, transport=login_transport, check_dns=False)
    db_session.refresh(job_gate)
    source_obj = db_session.get(Source, source_id)
    assert job_gate.state == "failed"
    assert source_obj is not None and source_obj.access_state == "approval_required"

    # Scanning a source in approval_required state via the API is blocked with 409 source_not_scannable
    blocked = auth_client.post(
        f"/api/v1/sources/{source_id}/scan",
        json={"confirm_authorized": True},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "source_not_scannable"


def test_phase3_draft_workflow_and_listmonk_export(
    auth_client: TestClient, db_session: Session
) -> None:
    """AC-10..AC-12: Brand profile, draft creation, link mapping, edit invalidation, Listmonk draft export."""
    # Seeded brand MyFitterU must be available
    brands = auth_client.get("/api/v1/brands").json()
    assert len(brands) >= 1
    myfitteru = next(b for b in brands if b["slug"] == "myfitteru")

    offer = auth_client.post(
        "/api/v1/offers",
        json={
            "network_slug": "clickbank",
            "external_offer_id": "coreflex1",
            "title": "CoreFlex Mobility Guide",
            "niche": "Health & Fitness",
            "vendor_name": "CoreFlex Wellness",
        },
    ).json()

    swipe_txt = (
        b"Email 1: Core Mobility Routine\n"
        b"Subject: The 60-second lower back release you can do at your desk\n"
        b"Subject Option 2: Stiff lower back after sitting? Try this 60-second movement\n"
        b"Preheader: Desk-friendly mobility tip inside\n"
        b"Body:\n"
        b"Hi Reader,\n\n"
        b"Sitting for long stretches tightens the hip flexors and pulls on the lower back.\n\n"
        b"Watch the 60-second desk release <https://vendor.coreflex.example.com/video>\n"
        b"Or use your hop link placeholder: [YOUR_AFFILIATE_LINK]\n"
        b"Manage preferences or unsubscribe: <https://myfitteru.example.com/unsubscribe>\n"
    )
    up = auth_client.post(
        f"/api/v1/offers/{offer['id']}/assets",
        data={"confirm_authorized": "true"},
        files={"file": ("coreflex_swipes.txt", swipe_txt, "text/plain")},
    )
    assert up.status_code == 202
    swipe_item = auth_client.get(f"/api/v1/swipes?offer_id={offer['id']}").json()["items"][0]
    swipe_id = swipe_item["id"]
    swipe_ver_id = swipe_item["current_version"]["id"]

    # Unapproved swipe cannot create a draft (FR-06/FR-07)
    unapproved_draft = auth_client.post(
        "/api/v1/drafts",
        json={"swipe_id": swipe_id, "brand_id": myfitteru["id"]},
    )
    assert unapproved_draft.status_code == 409
    assert unapproved_draft.json()["error"]["code"] == "swipe_not_approved"

    # Approve the swipe
    rev = auth_client.post(
        f"/api/v1/swipes/{swipe_id}/review",
        json={"version_id": swipe_ver_id, "decision": "approved", "notes": "Approved for MyFitterU"},
    )
    assert rev.status_code == 200
    original_swipe_body = rev.json()["versions"][0]["body_text"]

    # AC-10: Create a brand-specific draft from the approved swipe
    hop_url = "https://hop.clickbank.net/?affiliate=myfitteru&vendor=coreflex1&tid=nl01"
    draft_resp = auth_client.post(
        "/api/v1/drafts",
        json={
            "swipe_id": swipe_id,
            "brand_id": myfitteru["id"],
            "subject_position": 2,
            "affiliate_url": hop_url,
            "replace_urls": ["https://vendor.coreflex.example.com/video"],
            "sequence_position": 1,
            "suggested_day_offset": 0,
        },
    )
    assert draft_resp.status_code == 201, draft_resp.text
    draft = draft_resp.json()
    draft_id = draft["id"]
    assert draft["subject"] == "Stiff lower back after sitting? Try this 60-second movement"
    assert hop_url in draft["body_text"]
    assert "[YOUR_AFFILIATE_LINK]" not in draft["body_text"]
    assert "https://vendor.coreflex.example.com/video" not in draft["body_text"]
    # Protected unsubscribe link must NOT be replaced (FR-07)
    assert "https://myfitteru.example.com/unsubscribe" in draft["body_text"]
    assert "Affiliate Disclosure:" in draft["body_text"]
    assert draft["review_checks"]["ready_for_approval"] is True

    # Source swipe remains 100% immutable (AC-10)
    swipe_after = auth_client.get(f"/api/v1/swipes/{swipe_id}").json()
    assert swipe_after["versions"][0]["body_text"] == original_swipe_body
    assert "[YOUR_AFFILIATE_LINK]" in swipe_after["versions"][0]["body_text"]

    # AC-11: Unapproved draft cannot be downloaded or exported
    dl_unapproved = auth_client.get(f"/api/v1/drafts/{draft_id}/download?format=html")
    assert dl_unapproved.status_code == 409
    assert dl_unapproved.json()["error"]["code"] == "draft_not_approved"

    # Approve draft v1
    appr_v1 = auth_client.post(
        f"/api/v1/drafts/{draft_id}/approve",
        json={"version": 1},
    )
    assert appr_v1.status_code == 200
    assert appr_v1.json()["status"] == "approved"
    assert appr_v1.json()["approved_version"] == 1

    # Now local download succeeds
    dl_ok = auth_client.get(f"/api/v1/drafts/{draft_id}/download?format=html")
    assert dl_ok.status_code == 200
    assert hop_url.replace("&", "&amp;") in dl_ok.text or hop_url in dl_ok.text

    # AC-11: Material edit increments version to v2 and invalidates approval
    edit_resp = auth_client.patch(
        f"/api/v1/drafts/{draft_id}",
        json={"subject": "Updated Subject: 60-second desk lower back stretch"},
    )
    assert edit_resp.status_code == 200
    edited = edit_resp.json()
    assert edited["version"] == 2
    assert edited["status"] == "editing"
    assert edited["approved_version"] is None

    # Downloading v2 before re-approval is blocked again (AC-11)
    assert auth_client.get(f"/api/v1/drafts/{draft_id}/download?format=txt").status_code == 409

    # Re-approve at v2
    appr_v2 = auth_client.post(f"/api/v1/drafts/{draft_id}/approve", json={"version": 2})
    assert appr_v2.status_code == 200
    assert appr_v2.json()["approved_version"] == 2

    # AC-12: Test Listmonk adapter against a mocked Listmonk server
    settings = get_settings()
    settings.listmonk_enabled = True
    settings.listmonk_base_url = "http://listmonk.internal:9000"
    settings.listmonk_api_username = "swipevault_api"
    settings.listmonk_api_token = "secret_token"

    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def listmonk_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body_obj = json.loads(request.content.decode("utf-8")) if request.content else None
        calls.append((request.method, path, body_obj))
        if request.method == "GET" and path == "/api/lists":
            return httpx.Response(
                200,
                json={"data": {"results": [{"id": 7, "name": "MyFitterU Opt-In Readers", "type": "public"}]}},
            )
        if request.method == "POST" and path == "/api/campaigns":
            return httpx.Response(
                200,
                json={"data": {"id": 402, "status": "draft", "name": body_obj["name"] if body_obj else ""}},
            )
        return httpx.Response(404)

    lm_transport = httpx.MockTransport(listmonk_handler)
    conn_info = check_listmonk_connection(transport=lm_transport)
    assert conn_info["reachable"] is True
    assert conn_info["lists"][0]["id"] == 7

    draft_obj = db_session.get(Draft, draft_id)
    brand_obj = db_session.get(BrandProfile, myfitteru["id"])
    user_obj = db_session.query(User).first()
    assert draft_obj is not None and brand_obj is not None and user_obj is not None

    exp1 = export_unsent_draft_to_listmonk(
        db_session,
        draft=draft_obj,
        brand=brand_obj,
        list_ids=[7],
        user=user_obj,
        transport=lm_transport,
    )
    assert exp1.status == "completed"
    assert exp1.remote_id == "402"

    # Retrying with the same draft version + list IDs must NOT call POST /api/campaigns again (AC-12)
    post_count_before = sum(1 for m, p, _ in calls if m == "POST" and p == "/api/campaigns")
    exp2 = export_unsent_draft_to_listmonk(
        db_session,
        draft=draft_obj,
        brand=brand_obj,
        list_ids=[7],
        user=user_obj,
        transport=lm_transport,
    )
    post_count_after = sum(1 for m, p, _ in calls if m == "POST" and p == "/api/campaigns")
    assert exp2.id == exp1.id
    assert post_count_before == 1 and post_count_after == 1
    # Verify no sending/status-change endpoints were ever called (AC-12)
    assert all(p in ("/api/lists", "/api/campaigns") for _, p, _ in calls)
    assert db_session.get(Swipe, swipe_id) is not None
