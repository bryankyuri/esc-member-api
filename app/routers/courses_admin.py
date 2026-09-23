"""Course CMS — admin and superadmin only.

Articles are open to contributors; lessons are not (decision, 2026-09-23).
Course content decides what a certificate means, so the people who can change
it are the same people who can change anything else about the club.

Every write here bumps the parent course's `updated_at`, because that is what
`content_version` reads to decide whether the public site is stale. Modules and
items have no timestamp of their own, so a lesson edited without touching its
course would change the site and never trigger a rebuild.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.courses import (
    ITEM_KINDS,
    LEVELS,
    PROGRESSIONS,
    course_admin_out,
    item_admin_out,
    module_admin_out,
    touch,
)
from app.db import get_db
from app.deps import api_error, require_admin
from app.models import Course, CourseItem, CourseModule, LearningProgress
from app.schemas import (
    SLUG_RE,
    CourseIn,
    CourseItemIn,
    CourseModuleIn,
    PublishIn,
    ReorderIn,
)

router = APIRouter(
    prefix="/admin/courses",
    tags=["courses-admin"],
    dependencies=[Depends(require_admin)],
)


# ---- lookups -------------------------------------------------------------


def _course(db: Session, course_id: str) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise api_error(404, "unknown_course")
    return course


def _module(db: Session, module_id: str) -> CourseModule:
    module = db.get(CourseModule, module_id)
    if module is None:
        raise api_error(404, "unknown_module")
    return module


def _item(db: Session, item_id: str) -> CourseItem:
    item = db.get(CourseItem, item_id)
    if item is None:
        raise api_error(404, "unknown_item")
    return item


def _course_of_module(db: Session, module: CourseModule) -> Course:
    return _course(db, module.course_id)


def _course_of_item(db: Session, item: CourseItem) -> Course:
    return _course_of_module(db, _module(db, item.module_id))


# ---- validation ----------------------------------------------------------


def _check_course(db: Session, payload: CourseIn, exclude_id: str | None) -> None:
    if not SLUG_RE.match(payload.slug):
        raise api_error(422, "invalid_slug", "lowercase letters, digits and hyphens")
    if payload.level not in LEVELS:
        raise api_error(422, "invalid_level", f"one of {', '.join(LEVELS)}")
    if payload.progression not in PROGRESSIONS:
        raise api_error(
            422, "invalid_progression", f"one of {', '.join(PROGRESSIONS)}"
        )
    clash = db.query(Course).filter(Course.slug == payload.slug)
    if exclude_id:
        clash = clash.filter(Course.id != exclude_id)
    if clash.first() is not None:
        raise api_error(409, "slug_taken")


def _check_content_id(db: Session, content_id: str, exclude_id: str | None) -> None:
    clash = db.query(CourseItem).filter(CourseItem.content_id == content_id)
    if exclude_id:
        clash = clash.filter(CourseItem.id != exclude_id)
    if clash.first() is not None:
        raise api_error(409, "content_id_taken")


# ---- courses -------------------------------------------------------------


@router.get("")
def list_courses(db: Session = Depends(get_db)):
    """Every course, published or not — this is the editor's list."""
    rows = db.query(Course).order_by(Course.sort_order, Course.created_at).all()
    return [course_admin_out(c) for c in rows]


@router.put("/reorder")
def reorder_courses(payload: ReorderIn, db: Session = Depends(get_db)):
    for position, course_id in enumerate(payload.ids):
        course = _course(db, course_id)
        course.sort_order = position
    db.commit()
    rows = db.query(Course).order_by(Course.sort_order, Course.created_at).all()
    return [course_admin_out(c) for c in rows]


@router.get("/{course_id}")
def get_course(course_id: str, db: Session = Depends(get_db)):
    return course_admin_out(_course(db, course_id))


