import csv
import io
import secrets
from calendar import monthrange
from datetime import date as date_cls, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import api_error, effective_role, is_member, require_admin
from app.models import Activity, Attendance, User, Venue
from app.schemas import (
    EVENT_KINDS,
    SLUG_RE,
    ActivityAdminOut,
    ActivityIn,
    AttendanceLogRowOut,
    GenerateSessionsIn,
    MemberRowOut,
    OverviewOut,
    PagedRecordsOut,
    SessionSummaryOut,
    SettingsIn,
    SettingsOut,
    UpdateMemberIn,
    VenueIn,
    VenueOut,
)
from app.services import (
    DEFAULT_SESSION_TITLE,
    get_app_settings,
    membership_status,
    now_local,
    record_out,
    resolve_venue,
    save_app_settings,
)

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)

# Unambiguous alphabet: no 0/O, 1/I/L.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _random_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


# ---- Overview / logs ----------------------------------------------------


def _log_row(db: Session, att: Attendance) -> dict:
    activity = att.activity
    venue = resolve_venue(db, activity) if activity else None
    return {
        "id": att.id,
        "member_id": att.user_id,
        "member_name": att.user.full_name if att.user else "",
        "attended_at": att.attended_at.isoformat(),
        "distance_m": att.distance_m or 0,
        "venue_name": venue.name if venue else "",
    }


@router.get("/overview", response_model=OverviewOut)
def overview(db: Session = Depends(get_db)):
    now = now_local(db)
    # Week starts Monday (session day anchor).
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    this_week = (
        db.query(Attendance).filter(Attendance.attended_at >= week_start).count()
    )
    # "Members" here means people who actually completed membership, not every
    # signed-in account — the public site now creates `user` accounts too.
    all_users = db.query(User).all()
    statuses = [membership_status(db, u) for u in all_users]
    total_members = sum(1 for s in statuses if s != "none")
    active_members = statuses.count("active")
    dormant_members = statuses.count("dormant")
    registered_members = statuses.count("registered")

    per_session = (
        db.query(Attendance.activity_id, func.count(Attendance.id))
        .group_by(Attendance.activity_id)
        .all()
    )
    average = (
        round(sum(c for _, c in per_session) / len(per_session))
        if per_session
        else 0
    )

    trend = []
    for i in range(5, -1, -1):
        anchor = now.replace(day=1) - timedelta(days=1)
        month_date = now
        for _ in range(i):
            month_date = month_date.replace(day=1) - timedelta(days=1)
        month = month_date.strftime("%Y-%m")
        count = (
            db.query(Attendance)
            .join(Activity, Attendance.activity_id == Activity.id)
            .filter(Activity.date.like(f"{month}-%"))
            .count()
        )
        trend.append({"month": month, "count": count})
        _ = anchor

    recent = (
        db.query(Attendance)
        .order_by(Attendance.attended_at.desc())
        .limit(8)
        .all()
    )

    return {
        "this_week_count": this_week,
        "total_members": total_members,
        "active_members": active_members,
        "dormant_members": dormant_members,
        "registered_members": registered_members,
        "average_per_session": average,
        "monthly_trend": trend,
        "recent_checkins": [_log_row(db, r) for r in recent],
    }


@router.get("/sessions", response_model=list[SessionSummaryOut])
def sessions(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    counts = dict(
        db.query(Attendance.activity_id, func.count(Attendance.id))
        .group_by(Attendance.activity_id)
        .all()
    )
    rows = (
        db.query(Activity)
        .filter(Activity.is_attendance_event.is_(True), Activity.id.in_(counts))
        .order_by(Activity.date.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "activity_id": a.id,
            "date": a.date,
            "title": a.title,
            "attendee_count": counts.get(a.id, 0),
        }
        for a in rows
    ]


@router.get("/attendance", response_model=list[AttendanceLogRowOut])
def attendance_log(activity_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(Attendance)
        .filter(Attendance.activity_id == activity_id)
        .order_by(Attendance.attended_at)
        .all()
    )
    return [_log_row(db, r) for r in rows]


@router.get("/export")
def export_csv(
    from_: str = Query(alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    to: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Attendance)
        .join(Activity, Attendance.activity_id == Activity.id)
        .filter(Activity.date >= from_, Activity.date <= to)
        .order_by(Activity.date, Attendance.attended_at)
        .all()
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "member", "email", "checked_in_at", "distance_m", "venue"])
    for att in rows:
        venue = resolve_venue(db, att.activity) if att.activity else None
        writer.writerow(
            [
                att.activity.date if att.activity else "",
                att.user.full_name if att.user else "",
                att.user.email if att.user else "",
                att.attended_at.strftime("%H:%M:%S"),
                att.distance_m or "",
                venue.name if venue else "",
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="esc-attendance-{from_}-{to}.csv"'
        },
    )


