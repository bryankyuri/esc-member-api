"""Certificate issuing: completion check, codes, and the public view.

The server decides whether a course is finished — never the client. A
certificate is something people show to others, so "I completed it" arriving
in a request body is not evidence.

Since Phase 5 the course tables are the source of truth for what a course
contains; the generated `courses_manifest.json` and the script that kept it in
step with the frontend JSON are gone.
"""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.courses import course_item_ids
from app.courses import course_title as db_course_title
from app.models import Certificate, LearningProgress, User

# No 0/O/1/I/L: the code gets read aloud and typed by hand.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_RANDOM_LEN = 5


def course_items(db: Session, course_slug: str) -> list[str]:
    """Item ids that make up a course; empty when the course is unknown."""
    return course_item_ids(db, course_slug)


def course_title(db: Session, course_slug: str, lang: str = "id") -> str:
    return db_course_title(db, course_slug, lang)


def missing_items(db: Session, user: User, course_slug: str) -> list[str]:
    """Which items of the course this user has *not* completed."""
    required = course_items(db, course_slug)
    if not required:
        return []
    done = {
        row.item_id
        for row in db.query(LearningProgress).filter(
            LearningProgress.user_id == user.id,
            LearningProgress.course_slug == course_slug,
        )
    }
    return [item for item in required if item not in done]


def course_prefix(course_slug: str) -> str:
    """Three letters from the slug, for a readable code: ESC-MEN-7K3F9."""
    letters = "".join(ch for ch in course_slug.upper() if ch.isalpha())
    return (letters[:3] or "ESC").ljust(3, "X")


def new_code(db: Session, course_slug: str) -> str:
    prefix = course_prefix(course_slug)
    for _ in range(20):
        suffix = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_RANDOM_LEN))
        code = f"ESC-{prefix}-{suffix}"
        if db.query(Certificate).filter(Certificate.code == code).first() is None:
            return code
    # 31^5 ≈ 28.6M per course; twenty collisions in a row means something is
    # badly wrong, and silently issuing a duplicate would be worse.
    raise RuntimeError("could not allocate a unique certificate code")


def certificate_out(db: Session, cert: Certificate, lang: str = "id") -> dict:
    """The holder's own view — includes the email printed on their copy."""
    return {
        "code": cert.code,
        "course_slug": cert.course_slug,
        "course_title": course_title(db, cert.course_slug, lang),
        "first_name": cert.first_name_snapshot,
        "last_name": cert.last_name_snapshot,
        "email": cert.email_snapshot,
        "issued_at": cert.issued_at.isoformat(),
        "revoked": cert.revoked_at is not None,
    }


def verification_out(db: Session, cert: Certificate, lang: str = "id") -> dict:
    """The public view: enough to confirm it is real, and nothing more.

    Deliberately **no email**. Printing an address on the holder's own copy is
    fine; publishing it on a page anyone can open is not.
    """
    return {
        "code": cert.code,
        "holder_name": f"{cert.first_name_snapshot} {cert.last_name_snapshot}".strip(),
        "course_title": course_title(db, cert.course_slug, lang),
        "issued_at": cert.issued_at.isoformat(),
        "valid": cert.revoked_at is None,
    }
