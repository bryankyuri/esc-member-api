from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AuthSession, User
from app.security import SESSION_COOKIE, hash_token

# What a role may manage. Membership (below) is a separate question: it decides
# access to the member area, not to anything in the dashboard.
ROLE_ORDER = {"user": 0, "contributor": 1, "admin": 2, "superadmin": 3}
STORED_ROLES = ("user", "contributor", "admin")


def api_error(status: int, code: str, message: str = "") -> HTTPException:
    """Error shape the frontends read: body.detail.code / .message."""
    return HTTPException(status, detail={"code": code, "message": message or code})


def effective_role(user: User) -> str:
    """DB role with the env-defined superadmin overlay applied."""
    if user.email.lower() in get_settings().superadmin_list:
        return "superadmin"
    return user.role


def is_member(user: User) -> bool:
    """Membership = passed the club question AND completed the member profile.

    Derived, never stored, and independent of role: an admin who never answered
    the question is not a member and cannot check in.
    """
    return bool(user.security_passed and user.profile_completed)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise api_error(401, "unauthorized")
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == hash_token(token))
        .first()
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if session is None or session.expires_at < now:
        raise api_error(401, "unauthorized")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise api_error(401, "unauthorized")
    return user


def require_member(user: User = Depends(get_current_user)) -> User:
    """Member-area access: the club question and the member profile."""
    if not user.security_passed:
        raise api_error(403, "security_required")
    if not user.profile_completed:
        raise api_error(403, "profile_incomplete")
    return user


def _require_at_least(user: User, role: str) -> User:
    if ROLE_ORDER.get(effective_role(user), -1) < ROLE_ORDER[role]:
        raise api_error(403, "forbidden")
    return user


def require_contributor(user: User = Depends(get_current_user)) -> User:
    """Articles CMS: contributor, admin or superadmin."""
    return _require_at_least(user, "contributor")


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Everything else in the dashboard, and all course/lesson content."""
    return _require_at_least(user, "admin")


def require_superadmin(user: User = Depends(get_current_user)) -> User:
    """Reserved for granting and revoking admin."""
    return _require_at_least(user, "superadmin")
