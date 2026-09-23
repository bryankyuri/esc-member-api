from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.ids import new_id


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    google_sub: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String)
    # Learner profile: the two fields a certificate needs. Separate from the
    # member profile below (whatsapp/domicile/instagram), which is only
    # required for the member area — a plain user can earn a certificate.
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String, nullable=True)
    domicile: Mapped[str | None] = mapped_column(String, nullable=True)
    instagram: Mapped[str | None] = mapped_column(String, nullable=True)
    # What this account may *manage*: "user" | "contributor" | "admin".
    # "superadmin" is an env overlay and is never stored.
    # Membership is a different question entirely — see deps.is_member().
    role: Mapped[str] = mapped_column(String, default="user")
    profile_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Membership proof gate (security question), before profile completion.
    # Existing production members are grandfathered to True by the migration.
    security_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    security_attempts: Mapped[int] = mapped_column(Integer, default=0)
    security_attempt_date: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Membership facts. attendance_* are a denormalised cache of the attendance
    # table, maintained on check-in, so membership status costs no aggregate
    # query. scripts/recount_attendance.py rebuilds them if they ever drift.
    member_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_attended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_attended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attendance_count: Mapped[int] = mapped_column(Integer, default=0)

    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String)
    address: Mapped[str] = mapped_column(String, default="")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float, default=100)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[str] = mapped_column(String, index=True)  # YYYY-MM-DD
    start_time: Mapped[str] = mapped_column(String)  # HH:MM
    end_time: Mapped[str] = mapped_column(String)  # HH:MM
    is_attendance_event: Mapped[bool] = mapped_column(Boolean, default=True)
    is_holiday: Mapped[bool] = mapped_column(Boolean, default=False)
    # Off by default: an activity is internal until someone decides otherwise,
    # so a private session cannot leak onto the public calendar by accident.
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    # Public-calendar extras, ignored by the member app.
    # The public URL. Nullable: auto-created weekly sessions have no public
    # identity until an admin gives them one, and the serialiser falls back to
    # a date-derived slug so a link always resolves.
    public_slug: Mapped[str | None] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    title_en: Mapped[str] = mapped_column(String, default="")
    summary_id: Mapped[str] = mapped_column(Text, default="")
    summary_en: Mapped[str] = mapped_column(Text, default="")
    public_description: Mapped[list] = mapped_column(JSON, default=list)
    images: Mapped[list] = mapped_column(JSON, default=list)
    links: Mapped[list] = mapped_column(JSON, default=list)
    kind: Mapped[str] = mapped_column(String, default="weekly")
    price_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("venues.id"), nullable=True
    )
    attendance_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    venue: Mapped[Venue | None] = relationship()


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("user_id", "activity_id", name="uq_attendance_user_activity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    activity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activities.id"), index=True
    )
    attended_at: Mapped[datetime] = mapped_column(DateTime)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)

    user: Mapped[User] = relationship()
    activity: Mapped[Activity] = relationship()


class LearningProgress(Base):
    """One row per completed lesson item.

    Keyed by the CMS item id (a content slug), not a foreign key: course
    content lives in the frontend's JSON today and moves to its own tables in
    Phase 5. Progress must survive that move untouched, so it deliberately does
    not reference a courses table.
    """

    __tablename__ = "learning_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_progress_user_item"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    course_slug: Mapped[str] = mapped_column(String, index=True)
    item_id: Mapped[str] = mapped_column(String)
    completed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # manual | timer | quiz | override — how they finished it.
    via: Mapped[str] = mapped_column(String, default="manual")

    user: Mapped[User] = relationship()


class LearningDraft(Base):
    """Free-writing from a timer exercise. Personal notes, capped in size."""

    __tablename__ = "learning_drafts"
    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_draft_user_item"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    item_id: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship()


