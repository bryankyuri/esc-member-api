import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import Response

from app.config import get_settings

SESSION_COOKIE = "esc_session"


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_expiry() -> datetime:
    return datetime.utcnow() + timedelta(days=get_settings().session_ttl_days)


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 24 * 3600,
        domain=settings.cookie_domain or None,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE,
        domain=settings.cookie_domain or None,
        path="/",
    )
