# Pydantic schemas — field names are snake_case internally but serialize to
# camelCase, matching the frozen TypeScript contracts in member-frontend and
# member-dashboard (src/lib/types.ts).

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


# ---- Auth / users ------------------------------------------------------


class UserOut(ApiModel):
    id: int
    email: str
    full_name: str
    avatar_url: str | None
    whatsapp: str | None
    domicile: str | None
    instagram: str | None
    role: str
    profile_completed: bool


class CompleteProfileIn(ApiModel):
    full_name: str = Field(min_length=1, max_length=120)
    whatsapp: str = Field(min_length=8, max_length=20, pattern=r"^\+?[0-9]{8,18}$")
    domicile: str = Field(min_length=1, max_length=120)
    instagram: str = Field(min_length=1, max_length=60)


class UpdateProfileIn(ApiModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    whatsapp: str | None = Field(
        default=None, min_length=8, max_length=20, pattern=r"^\+?[0-9]{8,18}$"
    )
    domicile: str | None = Field(default=None, min_length=1, max_length=120)
    instagram: str | None = Field(default=None, min_length=1, max_length=60)


# ---- Venues / activities ----------------------------------------------


class VenueOut(ApiModel):
    id: int
    name: str
    address: str
    lat: float
    lng: float
    radius_m: float
    is_default: bool
    is_active: bool


class VenueIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(default="", max_length=250)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: float = Field(ge=10, le=5000)


class ActivityVenueOut(ApiModel):
    name: str
    address: str


class ActivityMemberOut(ApiModel):
    """Activity shape for the member app (venue embedded as name/address)."""

    id: int
    title: str
    description: str | None
    date: str
    start_time: str
    end_time: str
    is_attendance_event: bool
    is_holiday: bool
    venue: ActivityVenueOut | None


class ActivityAdminOut(ApiModel):
    """Activity shape for the dashboard (venue as id, code visible)."""

    id: int
    title: str
    description: str | None
    date: str
    start_time: str
    end_time: str
    is_attendance_event: bool
    is_holiday: bool
    venue_id: int | None
    attendance_code: str | None


class GenerateSessionsIn(ApiModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")


class ActivityIn(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    is_attendance_event: bool
    is_holiday: bool = False
    venue_id: int | None = None


# ---- Attendance (member) ----------------------------------------------


class AttendanceStatusOut(ApiModel):
    open: bool
    reason: str | None
    code_required: bool
    activity: ActivityMemberOut | None
    venue: VenueOut | None
    attended_at: str | None
    server_time: str
    gps_accuracy_max_m: int  # admin-configured; the client gate uses this too


class SubmitAttendanceIn(ApiModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy: float = Field(ge=0)
    code: str | None = None


class AttendanceRecordOut(ApiModel):
    id: int
    activity_id: int
    activity_title: str
    date: str
    attended_at: str
    venue_name: str


class SubmitAttendanceOut(ApiModel):
    record: AttendanceRecordOut
    streak: int
    total: int  # lifetime attendance count incl. this one (1 = first timer)


class PagedHistoryOut(ApiModel):
    items: list[AttendanceRecordOut]
    total: int
    streak: int
    has_more: bool


# ---- Admin -------------------------------------------------------------


class MemberRowOut(ApiModel):
    id: int
    full_name: str
    email: str
    avatar_url: str | None
    whatsapp: str | None
    domicile: str | None
    instagram: str | None
    role: str
    is_active: bool
    profile_completed: bool
    total_attendance: int
    last_attended_at: str | None
    joined_at: str


class UpdateMemberIn(ApiModel):
    is_active: bool | None = None
    role: str | None = Field(default=None, pattern=r"^(member|admin)$")


class AttendanceLogRowOut(ApiModel):
    id: int
    member_id: int
    member_name: str
    attended_at: str
    distance_m: float
    venue_name: str


class SessionSummaryOut(ApiModel):
    activity_id: int
    date: str
    title: str
    attendee_count: int


class MonthlyTrendPointOut(ApiModel):
    month: str
    count: int


class OverviewOut(ApiModel):
    this_week_count: int
    total_members: int
    active_members: int
    average_per_session: int
    monthly_trend: list[MonthlyTrendPointOut]
    recent_checkins: list[AttendanceLogRowOut]


class PagedRecordsOut(ApiModel):
    items: list[AttendanceRecordOut]
    total: int
    has_more: bool


class SettingsOut(ApiModel):
    default_day: int
    default_start: str
    default_end: str
    timezone: str
    gps_accuracy_max_m: int


class SettingsIn(ApiModel):
    default_day: int = Field(ge=0, le=6)
    default_start: str = Field(pattern=r"^\d{2}:\d{2}$")
    default_end: str = Field(pattern=r"^\d{2}:\d{2}$")
    timezone: str
    gps_accuracy_max_m: int = Field(ge=50, le=1000)
