"""courses in the database, and activities on the public calendar

Revision ID: 0007_courses
Revises: 0006_articles
Create Date: 2026-09-24

Phase 5 of PLATFORM-V2-SPEC.md (SPEC-CAL-03, SPEC-CMS-01, SPEC-CMS-02).

Course content moves out of the frontend's JSON so lessons can be edited
without a deploy, and activities gain the fields the public calendar needs.

Two deliberate choices:

* `course_items.content_id` is the id the public site and `learning_progress`
  use — not the row id. Progress written while courses lived in JSON refers to
  ids like "lyr-1", and nobody may lose a finished lesson because the content
  moved house.
* `activities.is_public` defaults to **false**. An activity is internal until
  someone says otherwise, so a private session cannot appear on the public
  calendar by accident.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_courses"
down_revision = "0006_articles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title_id", sa.String(), nullable=False),
        sa.Column("title_en", sa.String(), nullable=False, server_default=""),
        sa.Column("summary_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary_en", sa.Text(), nullable=False, server_default=""),
        sa.Column("level", sa.String(), nullable=False, server_default="beginner"),
        sa.Column("progression", sa.String(), nullable=False, server_default="linear"),
        sa.Column("accent", sa.String(), nullable=False, server_default="#ffc778"),
        sa.Column("icon", sa.String(), nullable=False, server_default="✍️"),
        sa.Column("outcomes", sa.JSON(), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_courses_slug", "courses", ["slug"], unique=True)

    op.create_table(
        "course_modules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "course_id", sa.String(36), sa.ForeignKey("courses.id"), nullable=False
        ),
        sa.Column("content_id", sa.String(), nullable=False),
        sa.Column("title_id", sa.String(), nullable=False),
        sa.Column("title_en", sa.String(), nullable=False, server_default=""),
        sa.Column("summary_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary_en", sa.Text(), nullable=False, server_default=""),
        sa.Column("unlock_after_module", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_course_modules_course_id", "course_modules", ["course_id"])

    op.create_table(
        "course_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "module_id",
            sa.String(36),
            sa.ForeignKey("course_modules.id"),
            nullable=False,
        ),
        sa.Column("content_id", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="lesson"),
        sa.Column("title_id", sa.String(), nullable=False),
        sa.Column("title_en", sa.String(), nullable=False, server_default=""),
        sa.Column("minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("video_url", sa.String(), nullable=True),
        sa.Column("blocks", sa.JSON(), nullable=True),
        sa.Column("quiz", sa.JSON(), nullable=True),
        sa.Column("tool", sa.JSON(), nullable=True),
        sa.Column("prerequisites", sa.JSON(), nullable=True),
        sa.Column("completion", sa.JSON(), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_course_items_module_id", "course_items", ["module_id"])
    op.create_index(
        "ix_course_items_content_id", "course_items", ["content_id"], unique=True
    )

    with op.batch_alter_table("activities") as batch:
        batch.add_column(
            sa.Column("is_public", sa.Boolean(), nullable=False, server_default="0")
        )
        # The public URL. Nullable because the weekly session rows created
        # automatically have no public identity until an admin gives them one;
        # the serialiser falls back to a date-derived slug so a link always works.
        batch.add_column(sa.Column("public_slug", sa.String(), nullable=True))
        batch.add_column(
            sa.Column("title_en", sa.String(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("summary_id", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("summary_en", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("public_description", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("images", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("links", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("kind", sa.String(), nullable=False, server_default="weekly")
        )
        batch.add_column(sa.Column("price_amount", sa.Integer(), nullable=True))

    op.create_index(
        "ix_activities_public_slug", "activities", ["public_slug"], unique=True
    )

    # A JSON column added to an existing table is NULL on every old row, and
    # "no images" is an empty list, not an absent one. Backfill so the admin
    # API can hand these rows to a schema that promises a list.
    op.execute(
        "UPDATE activities SET public_description = '[]' "
        "WHERE public_description IS NULL"
    )
    op.execute("UPDATE activities SET images = '[]' WHERE images IS NULL")
    op.execute("UPDATE activities SET links = '[]' WHERE links IS NULL")


def downgrade() -> None:
    op.drop_index("ix_activities_public_slug", table_name="activities")
    with op.batch_alter_table("activities") as batch:
        for column in (
            "price_amount",
            "kind",
            "links",
            "images",
            "public_description",
            "summary_en",
            "summary_id",
            "title_en",
            "public_slug",
            "is_public",
        ):
            batch.drop_column(column)
    op.drop_table("course_items")
    op.drop_table("course_modules")
    op.drop_table("courses")
