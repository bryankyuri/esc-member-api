"""Article visibility, serialisation, and related-article scoring.

Kept out of the router so the rules are readable in one place and testable
without HTTP.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Article

CATEGORIES = ("kabar", "catatan-sesi", "tips-menulis", "cerita-anggota")
STATUSES = ("draft", "published", "unpublished")

# Related-article scoring (SPEC-ART-04). Deterministic, so the same content
# always produces the same list — a prerendered page and a live page must not
# disagree about what is related.
SCORE_SAME_CATEGORY = 3
SCORE_SHARED_COURSE = 2
SCORE_SHARED_EVENT = 2
SCORE_RECENT = 1
RECENT_DAYS = 60
RELATED_COUNT = 3


def is_public(article: Article, now: datetime) -> bool:
    """Published, and its publish time has actually arrived.

    A future `published_at` is a scheduled post: saved, but not yet anyone
    else's business.
    """
    if article.status != "published":
        return False
    return article.published_at is not None and article.published_at <= now


def public_query(db: Session, now: datetime):
    return (
        db.query(Article)
        .filter(
            Article.status == "published",
            Article.published_at.isnot(None),
            Article.published_at <= now,
        )
        .order_by(Article.published_at.desc())
    )


def localized(value_id: str, value_en: str) -> dict:
    """Both languages, with a fallback so a missing translation never blanks
    the page — the frontend's `pick()` expects exactly this shape."""
    return {"id": value_id or value_en or "", "en": value_en or value_id or ""}


def card_out(article: Article) -> dict:
    """List/card shape: everything an index needs, and no body."""
    return {
        "slug": article.slug,
        "category": article.category,
        "title": localized(article.title_id, article.title_en),
        "excerpt": localized(article.excerpt_id, article.excerpt_en),
        "hero": article.hero,
        "featured": bool(article.featured),
        "published_at": (
            article.published_at.isoformat() if article.published_at else None
        ),
        "updated_at": article.updated_at.isoformat() if article.updated_at else None,
        "reading_minutes": reading_minutes(article),
        "author_name": article.author.full_name if article.author else "Tim ESC",
    }


def detail_out(article: Article, related: list[Article]) -> dict:
    return {
        **card_out(article),
        "body": article.body or [],
        "seo": article.seo,
        "event_slug": article.event_slug,
        "course_slug": article.course_slug,
        "related": [card_out(r) for r in related],
    }


def admin_out(article: Article) -> dict:
    """Everything, including what is not public yet."""
    return {
        "id": article.id,
        "slug": article.slug,
        "category": article.category,
        "status": article.status,
        "title": localized(article.title_id, article.title_en),
        "excerpt": localized(article.excerpt_id, article.excerpt_en),
        "hero": article.hero,
        "body": article.body or [],
        "seo": article.seo,
        "related_slugs": article.related_slugs or [],
        "event_slug": article.event_slug,
        "course_slug": article.course_slug,
        "featured": bool(article.featured),
        "published_at": (
            article.published_at.isoformat() if article.published_at else None
        ),
        "updated_at": article.updated_at.isoformat() if article.updated_at else None,
        "author_name": article.author.full_name if article.author else None,
    }


def reading_minutes(article: Article) -> int:
    """Rough reading time from the body blocks — 200 words a minute."""
    words = 0
    for block in article.body or []:
        text = block.get("text") or {}
        words += len(str(text.get("id") or text.get("en") or "").split())
        for item in block.get("items") or []:
            words += len(str(item.get("id") or item.get("en") or "").split())
    return max(1, round(words / 200))


def related_articles(
    db: Session, article: Article, now: datetime, limit: int = RELATED_COUNT
) -> list[Article]:
    """Manual picks first, then scoring, then recency as a top-up."""
    candidates = [a for a in public_query(db, now).all() if a.id != article.id]
    by_slug = {a.slug: a for a in candidates}

    chosen: list[Article] = []
    for slug in article.related_slugs or []:
        picked = by_slug.get(slug)
        if picked is not None and picked not in chosen:
            chosen.append(picked)

    def score(candidate: Article) -> tuple[int, str]:
        points = 0
        if candidate.category == article.category:
            points += SCORE_SAME_CATEGORY
        if candidate.course_slug and candidate.course_slug == article.course_slug:
            points += SCORE_SHARED_COURSE
        if candidate.event_slug and candidate.event_slug == article.event_slug:
            points += SCORE_SHARED_EVENT
        if (
            candidate.published_at
            and (now - candidate.published_at).days <= RECENT_DAYS
        ):
            points += SCORE_RECENT
        # Newest first within the same score, and the slug keeps it stable.
        stamp = candidate.published_at.isoformat() if candidate.published_at else ""
        return (points, stamp)

    ranked = sorted(
        (c for c in candidates if c not in chosen), key=score, reverse=True
    )
    chosen.extend(ranked)
    return chosen[:limit]
