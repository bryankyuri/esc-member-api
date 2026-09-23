"""Course serialisation — shaped exactly like the frontend already expects.

`public-frontend/src/content/types.ts` was written before this table existed,
and these functions match it deliberately: the Learn pages, the unlock rules
and the prerender script all keep working when the data starts arriving from
here instead of from JSON.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Course, CourseItem, CourseModule

LEVELS = ("beginner", "intermediate")
PROGRESSIONS = ("linear", "free")
ITEM_KINDS = ("lesson", "exercise", "quiz")


def localized(value_id: str, value_en: str) -> dict:
    return {"id": value_id or value_en or "", "en": value_en or value_id or ""}


def item_out(item: CourseItem, *, body: bool = True) -> dict:
    """`id` is the content id — what progress and certificates key on.

    `body=False` gives the stub the list view needs: enough to compute progress
    and unlock state, without shipping every lesson's text to a page that only
    draws progress bars. The shape stays the same so the frontend's `Course`
    type covers both.
    """
    stub = {
        "id": item.content_id,
        "slug": item.slug,
        "kind": item.kind,
        "title": localized(item.title_id, item.title_en),
        "minutes": item.minutes,
        "prerequisites": item.prerequisites or [],
        "completion": item.completion or {"kind": "manual"},
        "blocks": [],
    }
    if not body:
        return stub
    return {
        **stub,
        "videoUrl": item.video_url,
        "blocks": item.blocks or [],
        "quiz": item.quiz,
        "tool": item.tool,
    }


def module_out(module: CourseModule, *, body: bool = True) -> dict:
    return {
        "id": module.content_id,
        "title": localized(module.title_id, module.title_en),
        "summary": localized(module.summary_id, module.summary_en),
        "unlockAfterModule": module.unlock_after_module,
        "items": [
            item_out(i, body=body) for i in module.items if i.is_published
        ],
    }


def course_card(course: Course) -> dict:
    """The list view: the whole structure, none of the lesson text.

    It keeps `modules` because the Learn index draws a progress bar for every
    course, and progress is "how many of these item ids are done" — that needs
    the ids, and nothing else.
    """
    items = [i for m in course.modules for i in m.items if i.is_published]
    return {
        "slug": course.slug,
        "title": localized(course.title_id, course.title_en),
        "summary": localized(course.summary_id, course.summary_en),
        "level": course.level,
        "progression": course.progression,
        "accent": course.accent,
        "icon": course.icon,
        "outcomes": course.outcomes or [],
        "itemCount": len(items),
        "minutes": sum(i.minutes for i in items),
        "modules": [module_out(m, body=False) for m in course.modules],
    }


def course_out(course: Course) -> dict:
    return {
        **course_card(course),
        "modules": [module_out(m) for m in course.modules],
    }


def item_admin_out(item: CourseItem) -> dict:
    """The editor's view: the row id it addresses, and unpublished items too."""
    return {
        **item_out(item),
        "id": item.id,
        "contentId": item.content_id,
        "isPublished": item.is_published,
        "sortOrder": item.sort_order,
    }


def module_admin_out(module: CourseModule) -> dict:
    return {
        "id": module.id,
        "contentId": module.content_id,
        "title": localized(module.title_id, module.title_en),
        "summary": localized(module.summary_id, module.summary_en),
        "unlockAfterModule": module.unlock_after_module,
        "sortOrder": module.sort_order,
        "items": [item_admin_out(i) for i in module.items],
    }


def course_admin_out(course: Course) -> dict:
    items = [i for m in course.modules for i in m.items]
    return {
        "id": course.id,
        "slug": course.slug,
        "title": localized(course.title_id, course.title_en),
        "summary": localized(course.summary_id, course.summary_en),
        "level": course.level,
        "progression": course.progression,
        "accent": course.accent,
        "icon": course.icon,
        "outcomes": course.outcomes or [],
        "isPublished": course.is_published,
        "sortOrder": course.sort_order,
        "itemCount": len(items),
        "minutes": sum(i.minutes for i in items),
        "updatedAt": course.updated_at.isoformat() if course.updated_at else None,
        "modules": [module_admin_out(m) for m in course.modules],
    }


def touch(course: Course) -> None:
    """Mark the course changed.

    Modules and items carry no timestamp of their own, so every write to one
    bumps its course instead. `content_version` reads these timestamps to
    decide whether the public site needs rebuilding — without this, editing a
    lesson would change the site and never trigger a build.
    """
    course.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)


def published_courses(db: Session) -> list[Course]:
    return (
        db.query(Course)
        .filter(Course.is_published.is_(True))
        .order_by(Course.sort_order, Course.created_at)
        .all()
    )


def course_item_ids(db: Session, course_slug: str) -> list[str]:
    """Item ids that make up a course — the completion check for certificates.

    Replaces the generated `courses_manifest.json`: the database is now the
    source of truth, so the duplicate (and the script that kept it in step)
    are gone.
    """
    course = (
        db.query(Course)
        .filter(Course.slug == course_slug, Course.is_published.is_(True))
        .first()
    )
    if course is None:
        return []
    return [
        item.content_id
        for module in course.modules
        for item in module.items
        if item.is_published
    ]


def course_title(db: Session, course_slug: str, lang: str = "id") -> str:
    course = db.query(Course).filter(Course.slug == course_slug).first()
    if course is None:
        return course_slug
    title = localized(course.title_id, course.title_en)
    return title.get(lang) or title["id"]
