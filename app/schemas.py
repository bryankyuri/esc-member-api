# Pydantic schemas — field names are snake_case internally but serialize to
# camelCase, matching the frozen TypeScript contracts in member-frontend and
# member-dashboard (src/lib/types.ts).

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


# ---- Auth / users ------------------------------------------------------


class UserOut(ApiModel):
    id: str
    email: str
    full_name: str
    avatar_url: str | None
    whatsapp: str | None
    domicile: str | None
    instagram: str | None
    # What they may manage: user | contributor | admin | superadmin
    role: str
    profile_completed: bool
    security_passed: bool
    # Learner profile — the name a certificate is issued in.
    first_name: str | None = None
    last_name: str | None = None
    # Membership: derived from the two flags above, and the only thing that
    # opens the member area. Status is a display label (see services).
    is_member: bool
    membership_status: str
    member_since: str | None = None
    attendance_count: int = 0
    last_attended_at: str | None = None


class SecurityAnswerIn(ApiModel):
    answer: str = Field(min_length=1, max_length=200)


# ---- Learning (progress kept on the account, any signed-in role) ----------


class ProgressItemOut(ApiModel):
    item_id: str
    course_slug: str
    completed_at: str
    via: str


class DraftOut(ApiModel):
    item_id: str
    text: str
    updated_at: str


class LearningStateOut(ApiModel):
    items: list[ProgressItemOut]
    drafts: list[DraftOut]


class MarkCompleteIn(ApiModel):
    course_slug: str = Field(min_length=1, max_length=120)
    via: str = "manual"


class SaveDraftIn(ApiModel):
    text: str = ""


class MergeItemIn(ApiModel):
    item_id: str = Field(min_length=1, max_length=120)
    course_slug: str = Field(min_length=1, max_length=120)
    via: str = "manual"


class MergeDraftIn(ApiModel):
    item_id: str = Field(min_length=1, max_length=120)
    text: str = ""


class MergeProgressIn(ApiModel):
    """A visitor's localStorage store, sent once after their first sign-in."""

    items: list[MergeItemIn] = Field(default_factory=list, max_length=500)
    drafts: list[MergeDraftIn] = Field(default_factory=list, max_length=200)


# ---- Certificates --------------------------------------------------------


class LearnerProfileIn(ApiModel):
    """The whole learner profile: a name to print. No address, no phone."""

    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(default="", max_length=80)


class IssueCertificateIn(ApiModel):
    course_slug: str = Field(min_length=1, max_length=120)


class CertificateOut(ApiModel):
    """The holder's own certificate, including the email printed on it."""

    code: str
    course_slug: str
    course_title: str
    first_name: str
    last_name: str
    email: str
    issued_at: str
    revoked: bool


class CertificateVerifyOut(ApiModel):
    """Public proof. No email — see routers/certificates.py."""

    code: str
    holder_name: str
    course_title: str
    issued_at: str
    valid: bool


# ---- Articles ------------------------------------------------------------


class LocalizedIn(ApiModel):
    """Every visitor-facing string is bilingual; EN may be left empty and
    falls back to ID when rendered."""

    id: str = ""
    en: str = ""


class ArticleIn(ApiModel):
    slug: str = Field(min_length=1, max_length=120)
    category: str
    title: LocalizedIn
    excerpt: LocalizedIn = Field(default_factory=LocalizedIn)
    hero: dict | None = None
    body: list[dict] = Field(default_factory=list)
    seo: dict | None = None
    related_slugs: list[str] = Field(default_factory=list, max_length=10)
    event_slug: str | None = None
    course_slug: str | None = None
    featured: bool = False


class ArticleStatusIn(ApiModel):
    status: str
    """Optional: schedule a post by publishing it with a future timestamp."""
    published_at: datetime | None = None


class LocalizedOut(ApiModel):
    id: str
    en: str


class ArticleCardOut(ApiModel):
    slug: str
    category: str
    title: LocalizedOut
    excerpt: LocalizedOut
    hero: dict | None = None
    featured: bool = False
    published_at: str | None = None
    updated_at: str | None = None
    reading_minutes: int = 1
    author_name: str = "Tim ESC"


class ArticleDetailOut(ArticleCardOut):
    body: list[dict] = Field(default_factory=list)
    seo: dict | None = None
    event_slug: str | None = None
    course_slug: str | None = None
    related: list[ArticleCardOut] = Field(default_factory=list)


class ArticleListOut(ApiModel):
    items: list[ArticleCardOut]
    total: int
    page: int
    page_size: int
    has_more: bool
    categories: list[str]


class ContentVersionOut(ApiModel):
    """Fingerprint of the public content, polled by the rebuild pipeline."""

    version: str
    article_count: int
    # Courses and the public calendar are prerendered too, so a change to
    # either has to move the version or /learn and /calendar go stale.
    course_count: int = 0
    lesson_count: int = 0
    activity_count: int = 0
    latest_updated_at: str | None = None
    latest_published_at: str | None = None
    next_scheduled_at: str | None = None