@router.post("", status_code=201)
def create_course(payload: CourseIn, db: Session = Depends(get_db)):
    _check_course(db, payload, exclude_id=None)
    course = Course(
        slug=payload.slug,
        title_id=payload.title.id,
        title_en=payload.title.en,
        summary_id=payload.summary.id,
        summary_en=payload.summary.en,
        level=payload.level,
        progression=payload.progression,
        accent=payload.accent,
        icon=payload.icon,
        outcomes=payload.outcomes,
        sort_order=payload.sort_order,
        is_published=False,
    )
    db.add(course)
    db.commit()
    return course_admin_out(course)


@router.put("/{course_id}")
def update_course(course_id: str, payload: CourseIn, db: Session = Depends(get_db)):
    course = _course(db, course_id)
    _check_course(db, payload, exclude_id=course_id)
    course.slug = payload.slug
    course.title_id = payload.title.id
    course.title_en = payload.title.en
    course.summary_id = payload.summary.id
    course.summary_en = payload.summary.en
    course.level = payload.level
    course.progression = payload.progression
    course.accent = payload.accent
    course.icon = payload.icon
    course.outcomes = payload.outcomes
    course.sort_order = payload.sort_order
    touch(course)
    db.commit()
    return course_admin_out(course)


@router.put("/{course_id}/publish")
def set_published(course_id: str, payload: PublishIn, db: Session = Depends(get_db)):
    """Publishing a course puts it on /learn; unpublishing takes it off.

    An empty course cannot be published — a visitor would land on a page with
    nothing to do, and a certificate for it would mean nothing.
    """
    course = _course(db, course_id)
    if payload.is_published:
        items = [i for m in course.modules for i in m.items if i.is_published]
        if not items:
            raise api_error(422, "course_empty", "add a published item first")
    course.is_published = payload.is_published
    touch(course)
    db.commit()
    return course_admin_out(course)


@router.delete("/{course_id}", status_code=204)
def delete_course(course_id: str, db: Session = Depends(get_db)):
    """Only while nobody has learned from it.

    Deleting a course whose items people have completed would leave orphaned
    progress and certificates that verify against nothing. Unpublish instead:
    the course leaves the site and every certificate still resolves.
    """
    course = _course(db, course_id)
    learned = (
        db.query(LearningProgress)
        .filter(LearningProgress.course_slug == course.slug)
        .first()
    )
    if learned is not None:
        raise api_error(
            409, "course_in_use", "learners have progress here; unpublish instead"
        )
    db.delete(course)
    db.commit()


# ---- modules -------------------------------------------------------------


@router.post("/{course_id}/modules", status_code=201)
def create_module(
    course_id: str, payload: CourseModuleIn, db: Session = Depends(get_db)
):
    course = _course(db, course_id)
    module = CourseModule(
        course_id=course.id,
        content_id=payload.content_id,
        title_id=payload.title.id,
        title_en=payload.title.en,
        summary_id=payload.summary.id,
        summary_en=payload.summary.en,
        unlock_after_module=payload.unlock_after_module,
        sort_order=payload.sort_order,
    )
    db.add(module)
    touch(course)
    db.commit()
    return module_admin_out(module)


@router.put("/modules/{module_id}")
def update_module(
    module_id: str, payload: CourseModuleIn, db: Session = Depends(get_db)
):
    module = _module(db, module_id)
    module.content_id = payload.content_id
    module.title_id = payload.title.id
    module.title_en = payload.title.en
    module.summary_id = payload.summary.id
    module.summary_en = payload.summary.en
    module.unlock_after_module = payload.unlock_after_module
    module.sort_order = payload.sort_order
    touch(_course_of_module(db, module))
    db.commit()
    return module_admin_out(module)


@router.delete("/modules/{module_id}", status_code=204)
def delete_module(module_id: str, db: Session = Depends(get_db)):
    module = _module(db, module_id)
    course = _course_of_module(db, module)
    if module.items:
        raise api_error(409, "module_not_empty", "delete or move its items first")
    db.delete(module)
    touch(course)
    db.commit()


