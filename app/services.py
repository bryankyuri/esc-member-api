"""Domain helpers shared by the routers: app settings, session auto-creation,
venue resolution, streaks, and record serialization."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Activity, Attendance, Setting, User, Venue

SETTINGS_DEFAULTS: dict[str, str] = {
    "default_day": "1",  # 0=Sunday … 1=Monday (matches frontend contract)
    "default_start": "19:00",
    "default_end": "23:59",
    "timezone": "Asia/Jakarta",
    "gps_accuracy_max_m": "200",
}

DEFAULT_SESSION_TITLE = "ESC Weekly Session"


def get_app_settings(db: Session) -> dict[str, str]:
    stored = {s.key: s.value for s in db.query(Setting).all()}
    return {**SETTINGS_DEFAULTS, **stored}


def save_app_settings(db: Session, values: dict[str, str]) -> None:
    for key, value in values.items():
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=str(value)))
        else:
            row.value = str(value)
    db.commit()


def now_local(db: Session) -> datetime:
    tz = ZoneInfo(get_app_settings(db)["timezone"])
    return datetime.now(tz).replace(tzinfo=None)  # naive local time throughout


def default_venue(db: Session) -> Venue | None:
    return (
        db.query(Venue)
        .filter(Venue.is_default.is_(True), Venue.is_active.is_(True))
        .first()
    )


def resolve_venue(db: Session, activity: Activity) -> Venue | None:
    """Per-activity venue if set, otherwise the default venue."""
    if activity.venue_id is not None:
        venue = db.get(Venue, activity.venue_id)
        if venue is not None:
            return venue
    return default_venue(db)


def ensure_today_session(db: Session) -> None:
    """Auto-create the weekly session row for today if the admin hasn't.

    Keeps 'the regular Monday' and admin-managed calendar entries as one
    concept (SDD §5). Runs on /attendance/status reads.
    """
    now = now_local(db)
    settings = get_app_settings(db)
    # Python weekday(): Monday=0 … Sunday=6. Contract: 0=Sunday … 6=Saturday.
    contract_weekday = (now.weekday() + 1) % 7
    if contract_weekday != int(settings["default_day"]):
        return
    today = now.strftime("%Y-%m-%d")
    exists = (
        db.query(Activity)
        .filter(Activity.date == today, Activity.is_attendance_event.is_(True))
        .first()
    )
    if exists:
        return
    db.add(
        Activity(
            title=DEFAULT_SESSION_TITLE,
            description=None,
            date=today,
            start_time=settings["default_start"],
            end_time=settings["default_end"],
            is_attendance_event=True,
            is_holiday=False,
            venue_id=None,
        )
    )
    db.commit()


def parse_hhmm(day: date, hhmm: str) -> datetime:
    hours, minutes = (int(p) for p in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hours, minutes)


def compute_streak(db: Session, user_id: int, today: str) -> int:
    """Consecutive attended sessions counting back from the most recent
    finished (or attended) attendance event. Libur sessions are skipped."""
    sessions = (
        db.query(Activity)
        .filter(
            Activity.is_attendance_event.is_(True),
            Activity.is_holiday.is_(False),
            Activity.date <= today,
        )
        .order_by(Activity.date.desc())
        .all()
    )
    attended_ids = {
        a.activity_id
        for a in db.query(Attendance).filter(Attendance.user_id == user_id).all()
    }
    streak = 0
    for idx, session in enumerate(sessions):
        if session.id in attended_ids:
            streak += 1
        elif idx == 0 and session.date == today:
            # Today's session isn't over — an un-attended today doesn't
            # break the streak yet.
            continue
        else:
            break
    return streak


def record_out(db: Session, att: Attendance) -> dict:
    activity = att.activity or db.get(Activity, att.activity_id)
    venue = resolve_venue(db, activity) if activity else None
    return {
        "id": att.id,
        "activity_id": att.activity_id,
        "activity_title": activity.title if activity else "",
        "date": activity.date if activity else "",
        "attended_at": att.attended_at.isoformat(),
        "venue_name": venue.name if venue else "",
    }


def seed_defaults(db: Session) -> None:
    """First-boot seed: settings defaults + a placeholder default venue."""
    save_app_settings(db, get_app_settings(db))
    if default_venue(db) is None:
        db.add(
            Venue(
                name="Earhouse",
                address="Earhouse by Endah N Rhesa, Pamulang, Tangerang Selatan",
                lat=-6.3403526,
                lng=106.7281456,
                radius_m=100,
                is_default=True,
                is_active=True,
            )
        )
        db.commit()


def user_out(user: User, role: str) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "whatsapp": user.whatsapp,
        "domicile": user.domicile,
        "instagram": user.instagram,
        "role": role,
        "profile_completed": user.profile_completed,
        "security_passed": user.security_passed,
    }