class ArticleAdminOut(ApiModel):
    id: str
    slug: str
    category: str
    status: str
    title: LocalizedOut
    excerpt: LocalizedOut
    hero: dict | None = None
    body: list[dict] = Field(default_factory=list)
    seo: dict | None = None
    related_slugs: list[str] = Field(default_factory=list)
    event_slug: str | None = None
    course_slug: str | None = None
    featured: bool = False
    published_at: str | None = None
    updated_at: str | None = None
    author_name: str | None = None


class SecurityResultOut(ApiModel):
    passed: bool
    blocked: bool
    attempts_left: int


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
    id: str
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

    id: str
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

    id: str
    title: str
    description: str | None
    date: str
    start_time: str
    end_time: str
    is_attendance_event: bool
    is_holiday: bool
    venue_id: str | None
    attendance_code: str | None
    # Public calendar. Everything below is invisible to visitors until
    # `is_public` is turned on, which is off by default.
    is_public: bool = False
    public_slug: str | None = None
    title_en: str = ""
    summary_id: str = ""
    summary_en: str = ""
    # A JSON column added to an existing table reads back NULL on old rows.
    # 0007 backfills them, and these validators keep a row written by hand or
    # by an older deploy from turning a list response into a 500.
    public_description: list[dict] = Field(default_factory=list)
    images: list[dict] = Field(default_factory=list)
    links: list[dict] = Field(default_factory=list)
    kind: str = "weekly"
    price_amount: int | None = None

    @field_validator("public_description", "images", "links", mode="before")
    @classmethod
    def _null_is_empty(cls, value):
        return value if value is not None else []


# ---- Courses (admin CMS; lesson content is admin-only by decision) --------


class CourseIn(ApiModel):
    slug: str = Field(min_length=1, max_length=120)
    title: LocalizedIn
    summary: LocalizedIn = Field(default_factory=LocalizedIn)
    level: str = "beginner"
    progression: str = "linear"
    accent: str = Field(default="#ffc778", max_length=32)
    icon: str = Field(default="✍️", max_length=16)
    outcomes: list[dict] = Field(default_factory=list, max_length=12)
    sort_order: int = 0


class CourseModuleIn(ApiModel):
    # The id the frontend and `unlock_after_module` use. Stable across edits,
    # unlike the row id — renaming a module must not break a gate.
    content_id: str = Field(min_length=1, max_length=120)
    title: LocalizedIn
    summary: LocalizedIn = Field(default_factory=LocalizedIn)
    unlock_after_module: str | None = None
    sort_order: int = 0


class CourseItemIn(ApiModel):
    # Progress and certificates key on this. Changing it on an existing item
    # would orphan every learner's completion, so the API refuses.
    content_id: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=120)
    kind: str = "lesson"
    title: LocalizedIn
    minutes: int = Field(default=5, ge=0, le=600)
    video_url: str | None = Field(default=None, max_length=500)
    blocks: list[dict] = Field(default_factory=list)
    quiz: list[dict] | None = None
    tool: dict | None = None
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    completion: dict = Field(default_factory=lambda: {"kind": "manual"})
    is_published: bool = True
    sort_order: int = 0


class PublishIn(ApiModel):
    is_published: bool


class ReorderIn(ApiModel):
    """New order, as the ids to apply it to, first to last."""

    ids: list[str] = Field(min_length=1, max_length=200)


class GenerateSessionsIn(ApiModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")


EVENT_KINDS = ("weekly", "workshop", "showcase", "holiday")

# Shared by every slug an editor types — articles, activities, courses.
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ActivityIn(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    is_attendance_event: bool
    is_holiday: bool = False
    venue_id: str | None = None

    # ---- Public calendar (SPEC-CAL-03) ---------------------------------
    # Off by default, so an internal session can never reach the public
    # calendar because a field was left out of a request.
    is_public: bool = False
    public_slug: str | None = Field(default=None, max_length=120)
    title_en: str = Field(default="", max_length=200)
    summary_id: str = Field(default="", max_length=500)
    summary_en: str = Field(default="", max_length=500)
    public_description: list[dict] = Field(default_factory=list)
    images: list[dict] = Field(default_factory=list)
    links: list[dict] = Field(default_factory=list)
    kind: str = "weekly"
    price_amount: int | None = Field(default=None, ge=0)


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
    id: str
    activity_id: str
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
    id: str
    full_name: str
    email: str
    avatar_url: str | None
    whatsapp: str | None
    domicile: str | None
    instagram: str | None
    role: str
    is_member: bool
    membership_status: str
    member_since: str | None = None
    is_active: bool
    profile_completed: bool
    total_attendance: int
    last_attended_at: str | None
    joined_at: str


class UpdateMemberIn(ApiModel):
    is_active: bool | None = None
    # superadmin is env-only and can never be set here. Granting/revoking
    # "admin" is additionally restricted to superadmins in the router.
    role: str | None = Field(default=None, pattern=r"^(user|contributor|admin)$")


class AttendanceLogRowOut(ApiModel):
    id: str
    member_id: str
    member_name: str
    attended_at: str
    distance_m: float
    venue_name: str


class SessionSummaryOut(ApiModel):
    activity_id: str
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
    dormant_members: int = 0
    registered_members: int = 0
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
