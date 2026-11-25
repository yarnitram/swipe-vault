"""Pytest fixtures for SwipeVault backend tests."""

import io
import os
import zipfile
from collections.abc import Iterator
from pathlib import Path

import docx
import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from alembic.config import Config
from app.auth import CSRF_COOKIE, reset_login_rate_limits
from app.db import get_engine, get_sessionmaker
from app.main import create_app
from app.settings import get_settings


@pytest.fixture(scope="session", autouse=True)
def configure_test_env(tmp_path_factory: pytest.TempPathFactory) -> None:
    storage_dir = tmp_path_factory.mktemp("assets")
    os.environ["ASSET_STORAGE_PATH"] = str(storage_dir)
    os.environ["INGEST_INLINE"] = "true"
    os.environ["BOOTSTRAP_ADMIN_EMAIL"] = "admin@swipevault.test"
    os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "TestPassword-Strong-2026!"
    os.environ["SESSION_SECRET"] = "test-only-session-secret-key-64bytes"
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()

    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    reset_login_rate_limits()
    session_factory = get_sessionmaker()
    with session_factory() as db:
        db.execute(
            text(
                "TRUNCATE TABLE audit_events, job_events, jobs, review_events, swipe_tags, tags, "
                "swipe_provenance, subject_variants, swipe_versions, swipes, asset_sources, assets, "
                "sources, offer_approvals, offers, sessions RESTART IDENTITY CASCADE"
            )
        )
        db.commit()
    yield


@pytest.fixture()
def db_session() -> Iterator[Session]:
    session_factory = get_sessionmaker()
    with session_factory() as db:
        yield db


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as tc:
        yield tc


@pytest.fixture()
def auth_client(client: TestClient) -> TestClient:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@swipevault.test", "password": "TestPassword-Strong-2026!"},
    )
    assert resp.status_code == 200, resp.text
    csrf = client.cookies.get(CSRF_COOKIE)
    assert csrf
    client.headers["X-CSRF-Token"] = csrf
    return client


def make_pdf_bytes(text_pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for page_text in text_pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(36, 36, 550, 780), page_text, fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


def make_docx_bytes(paragraphs: list[str]) -> bytes:
    document = docx.Document()
    for para in paragraphs:
        document.add_paragraph(para)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def make_zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()
