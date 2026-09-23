"""articles (community posts) with draft / published / unpublished

Revision ID: 0006_articles
Revises: 0005_certs
Create Date: 2026-09-23

Phase 4 of PLATFORM-V2-SPEC.md (SPEC-ART-01 … SPEC-ART-08).

Articles are the first content type owned by the API rather than by frontend
JSON, so contributors can publish without a deploy.

`status` is three-valued on purpose. Unpublishing is not deleting: the row and
the slug stay, so re-publishing restores the same URL — and the next build must
remove the article's prerendered file and sitemap entry, or a page taken down
would remain reachable as a stale static file.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_articles"
down_revision = "0005_certs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("title_id", sa.String(), nullable=False),
        sa.Column("title_en", sa.String(), nullable=False, server_default=""),
        sa.Column("excerpt_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("excerpt_en", sa.Text(), nullable=False, server_default=""),
        sa.Column("hero", sa.JSON(), nullable=True),
        sa.Column("body", sa.JSON(), nullable=True),
        sa.Column("seo", sa.JSON(), nullable=True),
        sa.Column("related_slugs", sa.JSON(), nullable=True),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_slug", sa.String(), nullable=True),
        sa.Column("course_slug", sa.String(), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_articles_slug", "articles", ["slug"], unique=True)
    op.create_index("ix_articles_status", "articles", ["status"])
    op.create_index("ix_articles_category", "articles", ["category"])


def downgrade() -> None:
    op.drop_table("articles")
