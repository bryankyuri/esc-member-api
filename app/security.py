import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Response

from app.config import get_settings

SESSION_COOKIE = "esc_session"


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_expiry() -> datetime:
    # Naive UTC, matching how expires_at is compared in deps.get_current_user.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now + timedelta(days=get_settings().session_ttl_days)


def purge_expired_sessions(db) -> int:
    """Delete session rows that are past their expiry.

    They are already rejected on use; this just stops the table growing for
    ever. Called at startup — cheap, and there is no scheduler here.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    from app.models import AuthSession  # imported here to avoid a cycle

    removed = (
        db.query(AuthSession).filter(AuthSession.expires_at < now).delete()
    )
    db.commit()
    return removed


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
