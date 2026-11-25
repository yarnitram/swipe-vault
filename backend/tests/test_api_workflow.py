"""End-to-end API integration tests against PostgreSQL (AC-01..AC-09, AC-13, AC-14)."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Job
from app.workers.tasks import recover_interrupted_jobs
from tests.conftest import make_docx_bytes, make_pdf_bytes, make_zip_bytes

_CANDIDATE_FIXTURES = [
    Path("/app/fixtures"),
    Path(__file__).resolve().parents[2] / "fixtures",
]
FIXTURES_DIR = next((p for p in _CANDIDATE_FIXTURES if p.exists()), _CANDIDATE_FIXTURES[0])


def test_health_and_authentication_flow(client: TestClient) -> None:
    """AC-01 & Auth: Health endpoints work; unauthenticated requests are rejected; CSRF is enforced."""
    live = client.get("/api/v1/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"

    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["database"] == "ok"

    assert client.get("/api/v1/offers").status_code == 401

    bad = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@swipevault.test", "password": "wrong-password"},
    )
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_credentials"

    ok = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@swipevault.test", "password": "TestPassword-Strong-2026!"},
    )
    assert ok.status_code == 200
    assert ok.json()["user"]["email"] == "admin@swipevault.test"

    # Mutating request without X-CSRF-Token must fail with 403 csrf_failed
    no_csrf = client.post(
        "/api/v1/offers",
        json={"network_slug": "clickbank", "title": "Blocked Without CSRF"},
    )
    assert no_csrf.status_code == 403
    assert no_csrf.json()["error"]["code"] == "csrf_failed"


def test_csv_import_preview_and_commit(auth_client: TestClient) -> None:
    """AC-02: CSV preview identifies invalid rows and duplicates; committing valid rows creates offers."""
    csv_bytes = (FIXTURES_DIR / "sample_offers.csv").read_bytes()
    preview = auth_client.post(
        "/api/v1/offers/import/preview",
        files={"file": ("sample_offers.csv", csv_bytes, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["summary"] == {"total": 5, "valid": 2, "invalid": 2, "duplicates": 1}

    statuses = {row["row_number"]: row["status"] for row in payload["rows"]}
    assert statuses == {
        2: "valid",
        3: "valid",
        4: "duplicate_in_file",
        5: "invalid",
        6: "invalid",
    }

    commit = auth_client.post("/api/v1/offers/import/commit", json={"rows": payload["rows"]})
    assert commit.status_code == 200, commit.text
    result = commit.json()
    assert len(result["created"]) == 2
    assert len(result["skipped"]) == 3

    # Re-previewing the same CSV now flags the two committed offers as duplicate_existing
    preview_again = auth_client.post(
        "/api/v1/offers/import/preview",
        files={"file": ("sample_offers.csv", csv_bytes, "text/csv")},
    )
    assert preview_again.status_code == 200
    assert preview_again.json()["summary"]["duplicates"] == 3


def test_zip_ingestion_provenance_dedup_versioning_search_and_review(auth_client: TestClient) -> None:
    """AC-03, AC-04, AC-05, AC-08, AC-09: Full ingestion, provenance, dedup, versioning, search & review."""
    offer_resp = auth_client.post(
        "/api/v1/offers",
        json={
            "network_slug": "clickbank",
            "external_offer_id": "metaboost1",
            "title": "MetaBoost Metabolic Flush",
            "niche": "Health & Fitness",
            "vendor_name": "MetaBoost Wellness",
            "offer_url": "https://metaboost.example.com/offer",
            "affiliate_resources_url": "https://metaboost.example.com/affiliates",
        },
    )
    assert offer_resp.status_code == 201
    offer_id = offer_resp.json()["id"]

    # Record explicit vendor approval state
    appr = auth_client.post(
        f"/api/v1/offers/{offer_id}/approvals",
        json={"state": "approved", "notes": "Approved via vendor JV page"},
    )
    assert appr.status_code == 201

    # Add source URL and verify SSRF protection on source creation
    bad_src = auth_client.post(
        f"/api/v1/offers/{offer_id}/sources",
        json={"url": "http://192.168.1.50/private", "source_type": "affiliate_page"},
    )
    assert bad_src.status_code == 422
    assert bad_src.json()["error"]["code"] == "unsafe_url"

    good_src = auth_client.post(
        f"/api/v1/offers/{offer_id}/sources",
        json={
            "url": "https://metaboost.example.com/affiliates",
            "source_type": "affiliate_page",
            "access_state": "authorized",
            "allowed_hosts": ["cdn.metaboost.example.com"],
        },
    )
    assert good_src.status_code == 201

    # Upload without confirm_authorized must be rejected
    unconfirmed = auth_client.post(
        f"/api/v1/offers/{offer_id}/assets",
        data={"confirm_authorized": "false"},
        files={"file": ("swipes.txt", (FIXTURES_DIR / "sample_swipes.txt").read_bytes(), "text/plain")},
    )
    assert unconfirmed.status_code == 400
    assert unconfirmed.json()["error"]["code"] == "authorization_required"

    # Build a ZIP containing TXT, HTML, PDF, and DOCX resources (AC-03)
    zip_payload = make_zip_bytes(
        {
            "pack/swipes.txt": (FIXTURES_DIR / "sample_swipes.txt").read_bytes(),
            "pack/joint_promo.html": (FIXTURES_DIR / "sample_affiliate_swipes.html").read_bytes(),
            "pack/pdf_swipe.pdf": make_pdf_bytes(
                [
                    "Email 1: Hydration & Electrolytes\n"
                    "Subject: Why plain water can leave you tired by 2 PM\n"
                    "Preheader: Mineral balance guide inside\n"
                    "Body:\n"
                    "Adding a pinch of trace minerals to your morning glass supports steady hydration.\n"
                    "Read the electrolyte guide <https://metaboost.example.com/hydration>\n"
                ]
            ),
            "pack/docx_swipe.docx": make_docx_bytes(
                [
                    "Email 1: 7-Day Pantry Reset",
                    "Subject: 5 inflammatory pantry staples to swap out this week",
                    "Body:",
                    "Here are the 5 simplest kitchen swaps our coaches make on day one of the reset.",
                    "Download the pantry swap sheet <https://metaboost.example.com/pantry>",
                ]
            ),
        }
    )

    upload = auth_client.post(
        f"/api/v1/offers/{offer_id}/assets",
        data={"confirm_authorized": "true"},
        files={"file": ("metaboost_pack.zip", zip_payload, "application/zip")},
    )
    assert upload.status_code == 202, upload.text
    job_data = upload.json()["job"]
    assert job_data["state"] == "completed"
    assert job_data["progress"]["swipes_new"] == 5

    # AC-04: Re-uploading the unchanged ZIP adds no duplicate assets or swipes
    reupload = auth_client.post(
        f"/api/v1/offers/{offer_id}/assets",
        data={"confirm_authorized": "true"},
        files={"file": ("metaboost_pack.zip", zip_payload, "application/zip")},
    )
    assert reupload.status_code == 202
    assert reupload.json()["duplicate_asset"] is True

    swipes_list = auth_client.get(f"/api/v1/swipes?offer_id={offer_id}").json()
    assert swipes_list["total"] == 5

    # AC-08: Full-text search and filters
    search_resp = auth_client.get("/api/v1/swipes?q=electrolyte&network=clickbank&niche=Health+%26+Fitness")
    assert search_resp.status_code == 200
    assert search_resp.json()["total"] == 1
    assert "plain water" in (search_resp.json()["items"][0]["current_version"]["primary_subject"] or "")

    # Review a swipe from sample_swipes.txt, then upload a revised sample_swipes.txt and verify versioning (AC-05)
    morning_search = auth_client.get("/api/v1/swipes?q=15-second+morning+ritual").json()
    assert morning_search["total"] == 1
    morning_id = morning_search["items"][0]["id"]
    morning_ver1_id = morning_search["items"][0]["current_version"]["id"]

    # First upload sample_swipes.txt directly so it establishes its own file:sample_swipes.txt lineage
    direct_v1 = auth_client.post(
        f"/api/v1/offers/{offer_id}/assets",
        data={"confirm_authorized": "true"},
        files={
            "file": (
                "standalone_swipe.txt",
                (
                    b"Email 1: Digest Tea\n"
                    b"Subject: Warm ginger tea trick before dinner\n"
                    b"Body:\n"
                    b"Sip this warm ginger infusion 15 minutes before dinner to support digestion.\n"
                    b"See the recipe <https://metaboost.example.com/ginger-v1>\n"
                ),
                "text/plain",
            )
        },
    )
    assert direct_v1.status_code == 202

    tea_swipe = auth_client.get("/api/v1/swipes?q=ginger+infusion").json()["items"][0]
    tea_id = tea_swipe["id"]
    tea_v1_id = tea_swipe["current_version"]["id"]

    rev_resp = auth_client.post(
        f"/api/v1/swipes/{tea_id}/review",
        json={"version_id": tea_v1_id, "decision": "approved", "notes": "Verified v1 copy"},
    )
    assert rev_resp.status_code == 200
    assert rev_resp.json()["review_state"] == "approved"

    # Now upload a revised standalone_swipe.txt with updated subject/body (AC-05)
    direct_v2 = auth_client.post(
        f"/api/v1/offers/{offer_id}/assets",
        data={"confirm_authorized": "true"},
        files={
            "file": (
                "standalone_swipe.txt",
                (
                    b"Email 1: Digest Tea\n"
                    b"Subject: Warm ginger & lemon tea trick before dinner (Updated)\n"
                    b"Body:\n"
                    b"Sip this updated warm ginger and lemon infusion 20 minutes before dinner.\n"
                    b"See the updated recipe <https://metaboost.example.com/ginger-v2>\n"
                ),
                "text/plain",
            )
        },
    )
    assert direct_v2.status_code == 202
    assert direct_v2.json()["job"]["progress"]["versions_new"] == 1

    tea_detail = auth_client.get(f"/api/v1/swipes/{tea_id}").json()
    assert tea_detail["version_count"] == 2
    assert tea_detail["review_state"] == "pending"
    assert tea_detail["versions"][0]["version_number"] == 2
    assert tea_detail["versions"][1]["version_number"] == 1
    assert tea_detail["versions"][1]["review_events"][0]["decision"] == "approved"
    assert tea_detail["versions"][1]["review_events"][0]["notes"] == "Verified v1 copy"

    # Reviewing the stale v1 version must return 409 stale_version
    stale = auth_client.post(
        f"/api/v1/swipes/{tea_id}/review",
        json={"version_id": tea_v1_id, "decision": "approved"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_version"

    # Tagging and bulk archive
    tag_resp = auth_client.post(
        f"/api/v1/swipes/{morning_id}/tags",
        json={"tags": ["angle:metabolism", "morning-routine"]},
    )
    assert tag_resp.status_code == 200
    assert "angle:metabolism" in tag_resp.json()["tags"]

    by_tag = auth_client.get("/api/v1/swipes?tag=angle:metabolism").json()
    assert by_tag["total"] == 1

    # Provenance & asset download
    first_asset_id = tea_detail["versions"][0]["provenance"][0]["asset_id"]
    dl = auth_client.get(f"/api/v1/assets/{first_asset_id}/download")
    assert dl.status_code == 200
    assert b"ginger and lemon" in dl.content
    assert morning_ver1_id


def test_job_cancellation_and_worker_crash_recovery(
    auth_client: TestClient, db_session: Session
) -> None:
    """AC-13 & AC-14: Queued jobs can be cancelled; interrupted running jobs recover cleanly."""
    offer = auth_client.post(
        "/api/v1/offers",
        json={"network_slug": "clickbank", "title": "Recovery Test Offer"},
    ).json()

    upload = auth_client.post(
        f"/api/v1/offers/{offer['id']}/assets",
        data={"confirm_authorized": "true"},
        files={
            "file": (
                "recovery.txt",
                b"Email 1\nSubject: Recovery test subject\nBody:\nRecovery test body copy with link <https://recovery.example.com/a>",
                "text/plain",
            )
        },
    )
    assert upload.status_code == 202
    job_id = upload.json()["job"]["id"]

    # Simulate an interrupted running job and run worker recovery (AC-14)
    job = db_session.get(Job, job_id)
    assert job is not None
    job.state = "running"
    db_session.commit()

    recovered = recover_interrupted_jobs()
    assert recovered == 1

    job_detail = auth_client.get(f"/api/v1/jobs/{job_id}").json()
    assert job_detail["state"] == "completed"
    assert any(ev["event_type"] == "worker_recovery" for ev in job_detail["events"])