@router.put("/{course_id}/modules/reorder")
def reorder_modules(
    course_id: str, payload: ReorderIn, db: Session = Depends(get_db)
):
    course = _course(db, course_id)
    for position, module_id in enumerate(payload.ids):
        module = _module(db, module_id)
        if module.course_id != course.id:
            raise api_error(422, "module_not_in_course")
        module.sort_order = position
    touch(course)
    db.commit()
    return course_admin_out(course)


# ---- items ---------------------------------------------------------------


@router.post("/modules/{module_id}/items", status_code=201)
def create_item(
    module_id: str, payload: CourseItemIn, db: Session = Depends(get_db)
):
    module = _module(db, module_id)
    if payload.kind not in ITEM_KINDS:
        raise api_error(422, "invalid_kind", f"one of {', '.join(ITEM_KINDS)}")
    _check_content_id(db, payload.content_id, exclude_id=None)
    item = CourseItem(
        module_id=module.id,
        content_id=payload.content_id,
        slug=payload.slug,
        kind=payload.kind,
        title_id=payload.title.id,
        title_en=payload.title.en,
        minutes=payload.minutes,
        video_url=payload.video_url,
        blocks=payload.blocks,
        quiz=payload.quiz,
        tool=payload.tool,
        prerequisites=payload.prerequisites,
        completion=payload.completion,
        is_published=payload.is_published,
        sort_order=payload.sort_order,
    )
    db.add(item)
    touch(_course_of_module(db, module))
    db.commit()
    return item_admin_out(item)


@router.put("/items/{item_id}")
def update_item(item_id: str, payload: CourseItemIn, db: Session = Depends(get_db)):
    """Everything is editable except the content id.

    That id is what `learning_progress` and certificate completion checks are
    keyed on. Changing it would quietly un-complete the lesson for everyone who
    has already finished it, so the API refuses rather than doing it.
    """
    item = _item(db, item_id)
    if payload.kind not in ITEM_KINDS:
        raise api_error(422, "invalid_kind", f"one of {', '.join(ITEM_KINDS)}")
    if payload.content_id != item.content_id:
        raise api_error(
            422, "content_id_immutable", "learner progress is keyed on this id"
        )
    item.slug = payload.slug
    item.kind = payload.kind
    item.title_id = payload.title.id
    item.title_en = payload.title.en
    item.minutes = payload.minutes
    item.video_url = payload.video_url
    item.blocks = payload.blocks
    item.quiz = payload.quiz
    item.tool = payload.tool
    item.prerequisites = payload.prerequisites
    item.completion = payload.completion
    item.is_published = payload.is_published
    item.sort_order = payload.sort_order
    touch(_course_of_item(db, item))
    db.commit()
    return item_admin_out(item)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: str, db: Session = Depends(get_db)):
    """Only while nobody has completed it — unpublish otherwise.

    An unpublished item disappears from the course and stops counting towards
    a certificate, which is what "remove this lesson" almost always means.
    Deleting one that people finished would strand their progress rows.
    """
    item = _item(db, item_id)
    course = _course_of_item(db, item)
    completed = (
        db.query(LearningProgress)
        .filter(LearningProgress.item_id == item.content_id)
        .first()
    )
    if completed is not None:
        raise api_error(
            409, "item_in_use", "learners have completed this; unpublish instead"
        )
    db.delete(item)
    touch(course)
    db.commit()


@router.put("/modules/{module_id}/items/reorder")
def reorder_items(module_id: str, payload: ReorderIn, db: Session = Depends(get_db)):
    module = _module(db, module_id)
    for position, item_id in enumerate(payload.ids):
        item = _item(db, item_id)
        if item.module_id != module.id:
            raise api_error(422, "item_not_in_module")
        item.sort_order = position
    touch(_course_of_module(db, module))
    db.commit()
    return module_admin_out(module)
