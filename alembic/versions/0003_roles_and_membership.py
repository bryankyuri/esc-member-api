"""roles user/contributor/admin + membership columns

Revision ID: 0003_roles
Revises: 0002_uuid_pks
Create Date: 2026-09-23

Phase 1 of PLATFORM-V2-SPEC.md (SPEC-AUTH-01 … SPEC-AUTH-04).

"member" stops being a *role* and becomes a derived state. The role column now
says what someone may **manage** (user < contributor < admin, plus the env-only
superadmin), while membership is `security_passed AND profile_completed` — so
every existing `role='member'` row becomes `role='user'` and keeps exactly the
access it had.

Four denormalised columns are added so `membershipStatus` (active / dormant /
registered) can be computed without aggregating the attendance table on every
request. They are backfilled here from the real attendance rows.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_roles"
down_revision = "0002_uuid_pks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("member_since", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("first_attended_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_attended_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("attendance_count", sa.Integer(), nullable=False, server_default="0")
        )

    # member -> user. Membership itself lives in security_passed/profile_completed,
    # so nobody gains or loses access here.
    conn.execute(sa.text("UPDATE users SET role = 'user' WHERE role = 'member'"))

    # Backfill the attendance columns from the source of truth.
    conn.execute(sa.text("""
        UPDATE users SET
          attendance_count = (
            SELECT count(*) FROM attendance WHERE attendance.user_id = users.id
          ),
          first_attended_at = (
            SELECT min(attended_at) FROM attendance WHERE attendance.user_id = users.id
          ),
          last_attended_at = (
            SELECT max(attended_at) FROM attendance WHERE attendance.user_id = users.id
          )
    """))

    # Members who completed onboarding before this column existed: use the
    # earliest signal we have of them being a member.
    conn.execute(sa.text("""
        UPDATE users
           SET member_since = COALESCE(first_attended_at, created_at)
         WHERE security_passed = 1 AND profile_completed = 1
    """))

    # Dormancy window, editable later in the dashboard.
    exists = conn.execute(
        sa.text("SELECT 1 FROM settings WHERE key = 'membership_dormancy_months'")
    ).fetchone()
    if not exists:
        conn.execute(
            sa.text(
                "INSERT INTO settings (key, value) "
                "VALUES ('membership_dormancy_months', '12')"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE users SET role = 'member' WHERE role = 'user'"))
    # Contributors have no equivalent in the old model; demote them.
    conn.execute(sa.text("UPDATE users SET role = 'member' WHERE role = 'contributor'"))
    conn.execute(
        sa.text("DELETE FROM settings WHERE key = 'membership_dormancy_months'")
    )
    with op.batch_alter_table("users") as batch:
        batch.drop_column("attendance_count")
        batch.drop_column("last_attended_at")
        batch.drop_column("first_attended_at")
        batch.drop_column("member_since")
