"""Certificates: the learner profile, issuing, and public verification.

Open to any signed-in account. Membership is not required — finishing a course
is the only condition, which is the point: someone can find the site, learn,
and earn a certificate without ever joining the club.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.certificates import (
    certificate_out,
    course_items,
    missing_items,
    new_code,
    verification_out,
)
from app.db import get_db
from app.deps import api_error, effective_role, get_current_user
from app.models import Certificate, User
from app.schemas import (
    CertificateOut,
    CertificateVerifyOut,
    IssueCertificateIn,
    LearnerProfileIn,
    UserOut,
)
from app.services import user_out

router = APIRouter(tags=["certificates"])

# Nobody legitimately finishes five courses in an hour; this only stops a
# runaway client, and a rejected attempt never counts against it.
MAX_CERTIFICATES_PER_HOUR = 5


@router.put("/me/profile/learner", response_model=UserOut)
def update_learner_profile(
    payload: LearnerProfileIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """First and last name — everything a certificate needs from the visitor.

    Not the member profile: no WhatsApp, no address, no club question.
    """
    user.first_name = payload.first_name.strip()
    user.last_name = payload.last_name.strip()
    db.commit()
    return user_out(user, effective_role(user), db)


@router.get("/me/certificates", response_model=list[CertificateOut])
def my_certificates(
    lang: str = "id",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Certificate)
        .filter(Certificate.user_id == user.id)
        .order_by(Certificate.issued_at.desc())
        .all()
    )
    return [certificate_out(db, c, lang) for c in rows]


@router.post("/me/certificates", response_model=CertificateOut, status_code=201)
def issue_certificate(
    payload: IssueCertificateIn,
    lang: str = "id",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Issue on 100 % completion — automatic, no admin approval.

    The completion check runs here against `learning_progress`; the request
    body only names the course.
    """
    if not course_items(db, payload.course_slug):
        raise api_error(404, "unknown_course")

    # Idempotent: one certificate per (user, course). Asking again returns the
    # one they already hold rather than minting a second code.
    existing = (
        db.query(Certificate)
        .filter(
            Certificate.user_id == user.id,
            Certificate.course_slug == payload.course_slug,
        )
        .first()
    )
    if existing is not None:
        return certificate_out(db, existing, lang)

    outstanding = missing_items(db, user, payload.course_slug)
    if outstanding:
        raise api_error(
            409,
            "course_incomplete",
            f"{len(outstanding)} item(s) still to complete",
        )

    if not (user.first_name or "").strip():
        # The name is what the certificate is *for* — ask before issuing.
        raise api_error(422, "learner_profile_required")

    # Throttle by *account* and by certificates actually issued — not by IP,
    # which a whole office or campus can share, and not by request, which
    # would let a rejected attempt burn someone's allowance.
    recent = (
        db.query(Certificate)
        .filter(
            Certificate.user_id == user.id,
            Certificate.issued_at
            >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
        )
        .count()
    )
    if recent >= MAX_CERTIFICATES_PER_HOUR:
        raise api_error(429, "too_many_certificates")

    cert = Certificate(
        user_id=user.id,
        course_slug=payload.course_slug,
        code=new_code(db, payload.course_slug),
        first_name_snapshot=(user.first_name or "").strip(),
        last_name_snapshot=(user.last_name or "").strip(),
        email_snapshot=user.email,
    )
    db.add(cert)
    db.commit()
    return certificate_out(db, cert, lang)


@router.get("/certificates/{code}", response_model=CertificateVerifyOut)
def verify_certificate(
    code: str, lang: str = "id", db: Session = Depends(get_db)
):
    """Public verification — no account needed, and no email exposed.

    This is the only public endpoint that shows a person's name, so it must
    stay minimal, and the page rendering it is noindex.
    """
    cert = (
        db.query(Certificate)
        .filter(Certificate.code == code.strip().upper())
        .first()
    )
    if cert is None:
        raise api_error(404, "unknown_certificate")
    return verification_out(db, cert, lang)
