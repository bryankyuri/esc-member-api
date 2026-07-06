from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_complete_profile
from app.models import Activity, User
from app.schemas import ActivityMemberOut
from app.services import resolve_venue

router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("", response_model=list[ActivityMemberOut])
def list_activities(
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
    _user: User = Depends(require_complete_profile),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Activity)
        .filter(Activity.date.like(f"{month}-%"))
        .order_by(Activity.date)
        .all()
    )
    result = []
    for a in rows:
        venue = resolve_venue(db, a)
        result.append(
            {
                "id": a.id,
                "title": a.title,
                "description": a.description,
                "date": a.date,
                "start_time": a.start_time,
                "end_time": a.end_time,
                "is_attendance_event": a.is_attendance_event,
                "is_holiday": a.is_holiday,
                "venue": (
                    {"name": venue.name, "address": venue.address}
                    if venue
                    else None
                ),
            }
        )
    return result
