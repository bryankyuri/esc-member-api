from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import api_error, effective_role, get_current_user
from app.models import AuthSession, User
from app.schemas import (
    CompleteProfileIn,
    SecurityAnswerIn,
    SecurityResultOut,
    UpdateProfileIn,
    UserOut,
)
from app.security import (
    SESSION_COOKIE,
    clear_session_cookie,
    hash_token,
    new_session_token,
    session_expiry,
    set_session_cookie,
)
from app.services import now_local, user_out

router = APIRouter(prefix="/auth", tags=["auth"])

# Membership proof gate. Not a real secret (it's club trivia) — just enough to
# stop a random Google account completing registration. Answer is compared
# case-insensitively with collapsed whitespace.
SECURITY_ANSWER = "endah widiastuti"
MAX_SECURITY_ATTEMPTS = 10


def _normalize(s: str) -> str:
    return " ".join(s.strip().lower().split())

oauth = OAuth()
oauth.register(
    "google",
    client_id=get_settings().google_client_id,
    client_secret=get_settings().google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


@router.get("/google/login")
async def google_login(request: Request, next: str = "member"):
    # Remember which frontend started the flow so the callback can return there.
    request.session["login_next"] = "dashboard" if next == "dashboard" else "member"
    redirect_uri = f"{get_settings().api_base_url}/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    next_app = request.session.pop("login_next", "member")
    frontend = (
        settings.dashboard_frontend_url
        if next_app == "dashboard"
        else settings.member_frontend_url
    )

    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse(f"{frontend}/login?error=oauth")

    info = token.get("userinfo") or {}
    sub = info.get("sub")
    email = (info.get("email") or "").lower()
    if not sub or not email or not info.get("email_verified", False):
        return RedirectResponse(f"{frontend}/login?error=oauth")

    user = db.query(User).filter(User.google_sub == sub).first()
    if user is None:
        # Link by verified email if the account pre-exists (e.g. imported).
        user = db.query(User).filter(User.email == email).first()
        if user is not None:
            user.google_sub = sub
    if user is None:
        user = User(
            google_sub=sub,
            email=email,
            full_name=info.get("name") or email.split("@")[0],
            avatar_url=info.get("picture"),
            role="member",
            profile_completed=False,
        )
        db.add(user)
    else:
        user.avatar_url = info.get("picture") or user.avatar_url
    db.flush()

    if not user.is_active:
        db.commit()
        return RedirectResponse(f"{frontend}/login?error=inactive")

    raw_token = new_session_token()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=session_expiry(),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:250],
        )
    )
    db.commit()

    response = RedirectResponse(frontend)
    set_session_cookie(response, raw_token)
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user_out(user, effective_role(user))


@router.post("/security-question", response_model=SecurityResultOut)
def security_question(
    payload: SecurityAnswerIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.security_passed:
        return {"passed": True, "blocked": False, "attempts_left": MAX_SECURITY_ATTEMPTS}

    today = now_local(db).strftime("%Y-%m-%d")
    if user.security_attempt_date != today:
        user.security_attempt_date = today
        user.security_attempts = 0

    if user.security_attempts >= MAX_SECURITY_ATTEMPTS:
        db.commit()
        return {"passed": False, "blocked": True, "attempts_left": 0}

    if _normalize(payload.answer) == SECURITY_ANSWER:
        user.security_passed = True
        db.commit()
        return {
            "passed": True,
            "blocked": False,
            "attempts_left": MAX_SECURITY_ATTEMPTS - user.security_attempts,
        }

    user.security_attempts += 1
    blocked = user.security_attempts >= MAX_SECURITY_ATTEMPTS
    db.commit()
    return {
        "passed": False,
        "blocked": blocked,
        "attempts_left": MAX_SECURITY_ATTEMPTS - user.security_attempts,
    }


@router.post("/complete-profile", response_model=UserOut)
def complete_profile(
    payload: CompleteProfileIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Can't complete registration without passing the membership gate first.
    if not user.security_passed:
        raise api_error(403, "security_required")
    user.full_name = payload.full_name.strip()
    user.whatsapp = payload.whatsapp.strip()
    user.domicile = payload.domicile.strip()
    user.instagram = payload.instagram.strip().lstrip("@")
    user.profile_completed = True
    db.commit()
    return user_out(user, effective_role(user))


@router.patch("/profile", response_model=UserOut)
def update_profile(
    payload: UpdateProfileIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
    if payload.whatsapp is not None:
        user.whatsapp = payload.whatsapp.strip()
    if payload.domicile is not None:
        user.domicile = payload.domicile.strip()
    if payload.instagram is not None:
        user.instagram = payload.instagram.strip().lstrip("@")
    db.commit()
    return user_out(user, effective_role(user))


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.query(AuthSession).filter(
            AuthSession.token_hash == hash_token(token)
        ).delete()
        db.commit()
    clear_session_cookie(response)
