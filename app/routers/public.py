"""Public content: no authentication, cacheable, safe to expose.

Everything here is readable by anyone, so it must never leak what only members
should see — attendance codes, venue coordinates, member names or emails. The
public feed shows counts, not people.
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.articles import (
    CATEGORIES,
    card_out,
    detail_out,
    public_query,
    related_articles,
)
from app.content_version import content_version
from app.courses import course_card, course_out, published_courses
from app.db import get_db
from app.deps import api_error
from app.models import Activity, Article, Course
from app.schemas import ArticleDetailOut, ArticleListOut, ContentVersionOut
from app.services import now_local, public_activity_out, public_slug

router = APIRouter(prefix="/public", tags=["public"])

PAGE_SIZE = 12
# Short enough that an edit appears quickly, long enough for Cloudflare to
# absorb the traffic. Articles are also served from prerendered HTML.
CACHE_CONTROL = "public, max-age=60"


@router.get("/content-version", response_model=ContentVersionOut)
def get_content_version(response: Response, db: Session = Depends(get_db)):
    """What the public site *should* be showing, as a fingerprint.

    The rebuild pipeline polls this and compares it with the version baked
    into the deployed site (`/content-version.json`). If they differ, content
    changed and a rebuild is worth its minutes; if not, nothing happens.

    Pull rather than push: publishing an article never depends on this API
    being able to reach Cloudflare, and a missed call cannot leave the site
    permanently stale — the next poll notices.
    """
    # Short cache: this is polled on a schedule, and being a few seconds stale
    # only delays a rebuild by one interval.
    response.headers["Cache-Control"] = "public, max-age=30"
    return content_version(db, now_local(db))


@router.get("/courses")
def list_courses(response: Response, db: Session = Depends(get_db)):
    """Published courses, without their lesson bodies."""
    response.headers["Cache-Control"] = CACHE_CONTROL
    return [course_card(c) for c in published_courses(db)]


@router.get("/courses/{slug}")
def get_course(slug: str, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = CACHE_CONTROL
    course = (
        db.query(Course)
        .filter(Course.slug == slug, Course.is_published.is_(True))
        .first()
    )
    if course is None:
        raise api_error(404, "unknown_course")
    return course_out(course)


@router.get("/activities")
def list_public_activities(
    response: Response,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """The community calendar.

    Only activities an admin marked public, and only the fields a visitor
    needs: **never** the attendance code, and never the venue's coordinates —
    the address and a map link are enough to find the place.
    """
    response.headers["Cache-Control"] = CACHE_CONTROL
    query = db.query(Activity).filter(Activity.is_public.is_(True))
    if from_:
        query = query.filter(Activity.date >= from_)
    if to:
        query = query.filter(Activity.date <= to)

    return [
        public_activity_out(db, activity)
        for activity in query.order_by(Activity.date).all()
    ]


@router.get("/activities/{slug}")
def get_public_activity(slug: str, response: Response, db: Session = Depends(get_db)):
    """One activity's detail page.

    Matches the admin-set slug, or the date-derived fallback for activities
    nobody has named — both are links that appear on the calendar, so both
    have to resolve.
    """
    response.headers["Cache-Control"] = CACHE_CONTROL
    rows = db.query(Activity).filter(Activity.is_public.is_(True)).all()
    for activity in rows:
        if public_slug(activity) == slug:
            return public_activity_out(db, activity)
    raise api_error(404, "unknown_activity")


@router.get("/articles", response_model=ArticleListOut)
def list_articles(
    response: Response,
    page: int = Query(default=1, ge=1),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = CACHE_CONTROL
    if category is not None and category not in CATEGORIES:
        raise api_error(404, "unknown_category")

    now = now_local(db)
    query = public_query(db, now)
    if category:
        query = query.filter(Article.category == category)

    total = query.count()
    rows = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return {
        "items": [card_out(a) for a in rows],
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
        "has_more": (page - 1) * PAGE_SIZE + len(rows) < total,
        "categories": list(CATEGORIES),
    }


@router.get("/articles/{slug}", response_model=ArticleDetailOut)
def get_article(slug: str, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = CACHE_CONTROL
    now = now_local(db)
    article = public_query(db, now).filter(Article.slug == slug).first()
    if article is None:
        # Drafts, scheduled posts and unpublished articles are all simply
        # "not here" — the status is nobody's business.
        raise api_error(404, "unknown_article")
    return detail_out(article, related_articles(db, article, now))