# ---- Members ------------------------------------------------------------


def _member_row(db: Session, user: User) -> dict:
    total, last = (
        db.query(func.count(Attendance.id), func.max(Attendance.attended_at))
        .filter(Attendance.user_id == user.id)
        .one()
    )
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "whatsapp": user.whatsapp,
        "domicile": user.domicile,
        "instagram": user.instagram,
        # Two separate ideas, two separate columns in the UI: what they may
        # manage (role) and how alive their membership is (status).
        "role": effective_role(user),
        "is_member": is_member(user),
        "membership_status": membership_status(db, user),
        "member_since": user.member_since.isoformat() if user.member_since else None,
        "is_active": user.is_active,
        "profile_completed": user.profile_completed,
        "total_attendance": total or 0,
        "last_attended_at": last.isoformat() if isinstance(last, datetime) else None,
        "joined_at": user.created_at.isoformat() if user.created_at else "",
    }


@router.get("/members", response_model=list[MemberRowOut])
def members(
    status: str | None = Query(
        default=None, pattern=r"^(none|registered|active|dormant|disabled)$"
    ),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.full_name).all()
    rows = [_member_row(db, u) for u in users]
    if status:
        rows = [r for r in rows if r["membership_status"] == status]
    return rows


@router.get("/members/{member_id}", response_model=MemberRowOut)
def member_detail(member_id: str, db: Session = Depends(get_db)):
    user = db.get(User, member_id)
    if user is None:
        raise api_error(404, "unknown", "member not found")
    return _member_row(db, user)


@router.get("/members/{member_id}/attendance", response_model=PagedRecordsOut)
def member_attendance(
    member_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Attendance)
        .join(Activity, Attendance.activity_id == Activity.id)
        .filter(Attendance.user_id == member_id)
        .order_by(Activity.date.desc())
    )
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [record_out(db, r) for r in rows],
        "total": total,
        "has_more": (page - 1) * page_size + len(rows) < total,
    }


@router.patch("/members/{member_id}", response_model=MemberRowOut)
def update_member(
    member_id: str,
    payload: UpdateMemberIn,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, member_id)
    if user is None:
        raise api_error(404, "unknown", "member not found")
    # Superadmin is env-defined: its status/role can never change via API.
    if effective_role(user) == "superadmin":
        raise api_error(403, "forbidden", "superadmin is configured on the server")

    if payload.role is not None:
        # Granting or removing admin is superadmin-only. Without this an admin
        # could demote every other admin, including the person who promoted
        # them. Contributor is an ordinary admin decision.
        touches_admin = payload.role == "admin" or user.role == "admin"
        if touches_admin and effective_role(actor) != "superadmin":
            raise api_error(
                403, "forbidden", "only a superadmin can grant or revoke admin"
            )
        user.role = payload.role

    if payload.is_active is not None:
        user.is_active = payload.is_active

    db.commit()
    return _member_row(db, user)


# ---- Activities ----------------------------------------------------------


@router.get("/activities", response_model=list[ActivityAdminOut])
def admin_activities(
    month: str = Query(pattern=r"^\d{4}-\d{2}$"), db: Session = Depends(get_db)
):
    return (
        db.query(Activity)
        .filter(Activity.date.like(f"{month}-%"))
        .order_by(Activity.date)
        .all()
    )


