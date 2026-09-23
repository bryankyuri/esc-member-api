"""The fingerprint the rebuild pipeline polls.

Pull, not push: the API never calls Cloudflare. A cron Worker asks this endpoint
what the site *should* be showing, compares it with the version baked into the
deployed site (`/content-version.json`), and only spends build minutes when the
two differ. Publishing therefore never depends on the API being able to reach
Cloudflare, and a missed poll cannot leave the site permanently stale — the next
one notices.

It has to cover everything that is prerendered, which since Phase 5 is three
things, not one:

  * **articles** — `/artikel` and every article page
  * **courses**  — `/learn` and every lesson page
  * **activities** — the public calendar

and the three ways each of them changes:

  * something is published or taken down  → a count moves
  * something published is edited         → a `latest_updated` moves
  * a **scheduled** article falls due     → count and `latest_published` move
    with no row written at all, which is exactly the case a "did any row
    change?" check would miss

Drafts, unpublished courses and internal activities are deliberately invisible
here: editing one changes nothing a visitor can see, so it must not cost a
rebuild.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy.orm import Session

from app.articles import public_query
from app.courses import published_courses
from app.models import Activity, Article


def _stamp(value: datetime | None) -> str:
    return value.isoformat() if value else "-"


def content_version(db: Session, now: datetime) -> dict:
    articles = public_query(db, now).all()
    article_updated = max(
        (a.updated_at for a in articles if a.updated_at), default=None
    )
    article_published = max(
        (a.published_at for a in articles if a.published_at), default=None
    )

    # When the next scheduled post falls due — so the poller knows a change is
    # coming even though nothing has changed yet.
    upcoming = (
        db.query(Article)
        .filter(
            Article.status == "published",
            Article.published_at.isnot(None),
            Article.published_at > now,
        )
        .order_by(Article.published_at)
        .first()
    )

    courses = published_courses(db)
    course_updated = max((c.updated_at for c in courses if c.updated_at), default=None)
    # Items carry no timestamp of their own, so the admin CMS touches the parent
    # course on every module/item write (see `app/routers/courses_admin.py`).
    # The published-item count is the belt to that braces: unpublishing a single
    # lesson moves the fingerprint even if a future code path forgets to touch.
    item_count = sum(
        1 for c in courses for m in c.modules for i in m.items if i.is_published
    )

    activities = db.query(Activity).filter(Activity.is_public.is_(True)).all()
    activity_updated = max(
        (a.updated_at for a in activities if a.updated_at), default=None
    )

    fingerprint = "|".join(
        [
            str(len(articles)),
            _stamp(article_updated),
            _stamp(article_published),
            str(len(courses)),
            str(item_count),
            _stamp(course_updated),
            str(len(activities)),
            _stamp(activity_updated),
        ]
    )
    return {
        "version": hashlib.sha256(fingerprint.encode()).hexdigest()[:16],
        "article_count": len(articles),
        "course_count": len(courses),
        "lesson_count": item_count,
        "activity_count": len(activities),
        "latest_updated_at": _stamp(article_updated) if article_updated else None,
        "latest_published_at": _stamp(article_published) if article_published else None,
        "next_scheduled_at": (
            upcoming.published_at.isoformat()
            if upcoming and upcoming.published_at
            else None
        ),
    }
