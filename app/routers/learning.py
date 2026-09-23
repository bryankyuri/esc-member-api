"""Lesson progress and drafts, tied to the account.

Open to **any signed-in account** — `user`, contributor, admin, superadmin.
Learning is not member-area functionality: someone who found the site today can
work through a course without ever registering as an ESC member.

Reading lessons needs no account at all; that happens entirely on the public
site. Only saving arrives here.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import api_error, get_current_user
from app.models import LearningDraft, LearningProgress, User
from app.schemas import (
    LearningStateOut,
    MarkCompleteIn,
    MergeProgressIn,
    SaveDraftIn,
)

router = APIRouter(prefix="/me/learning", tags=["learning"])

# Free-writing can be long, but it is still a text field in SQLite.
MAX_DRAFT_CHARS = 20_000
VALID_VIA = ("manual", "timer", "quiz", "override")


def _state(db: Session, user: User) -> dict:
    items = (
        db.query(LearningProgress)
        .filter(LearningProgress.user_id == user.id)
        .order_by(LearningProgress.completed_at)
        .all()
    )
    drafts = db.query(LearningDraft).filter(LearningDraft.user_id == user.id).all()
    return {
        "items": [
            {
                "item_id": p.item_id,
                "course_slug": p.course_slug,
                "completed_at": p.completed_at.isoformat(),
                "via": p.via,
            }
            for p in items
        ],
        "drafts": [
            {
                "item_id": d.item_id,
                "text": d.text,
                "updated_at": d.updated_at.isoformat(),
            }
            for d in drafts
        ],
    }


@router.get("", response_model=LearningStateOut)
def get_state(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return _state(db, user)


@router.put("/items/{item_id}", response_model=LearningStateOut)
def mark_complete(
    item_id: str,
    payload: MarkCompleteIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.via not in VALID_VIA:
        raise api_error(422, "invalid_via")

    existing = (
        db.query(LearningProgress)
        .filter(
            LearningProgress.user_id == user.id,
            LearningProgress.item_id == item_id,
        )
        .first()
    )
    # Completing twice keeps the original timestamp — the date someone first
    # finished a lesson is the interesting one.
    if existing is None:
        db.add(
            LearningProgress(
                user_id=user.id,
                course_slug=payload.course_slug,
                item_id=item_id,
                via=payload.via,
            )
        )
        db.commit()
    return _state(db, user)


@router.delete("/items/{item_id}", response_model=LearningStateOut)
def mark_incomplete(
    item_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(LearningProgress).filter(
        LearningProgress.user_id == user.id,
        LearningProgress.item_id == item_id,
    ).delete()
    db.commit()
    return _state(db, user)


@router.put("/drafts/{item_id}", response_model=LearningStateOut)
def save_draft(
    item_id: str,
    payload: SaveDraftIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    text = payload.text[:MAX_DRAFT_CHARS]
    draft = (
        db.query(LearningDraft)
        .filter(LearningDraft.user_id == user.id, LearningDraft.item_id == item_id)
        .first()
    )
    if not text:
        # Clearing the box deletes the row rather than storing an empty one.
        if draft is not None:
            db.delete(draft)
    elif draft is None:
        db.add(LearningDraft(user_id=user.id, item_id=item_id, text=text))
    else:
        draft.text = text
    db.commit()
    return _state(db, user)


@router.post("/merge", response_model=LearningStateOut)
def merge_local(
    payload: MergeProgressIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import a visitor's localStorage progress, once, on first sign-in.

    Idempotent: completions already on the account are left alone, and a draft
    is only imported when the account has nothing for that item — the account
    is always the more recent source.
    """
    known = {
        p.item_id
        for p in db.query(LearningProgress)
        .filter(LearningProgress.user_id == user.id)
        .all()
    }
    for entry in payload.items:
        if entry.item_id in known:
            continue
        db.add(
            LearningProgress(
                user_id=user.id,
                course_slug=entry.course_slug,
                item_id=entry.item_id,
                via=entry.via if entry.via in VALID_VIA else "manual",
            )
        )
        known.add(entry.item_id)

    have_drafts = {
        d.item_id
        for d in db.query(LearningDraft)
        .filter(LearningDraft.user_id == user.id)
        .all()
    }
    for draft in payload.drafts:
        if draft.item_id in have_drafts or not draft.text.strip():
            continue
        db.add(
            LearningDraft(
                user_id=user.id,
                item_id=draft.item_id,
                text=draft.text[:MAX_DRAFT_CHARS],
            )
        )

    db.commit()
    return _state(db, user)
