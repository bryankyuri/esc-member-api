"""baseline: the schema as it stood with integer primary keys

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-23

This is the starting point, matching every database that existed before
Alembic was adopted. Existing databases are *stamped* with this revision
rather than running it:

    alembic stamp 0001_baseline

A brand-new database runs it for real.
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("google_sub", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("avatar_url", sa.String()),
        sa.Column("whatsapp", sa.String()),
        sa.Column("domicile", sa.String()),
        sa.Column("instagram", sa.String()),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("profile_completed", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("security_passed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("security_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("security_attempt_date", sa.String()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)

    op.create_table(
        "venues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("radius_m", sa.Float(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("start_time", sa.String(), nullable=False),
        sa.Column("end_time", sa.String(), nullable=False),
        sa.Column("is_attendance_event", sa.Boolean(), nullable=False),
        sa.Column("is_holiday", sa.Boolean(), nullable=False),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id")),
        sa.Column("attendance_code", sa.String()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_activities_date", "activities", ["date"])

    op.create_table(
        "attendance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id"), nullable=False),
        sa.Column("attended_at", sa.DateTime(), nullable=False),
        sa.Column("lat", sa.Float()),
        sa.Column("lng", sa.Float()),
        sa.Column("distance_m", sa.Float()),
        sa.UniqueConstraint("user_id", "activity_id", name="uq_attendance_user_activity"),
    )
    op.create_index("ix_attendance_user_id", "attendance", ["user_id"])
    op.create_index("ix_attendance_activity_id", "attendance", ["activity_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("ip", sa.String()),
        sa.Column("user_agent", sa.String()),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)

    op.create_table(
        "settings",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.String(), nullable=False),
    )


def downgrade() -> None:
    for table in ("settings", "auth_sessions", "attendance", "activities",
                  "venues", "users"):
        op.drop_table(table)