class Certificate(Base):
    """Proof that someone completed a course.

    The name and email are **snapshots**: a certificate already in someone's
    hands must not silently change when they later edit their profile.
    """

    __tablename__ = "certificates"
    __table_args__ = (
        UniqueConstraint("user_id", "course_slug", name="uq_certificate_user_course"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    course_slug: Mapped[str] = mapped_column(String, index=True)
    # Short, human-readable, and random — printed on the certificate and
    # typeable by hand. Not a UUID, and not sequential: nobody should be able
    # to walk through other people's certificates.
    code: Mapped[str] = mapped_column(String, unique=True, index=True)
    first_name_snapshot: Mapped[str] = mapped_column(String)
    last_name_snapshot: Mapped[str] = mapped_column(String)
    email_snapshot: Mapped[str] = mapped_column(String)
    issued_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship()


class Course(Base):
    """A course on the public site. Bilingual, like every content table."""

    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    title_id: Mapped[str] = mapped_column(String)
    title_en: Mapped[str] = mapped_column(String, default="")
    summary_id: Mapped[str] = mapped_column(Text, default="")
    summary_en: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String, default="beginner")
    # linear = finish an item to open the next; free = jump anywhere.
    progression: Mapped[str] = mapped_column(String, default="linear")
    accent: Mapped[str] = mapped_column(String, default="#ffc778")
    icon: Mapped[str] = mapped_column(String, default="✍️")
    outcomes: Mapped[list] = mapped_column(JSON, default=list)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    modules: Mapped[list["CourseModule"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="CourseModule.sort_order",
    )


class CourseModule(Base):
    __tablename__ = "course_modules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id"), index=True
    )
    # Exposed to the frontend and referenced by `unlock_after_module` — stable
    # across edits, unlike the row id.
    content_id: Mapped[str] = mapped_column(String)
    title_id: Mapped[str] = mapped_column(String)
    title_en: Mapped[str] = mapped_column(String, default="")
    summary_id: Mapped[str] = mapped_column(Text, default="")
    summary_en: Mapped[str] = mapped_column(Text, default="")
    unlock_after_module: Mapped[str | None] = mapped_column(String, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    course: Mapped[Course] = relationship(back_populates="modules")
    items: Mapped[list["CourseItem"]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        order_by="CourseItem.sort_order",
    )


class CourseItem(Base):
    """One lesson, exercise or quiz.

    `content_id` is what the public site and `learning_progress` use. It is
    deliberately NOT the row id: progress rows written before courses moved
    into the database refer to these ids ("lyr-1"), and a learner must not lose
    a finished lesson because the content moved.
    """

    __tablename__ = "course_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    module_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("course_modules.id"), index=True
    )
    content_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    slug: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="lesson")
    title_id: Mapped[str] = mapped_column(String)
    title_en: Mapped[str] = mapped_column(String, default="")
    minutes: Mapped[int] = mapped_column(Integer, default=5)
    video_url: Mapped[str | None] = mapped_column(String, nullable=True)
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    quiz: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tool: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prerequisites: Mapped[list] = mapped_column(JSON, default=list)
    completion: Mapped[dict] = mapped_column(JSON, default=dict)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    module: Mapped[CourseModule] = relationship(back_populates="items")


class Article(Base):
    """A community post on the public site.

    Bilingual by construction: every visitor-facing string is stored for both
    languages, matching `public-frontend/src/content/types.ts` so the frontend
    renderer needs no translation layer.

    Three states rather than a boolean, because taking a published article down
    is not the same as never having published it: `unpublished` keeps the row
    and the slug, so re-publishing restores the same URL.
    """

    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    category: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="draft", index=True)

    title_id: Mapped[str] = mapped_column(String)
    title_en: Mapped[str] = mapped_column(String, default="")
    excerpt_id: Mapped[str] = mapped_column(Text, default="")
    excerpt_en: Mapped[str] = mapped_column(Text, default="")

    # Same JSON shapes the frontend already renders.
    hero: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    body: Mapped[list] = mapped_column(JSON, default=list)
    seo: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    related_slugs: Mapped[list] = mapped_column(JSON, default=list)

    author_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    # Cross-links into the rest of the site, by slug (content, not a FK).
    event_slug: Mapped[str | None] = mapped_column(String, nullable=True)
    course_slug: Mapped[str | None] = mapped_column(String, nullable=True)

    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    # Future-dated = scheduled: saved, but not public until its time.
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    author: Mapped[User | None] = relationship()


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
