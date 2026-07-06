from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import api_error, require_complete_profile
from app.geo import haversine_meters
from app.models import Activity, Attendance, User
from app.schemas import (
    AttendanceStatusOut,
    PagedHistoryOut,
    SubmitAttendanceIn,
    SubmitAttendanceOut,
)
from app.services import (
    compute_streak,
    ensure_today_session,
    get_app_settings,
    now_local,
    parse_hhmm,
    record_out,
    resolve_venue,
)

router = APIRouter(prefix="/attendance", tags=["attendance"])
limiter = Limiter(key_func=get_remote_address)


def _activity_member_out(db: Session, activity: Activity) -> dict:
    venue = resolve_venue(db, activity)
    return {
        "id": activity.id,
        "title": activity.title,
        "description": activity.description,
        "date": activity.date,
        "start_time": activity.start_time,
        "end_time": activity.end_time,
        "is_attendance_event": activity.is_attendance_event,
        "is_holiday": activity.is_holiday,
        "venue": (
            {"name": venue.name, "address": venue.address} if venue else None
        ),
    }


def _status(db: Session, user: User) -> dict:
    ensure_today_session(db)
    now = now_local(db)
    today = now.strftime("%Y-%m-%d")

    activity = (
        db.query(Activity)
        .filter(Activity.date == today, Activity.is_attendance_event.is_(True))
        .order_by(Activity.id)
        .first()
    )

    base = {
        "open": False,
        "reason": None,
        "code_required": False,
        "activity": None,
        "venue": None,
        "attended_at": None,
        "server_time": now.isoformat(),
    }

    if activity is None:
        return {**base, "reason": "no_session"}

    venue = resolve_venue(db, activity)
    base["activity"] = _activity_member_out(db, activity)
    base["venue"] = venue
    base["code_required"] = activity.attendance_code is not None

    if activity.is_holiday:
        return {**base, "reason": "holiday"}

    existing = (
        db.query(Attendance)
        .filter(
            Attendance.user_id == user.id, Attendance.activity_id == activity.id
        )
        .first()
    )
    if existing:
        return {
            **base,
            "reason": "already_attended",
            "attended_at": existing.attended_at.isoformat(),
        }

    day = datetime.strptime(activity.date, "%Y-%m-%d").date()
    start = parse_hhmm(day, activity.start_time)
    end = parse_hhmm(day, activity.end_time)
    if now < start:
        return {**base, "reason": "too_early"}
    if now > end:
        return {**base, "reason": "closed"}

    return {**base, "open": True}


@router.get("/status", response_model=AttendanceStatusOut)
def attendance_status(
    user: User = Depends(require_complete_profile),
    db: Session = Depends(get_db),
):
    return _status(db, user)


@router.post("", response_model=SubmitAttendanceOut, status_code=201)
@limiter.limit("10/minute")
def submit_attendance(
    request: Request,
    payload: SubmitAttendanceIn,
    user: User = Depends(require_complete_profile),
    db: Session = Depends(get_db),
):
    status = _status(db, user)

    if not status["open"]:
        reason = status["reason"]
        if reason == "already_attended":
            raise api_error(409, "already_attended")
        raise api_error(409, reason or "closed")

    activity_id = status["activity"]["id"]
    activity = db.get(Activity, activity_id)
    venue = resolve_venue(db, activity)
    if venue is None:
        raise api_error(409, "closed", "no venue configured")

    settings = get_app_settings(db)
    if payload.accuracy > float(settings["gps_accuracy_max_m"]):
        raise api_error(422, "gps_accuracy")

    distance = haversine_meters(payload.lat, payload.lng, venue.lat, venue.lng)
    if distance > venue.radius_m:
        raise api_error(422, "outside_radius")

    if activity.attendance_code is not None:
        if not payload.code:
            raise api_error(422, "code_required")
        if payload.code.strip().upper() != activity.attendance_code.upper():
            raise api_error(422, "invalid_code")

    attendance = Attendance(
        user_id=user.id,
        activity_id=activity.id,
        attended_at=now_local(db),
        lat=payload.lat,
        lng=payload.lng,
        distance_m=round(distance, 1),
    )
    db.add(attendance)
    try:
        db.commit()
    except IntegrityError:
        # UNIQUE(user_id, activity_id) — race-proof duplicate prevention.
        db.rollback()
        raise api_error(409, "already_attended")

    today = now_local(db).strftime("%Y-%m-%d")
    total = (
        db.query(Attendance).filter(Attendance.user_id == user.id).count()
    )
    return {
        "record": record_out(db, attendance),
        "streak": compute_streak(db, user.id, today),
        "total": total,
    }


@router.get("/me")
def my_attendance(
    from_: str = Query(alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    to: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: User = Depends(require_complete_profile),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Attendance)
        .join(Activity, Attendance.activity_id == Activity.id)
        .filter(
            Attendance.user_id == user.id,
            Activity.date >= from_,
            Activity.date <= to,
        )
        .order_by(Activity.date.desc())
        .all()
    )
    return [record_out(db, r) for r in rows]


@router.get("/me/history", response_model=PagedHistoryOut)
def my_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    user: User = Depends(require_complete_profile),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Attendance)
        .join(Activity, Attendance.activity_id == Activity.id)
        .filter(Attendance.user_id == user.id)
        .order_by(Activity.date.desc())
    )
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    today = now_local(db).strftime("%Y-%m-%d")
    return {
        "items": [record_out(db, r) for r in rows],
        "total": total,
        "streak": compute_streak(db, user.id, today),
        "has_more": (page - 1) * page_size + len(rows) < total,
    }