@router.post(
    "/activities/generate",
    response_model=list[ActivityAdminOut],
    status_code=201,
)
def generate_sessions(
    payload: GenerateSessionsIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Create the default weekly session on every default-day date of the
    given month, skipping dates that already have an attendance event."""
    settings = get_app_settings(db)
    target_day = int(settings["default_day"])  # 0=Sunday … 6=Saturday
    year, month = (int(p) for p in payload.month.split("-"))

    existing = {
        a.date
        for a in db.query(Activity)
        .filter(
            Activity.date.like(f"{payload.month}-%"),
            Activity.is_attendance_event.is_(True),
        )
        .all()
    }

    created: list[Activity] = []
    for day in range(1, monthrange(year, month)[1] + 1):
        d = date_cls(year, month, day)
        if (d.weekday() + 1) % 7 != target_day:
            continue
        date_str = d.strftime("%Y-%m-%d")
        if date_str in existing:
            continue
        activity = Activity(
            title=DEFAULT_SESSION_TITLE,
            description=None,
            date=date_str,
            start_time=settings["default_start"],
            end_time=settings["default_end"],
            is_attendance_event=True,
            is_holiday=False,
            venue_id=None,
            created_by=admin.id,
        )
        db.add(activity)
        created.append(activity)
    db.commit()
    return created


def _assert_no_duplicate_session(
    db: Session, payload: ActivityIn, exclude_id: str | None = None
) -> None:
    """At most one attendance session per date."""
    if not payload.is_attendance_event:
        return
    query = db.query(Activity).filter(
        Activity.date == payload.date, Activity.is_attendance_event.is_(True)
    )
    if exclude_id is not None:
        query = query.filter(Activity.id != exclude_id)
    if query.first() is not None:
        raise api_error(
            409, "duplicate_session", "an attendance session already exists on that date"
        )


def _validate_public(
    db: Session, payload: ActivityIn, exclude_id: str | None = None
) -> None:
    """Checks that only matter once an activity faces the public."""
    if payload.kind not in EVENT_KINDS:
        raise api_error(422, "invalid_kind", f"one of {', '.join(EVENT_KINDS)}")

    slug = (payload.public_slug or "").strip()
    if slug:
        if not SLUG_RE.match(slug):
            raise api_error(
                422, "invalid_slug", "lowercase letters, digits and hyphens"
            )
        clash = db.query(Activity).filter(Activity.public_slug == slug)
        if exclude_id is not None:
            clash = clash.filter(Activity.id != exclude_id)
        if clash.first() is not None:
            raise api_error(409, "slug_taken")

    if payload.is_public and not payload.summary_id.strip():
        # The calendar card is a title and a summary; publishing without one
        # puts an empty card on the public site.
        raise api_error(422, "summary_required", "a public activity needs a summary")


@router.post("/activities", response_model=ActivityAdminOut, status_code=201)
def create_activity(
    payload: ActivityIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    _assert_no_duplicate_session(db, payload)
    _validate_public(db, payload)
    values = payload.model_dump()
    values["public_slug"] = (values.get("public_slug") or "").strip() or None
    activity = Activity(**values, created_by=admin.id)
    db.add(activity)
    db.commit()
    return activity


@router.patch("/activities/{activity_id}", response_model=ActivityAdminOut)
def update_activity(
    activity_id: str, payload: ActivityIn, db: Session = Depends(get_db)
):
    """A real partial update: only the fields the request actually sent.

    This matters now that activities carry public-calendar content. A client
    that knows nothing about images and links — the attendance-side forms, say
    — must be able to move a workshop's start time without silently erasing
    the carousel someone built.
    """
    activity = db.get(Activity, activity_id)
    if activity is None:
        raise api_error(404, "unknown", "activity not found")
    _assert_no_duplicate_session(db, payload, exclude_id=activity_id)
    _validate_public(db, payload, exclude_id=activity_id)

    changes = payload.model_dump(exclude_unset=True)
    if "public_slug" in changes:
        changes["public_slug"] = (changes["public_slug"] or "").strip() or None
    for key, value in changes.items():
        setattr(activity, key, value)
    db.commit()
    return activity


@router.delete("/activities/{activity_id}", status_code=204)
def delete_activity(activity_id: str, db: Session = Depends(get_db)):
    activity = db.get(Activity, activity_id)
    if activity is None:
        return
    if activity.is_attendance_event:
        # The DEFAULT-DAY weekly session (e.g. Monday) is never deleted —
        # only marked libur. Attendance sessions on other days are extra
        # events and may be deleted…
        settings = get_app_settings(db)
        day = datetime.strptime(activity.date, "%Y-%m-%d").date()
        if (day.weekday() + 1) % 7 == int(settings["default_day"]):
            raise api_error(
                409,
                "session_protected",
                "default-day sessions cannot be deleted; mark as libur",
            )
        # …unless members already checked in — that history is protected.
        has_attendance = (
            db.query(Attendance)
            .filter(Attendance.activity_id == activity_id)
            .first()
            is not None
        )
        if has_attendance:
            raise api_error(
                409,
                "has_attendance",
                "sessions with attendance records cannot be deleted; mark as libur",
            )
    db.delete(activity)
    db.commit()


@router.post("/activities/{activity_id}/code", response_model=ActivityAdminOut)
def generate_code(activity_id: str, db: Session = Depends(get_db)):
    activity = db.get(Activity, activity_id)
    if activity is None:
        raise api_error(404, "unknown", "activity not found")
    activity.attendance_code = _random_code()
    db.commit()
    return activity


@router.delete("/activities/{activity_id}/code", response_model=ActivityAdminOut)
def remove_code(activity_id: str, db: Session = Depends(get_db)):
    activity = db.get(Activity, activity_id)
    if activity is None:
        raise api_error(404, "unknown", "activity not found")
    activity.attendance_code = None
    db.commit()
    return activity


# ---- Venues ---------------------------------------------------------------


@router.get("/venues", response_model=list[VenueOut])
def venues(db: Session = Depends(get_db)):
    return (
        db.query(Venue)
        .filter(Venue.is_active.is_(True))
        .order_by(Venue.is_default.desc(), Venue.name)
        .all()
    )


@router.post("/venues", response_model=VenueOut, status_code=201)
def create_venue(payload: VenueIn, db: Session = Depends(get_db)):
    venue = Venue(**payload.model_dump(), is_default=False, is_active=True)
    db.add(venue)
    db.commit()
    return venue


@router.patch("/venues/{venue_id}", response_model=VenueOut)
def update_venue(venue_id: str, payload: VenueIn, db: Session = Depends(get_db)):
    venue = db.get(Venue, venue_id)
    if venue is None or not venue.is_active:
        raise api_error(404, "unknown", "venue not found")
    for key, value in payload.model_dump().items():
        setattr(venue, key, value)
    db.commit()
    return venue


@router.patch("/venues/{venue_id}/default", response_model=VenueOut)
def set_default_venue(venue_id: str, db: Session = Depends(get_db)):
    venue = db.get(Venue, venue_id)
    if venue is None or not venue.is_active:
        raise api_error(404, "unknown", "venue not found")
    db.query(Venue).update({Venue.is_default: False})
    venue.is_default = True
    db.commit()
    return venue


@router.delete("/venues/{venue_id}", status_code=204)
def deactivate_venue(venue_id: str, db: Session = Depends(get_db)):
    venue = db.get(Venue, venue_id)
    if venue is None:
        return
    if venue.is_default:
        raise api_error(409, "unknown", "cannot remove the default venue")
    # Soft-delete: past activities keep their venue for history/audit.
    venue.is_active = False
    db.commit()


# ---- Settings --------------------------------------------------------------


@router.get("/settings", response_model=SettingsOut)
def get_settings_endpoint(db: Session = Depends(get_db)):
    s = get_app_settings(db)
    return {
        "default_day": int(s["default_day"]),
        "default_start": s["default_start"],
        "default_end": s["default_end"],
        "timezone": s["timezone"],
        "gps_accuracy_max_m": int(s["gps_accuracy_max_m"]),
    }


@router.put("/settings", response_model=SettingsOut)
def put_settings(payload: SettingsIn, db: Session = Depends(get_db)):
    save_app_settings(
        db,
        {
            "default_day": str(payload.default_day),
            "default_start": payload.default_start,
            "default_end": payload.default_end,
            "timezone": payload.timezone,
            "gps_accuracy_max_m": str(payload.gps_accuracy_max_m),
        },
    )
    return get_settings_endpoint(db)
