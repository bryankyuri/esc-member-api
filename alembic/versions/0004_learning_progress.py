"""learning progress + drafts on the account

Revision ID: 0004_learning
Revises: 0003_roles
Create Date: 2026-09-23

Phase 2 of PLATFORM-V2-SPEC.md (SPEC-LRN-05, SPEC-LRN-06).

Lesson progress moves off the visitor's localStorage and onto their account, so
it survives clearing the browser and follows them to another device. Anonymous
visitors can still read every lesson — only *saving* needs an account.

Items are referenced by their content id (a slug from the CMS), not a foreign
key: courses live in frontend JSON today and gain their own tables in Phase 5,
and progress must not have to be rewritten when that happens.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_learning"
down_revision = "0003_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_progress",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_slug", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column(
            "completed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("via", sa.String(), nullable=False, server_default="manual"),
        sa.UniqueConstraint("user_id", "item_id", name="uq_progress_user_item"),
    )
    op.create_index("ix_learning_progress_user_id", "learning_progress", ["user_id"])
    op.create_index(
        "ix_learning_progress_course_slug", "learning_progress", ["course_slug"]
    )

    op.create_table(
        "learning_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "item_id", name="uq_draft_user_item"),
    )
    op.create_index("ix_learning_drafts_user_id", "learning_drafts", ["user_id"])


def downgrade() -> None:
    op.drop_table("learning_drafts")
    op.drop_table("learning_progress")
