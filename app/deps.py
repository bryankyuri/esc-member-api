from datetime import datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AuthSession, User
from app.security import SESSION_COOKIE, hash_token


def api_error(status: int, code: str, message: str = "") -> HTTPException:
    """Error shape the frontends read: body.detail.code / .message."""
    return HTTPException(status, detail={"code": code, "message": message or code})


def effective_role(user: User) -> str:
    """DB role with the env-defined superadmin overlay applied."""
    if user.email.lower() in get_settings().superadmin_list:
        return "superadmin"
    return user.role


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise api_error(401, "unauthorized")
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == hash_token(token))
        .first()
    )
    if session is None or session.expires_at < datetime.utcnow():
        raise api_error(401, "unauthorized")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise api_error(401, "unauthorized")
    return user


def require_complete_profile(user: User = Depends(get_current_user)) -> User:
    if not user.profile_completed:
        raise api_error(403, "profile_incomplete")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if effective_role(user) not in ("admin", "superadmin"):
        raise api_error(403, "forbidden")
    return user
