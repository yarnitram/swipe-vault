"""Session authentication, double-submit CSRF verification, login rate limiting, and admin bootstrap."""

import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from datetime import timedelta
from threading import Lock

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import AuditEvent, User, UserSession, utcnow
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.settings import get_settings

SESSION_COOKIE = "sv_session"
CSRF_COOKIE = "sv_csrf"
CSRF_HEADER = "x-csrf-token"

_rate_lock = Lock()
_login_attempts: dict[str, list[float]] = defaultdict(list)


def reset_login_rate_limits() -> None:
    with _rate_lock:
        _login_attempts.clear()


def check_login_rate_limit(key: str) -> None:
    settings = get_settings()
    now = time.monotonic()
    cutoff = now - settings.login_window_seconds
    with _rate_lock:
        recent = [ts for ts in _login_attempts[key] if ts > cutoff]
        _login_attempts[key] = recent
        if len(recent) >= settings.login_max_attempts:
            raise ApiError(429, "rate_limited", "Too many login attempts; please wait before retrying")


def record_failed_login(key: str) -> None:
    with _rate_lock:
        _login_attempts[key].append(time.monotonic())


def clear_failed_logins(key: str) -> None:
    with _rate_lock:
        _login_attempts.pop(key, None)


def _hash_token(raw_token: str) -> str:
    secret = get_settings().session_secret.encode("utf-8")
    return hmac.new(secret, raw_token.encode("utf-8"), hashlib.sha256).hexdigest()


def create_user_session(db: Session, user: User, response: Response) -> str:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    expires_at = utcnow() + timedelta(hours=settings.session_ttl_hours)

    sess = UserSession(
        token_hash=_hash_token(raw_token),
        user_id=user.id,
        expires_at=expires_at,
    )
    db.add(sess)
    db.add(
        AuditEvent(
            user_id=user.id,
            action="auth.login",
            entity_type="user",
            entity_id=str(user.id),
            metadata_json={"email": user.email},
        )
    )
    db.commit()

    max_age = settings.session_ttl_hours * 3600
    secure = settings.session_cookie_secure or settings.is_production
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE,
        value=csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    return csrf_token


def clear_user_session(db: Session, request: Request, response: Response) -> None:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        token_hash = _hash_token(raw_token)
        sess = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
        if sess is not None:
            db.delete(sess)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise ApiError(401, "not_authenticated", "Authentication required")
    token_hash = _hash_token(raw_token)
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    if sess is None or sess.expires_at <= utcnow():
        if sess is not None:
            db.delete(sess)
            db.commit()
        raise ApiError(401, "not_authenticated", "Session expired or invalid")

    user = sess.user
    if user is None or not user.active:
        raise ApiError(401, "not_authenticated", "User account is inactive")

    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        cookie_csrf = request.cookies.get(CSRF_COOKIE) or ""
        header_csrf = request.headers.get(CSRF_HEADER) or ""
        if not cookie_csrf or not header_csrf or not secrets.compare_digest(cookie_csrf, header_csrf):
            raise ApiError(403, "csrf_failed", "Missing or invalid CSRF token")

    return user


def authenticate_user(db: Session, email: str, password: str, client_key: str) -> User:
    norm_email = email.strip().lower()
    rate_key = f"{client_key}:{norm_email}"
    check_login_rate_limit(rate_key)
    check_login_rate_limit(client_key)

    user = db.scalar(select(User).where(User.email == norm_email))
    stored_hash = user.password_hash if user is not None else None
    if not verify_password(stored_hash, password) or user is None or not user.active:
        record_failed_login(rate_key)
        record_failed_login(client_key)
        raise ApiError(401, "invalid_credentials", "Invalid email or password")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()

    clear_failed_logins(rate_key)
    clear_failed_logins(client_key)
    return user


def ensure_bootstrap_admin(db: Session) -> User | None:
    """Create the initial operator account if BOOTSTRAP_ADMIN_EMAIL/PASSWORD are configured."""
    settings = get_settings()
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        return None
    email = settings.bootstrap_admin_email.strip().lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        return existing
    user = User(
        email=email,
        password_hash=hash_password(settings.bootstrap_admin_password),
        role="admin",
        active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
