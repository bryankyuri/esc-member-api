"""integer primary keys -> UUIDv7 strings

Revision ID: 0002_uuid_pks
Revises: 0001_baseline
Create Date: 2026-09-23

Phase 0 of PLATFORM-V2-SDD.md. Sequential ids leak information once accounts
reach the public site (/members/12 says you are the twelfth member, and the
range can be walked), so every table moves to a UUID.

v7 rather than v4: the first 48 bits are a millisecond timestamp, so rows stay
insert-ordered and "ORDER BY id" still means "oldest first". Each existing row
is seeded from its own created_at, so the new ids preserve the old ordering.

SQLite cannot alter a primary key, so each table is rebuilt and all five
foreign keys are remapped in the same transaction. Verified on a sanitised copy
of production (102 users / 183 attendance rows) with scripts/verify_uuid.py.

Irreversible in practice: downgrade() would have to invent integer ids, so it
raises instead. Roll back by restoring the backup taken before the upgrade.
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

from app.ids import uuid7

revision = "0002_uuid_pks"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

# child table -> {fk column: parent table}
FKS = {
    "activities": {"venue_id": "venues", "created_by": "users"},
    "attendance": {"user_id": "users", "activity_id": "activities"},
    "auth_sessions": {"user_id": "users"},
}
# parents before children
TABLES = ["users", "venues", "activities", "attendance", "auth_sessions"]


def _parse(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. one UUID per existing row, timestamped from that row's created_at
    id_map: dict[str, dict[int, str]] = {}
    for table in TABLES:
        cols = {c["name"] for c in sa.inspect(conn).get_columns(table)}
        time_col = "created_at" if "created_at" in cols else None
        select = f"SELECT id{', ' + time_col if time_col else ''} FROM {table}"
        id_map[table] = {
            row[0]: uuid7(_parse(row[1]) if time_col else None)
            for row in conn.execute(sa.text(select))
        }

    # 2. widen the id columns to text, then rewrite every value
    with op.batch_alter_table("users") as batch:
        batch.alter_column("id", type_=sa.String(36), existing_type=sa.Integer())
    with op.batch_alter_table("venues") as batch:
        batch.alter_column("id", type_=sa.String(36), existing_type=sa.Integer())
    with op.batch_alter_table("activities") as batch:
        batch.alter_column("id", type_=sa.String(36), existing_type=sa.Integer())
        batch.alter_column("venue_id", type_=sa.String(36), existing_type=sa.Integer())
        batch.alter_column("created_by", type_=sa.String(36), existing_type=sa.Integer())
    with op.batch_alter_table("attendance") as batch:
        batch.alter_column("id", type_=sa.String(36), existing_type=sa.Integer())
        batch.alter_column("user_id", type_=sa.String(36), existing_type=sa.Integer())
        batch.alter_column("activity_id", type_=sa.String(36), existing_type=sa.Integer())
    with op.batch_alter_table("auth_sessions") as batch:
        batch.alter_column("id", type_=sa.String(36), existing_type=sa.Integer())
        batch.alter_column("user_id", type_=sa.String(36), existing_type=sa.Integer())

    # 3. children first: their FKs still point at the old integers
    for table in reversed(TABLES):
        for old_id, new_id in id_map[table].items():
            conn.execute(
                sa.text(f"UPDATE {table} SET id = :new WHERE id = :old"),
                {"new": new_id, "old": str(old_id)},
            )
        for column, parent in FKS.get(table, {}).items():
            for old_id, new_id in id_map[parent].items():
                conn.execute(
                    sa.text(
                        f"UPDATE {table} SET {column} = :new WHERE {column} = :old"
                    ),
                    {"new": new_id, "old": str(old_id)},
                )

    dangling = conn.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    if dangling:
        raise RuntimeError(f"foreign_key_check failed after migration: {dangling[:5]}")


def downgrade() -> None:
    raise NotImplementedError(
        "UUIDs cannot be turned back into meaningful integers. "
        "Restore the backup taken before this migration."
    )
