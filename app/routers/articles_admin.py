"""Article CMS — contributors and up.

Contributors publish directly: no editorial queue (decision, 2026-09-23). What
they cannot touch is anything else in the dashboard, and that is enforced here
by `require_contributor`, not by hiding menu items.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.articles import CATEGORIES, STATUSES, admin_out
from app.db import get_db
from app.deps import api_error, require_contributor
from app.models import Article, User
from app.schemas import SLUG_RE, ArticleAdminOut, ArticleIn, ArticleStatusIn
from app.services import now_local

router = APIRouter(
    prefix="/admin/articles",
    tags=["articles-admin"],
    dependencies=[Depends(require_contributor)],
)


def _get(db: Session, article_id: str) -> Article:
    article = db.get(Article, article_id)
    if article is None:
        raise api_error(404, "unknown_article")
    return article


def _check_slug(db: Session, slug: str, exclude_id: str | None = None) -> None:
    if not SLUG_RE.match(slug):
        raise api_error(422, "invalid_slug", "lowercase letters, digits and hyphens")
    clash = db.query(Article).filter(Article.slug == slug)
    if exclude_id:
        clash = clash.filter(Article.id != exclude_id)
    if clash.first() is not None:
        raise api_error(409, "slug_taken")


def _apply(article: Article, payload: ArticleIn) -> None:
    article.slug = payload.slug
    article.category = payload.category
    article.title_id = payload.title.id
    article.title_en = payload.title.en
    article.excerpt_id = payload.excerpt.id
    article.excerpt_en = payload.excerpt.en
    article.hero = payload.hero
    article.body = payload.body
    article.seo = payload.seo
    article.related_slugs = payload.related_slugs
    article.event_slug = payload.event_slug
    article.course_slug = payload.course_slug
    article.featured = payload.featured


@router.get("", response_model=list[ArticleAdminOut])
def list_articles(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if status is not None and status not in STATUSES:
        raise api_error(422, "invalid_status")
    query = db.query(Article).order_by(Article.updated_at.desc())
    if status:
        query = query.filter(Article.status == status)
    return [admin_out(a) for a in query.all()]


@router.get("/{article_id}", response_model=ArticleAdminOut)
def get_article(article_id: str, db: Session = Depends(get_db)):
    return admin_out(_get(db, article_id))


@router.post("", response_model=ArticleAdminOut, status_code=201)
def create_article(
    payload: ArticleIn,
    actor: User = Depends(require_contributor),
    db: Session = Depends(get_db),
):
    if payload.category not in CATEGORIES:
        raise api_error(422, "invalid_category")
    _check_slug(db, payload.slug)

    article = Article(author_id=actor.id, status="draft")
    _apply(article, payload)
    db.add(article)
    db.commit()
    return admin_out(article)


@router.put("/{article_id}", response_model=ArticleAdminOut)
def update_article(
    article_id: str, payload: ArticleIn, db: Session = Depends(get_db)
):
    if payload.category not in CATEGORIES:
        raise api_error(422, "invalid_category")
    article = _get(db, article_id)
    _check_slug(db, payload.slug, exclude_id=article_id)
    _apply(article, payload)
    db.commit()
    return admin_out(article)


@router.put("/{article_id}/status", response_model=ArticleAdminOut)
def set_status(
    article_id: str, payload: ArticleStatusIn, db: Session = Depends(get_db)
):
    """draft → published → unpublished, and back again.

    Publishing stamps `published_at` unless the author scheduled one. An
    article that is taken down keeps its slug and its date, so re-publishing
    restores the same URL rather than minting a new one.
    """
    if payload.status not in STATUSES:
        raise api_error(422, "invalid_status")
    article = _get(db, article_id)

    if payload.status == "published":
        if not article.title_id.strip():
            raise api_error(422, "title_required")
        if payload.published_at is not None:
            article.published_at = payload.published_at
        elif article.published_at is None:
            article.published_at = now_local(db)

    article.status = payload.status
    db.commit()

    # No build is triggered from here. This change moves
    # `GET /public/content-version`, and the rebuild pipeline polls that — so a
    # rebuild costs build minutes only when the public content really differs,
    # and publishing never depends on this API reaching Cloudflare.
    return admin_out(article)


@router.delete("/{article_id}", status_code=204)
def delete_article(article_id: str, db: Session = Depends(get_db)):
    """Hard delete, for drafts that were a mistake.

    Taking a *published* article off the site is `status=unpublished`, which
    keeps the slug so the URL can come back.
    """
    article = _get(db, article_id)
    db.delete(article)
    db.commit()
