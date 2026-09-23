"""Phase 0 — convert every integer primary key to a UUIDv7 string.

    python -m scripts.migrate_uuid <path-to.db> [--dry-run]

SQLite cannot ALTER a primary key, so each table is rebuilt: new table with
TEXT ids, rows copied through an id map, old table dropped, new one renamed.
All five foreign keys are remapped in the same transaction.

UUIDv7 (not v4) so ids stay time-ordered: rows keep their natural order and
indexes do not fragment. The timestamp comes from each row's own created_at
where it has one, so existing rows sort exactly as they did before.

Safe to run repeatedly: it detects an already-migrated database and stops.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# table -> (its own FK columns pointing at other tables)
FOREIGN_KEYS: dict[str, dict[str, str]] = {
    "activities": {"venue_id": "venues", "created_by": "users"},
    "attendance": {"user_id": "users", "activity_id": "activities"},
    "auth_sessions": {"user_id": "users"},
}

# Rebuild order: parents before children, so FK values always resolve.
TABLES = ["users", "venues", "activities", "attendance", "auth_sessions"]

NEW_SCHEMA: dict[str, str] = {
    "users": """
        CREATE TABLE users (
            id VARCHAR(36) NOT NULL,
            google_sub VARCHAR NOT NULL,
            email VARCHAR NOT NULL,
            full_name VARCHAR NOT NULL,
            avatar_url VARCHAR,
            whatsapp VARCHAR,
            domicile VARCHAR,
            instagram VARCHAR,
            role VARCHAR NOT NULL,
            profile_completed BOOLEAN NOT NULL,
            is_active BOOLEAN NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            security_passed BOOLEAN NOT NULL DEFAULT 0,
            security_attempts INTEGER NOT NULL DEFAULT 0,
            security_attempt_date VARCHAR,
            PRIMARY KEY (id)
        )""",
    "venues": """
        CREATE TABLE venues (
            id VARCHAR(36) NOT NULL,
            name VARCHAR NOT NULL,
            address VARCHAR NOT NULL,
            lat FLOAT NOT NULL,
            lng FLOAT NOT NULL,
            radius_m FLOAT NOT NULL,
            is_default BOOLEAN NOT NULL,
            is_active BOOLEAN NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id)
        )""",
    "activities": """
        CREATE TABLE activities (
            id VARCHAR(36) NOT NULL,
            title VARCHAR NOT NULL,
            description TEXT,
            date VARCHAR NOT NULL,
            start_time VARCHAR NOT NULL,
            end_time VARCHAR NOT NULL,
            is_attendance_event BOOLEAN NOT NULL,
            is_holiday BOOLEAN NOT NULL,
            venue_id VARCHAR(36),
            attendance_code VARCHAR,
            created_by VARCHAR(36),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(venue_id) REFERENCES venues (id),
            FOREIGN KEY(created_by) REFERENCES users (id)
        )""",
    "attendance": """
        CREATE TABLE attendance (
            id VARCHAR(36) NOT NULL,
            user_id VARCHAR(36) NOT NULL,
            activity_id VARCHAR(36) NOT NULL,
            attended_at DATETIME NOT NULL,
            lat FLOAT,
            lng FLOAT,
            distance_m FLOAT,
            PRIMARY KEY (id),
            CONSTRAINT uq_attendance_user_activity UNIQUE (user_id, activity_id),
            FOREIGN KEY(user_id) REFERENCES users (id),
            FOREIGN KEY(activity_id) REFERENCES activities (id)
        )""",
    "auth_sessions": """
        CREATE TABLE auth_sessions (
            id VARCHAR(36) NOT NULL,
            user_id VARCHAR(36) NOT NULL,
            token_hash VARCHAR NOT NULL,
            expires_at DATETIME NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            ip VARCHAR,
            user_agent VARCHAR,
            PRIMARY KEY (id),
            FOREIGN KEY(user_id) REFERENCES users (id)
        )""",
}

INDEXES = [
    "CREATE INDEX ix_activities_date ON activities (date)",
    "CREATE INDEX ix_attendance_activity_id ON attendance (activity_id)",
    "CREATE INDEX ix_attendance_user_id ON attendance (user_id)",
    "CREATE UNIQUE INDEX ix_auth_sessions_token_hash ON auth_sessions (token_hash)",
    "CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id)",
    "CREATE UNIQUE INDEX ix_users_email ON users (email)",
    "CREATE UNIQUE INDEX ix_users_google_sub ON users (google_sub)",
]


def uuid7(when: datetime | None = None) -> str:
    """UUIDv7: 48-bit millisecond timestamp, 4-bit version, 74 random bits."""
    ms = int((when or datetime.now(timezone.utc)).timestamp() * 1000)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (
        (ms & 0xFFFFFFFFFFFF) << 80
        | 0x7 << 76
        | rand_a << 64
        | 0b10 << 62
        | rand_b
    )
    hexed = f"{value:032x}"
    return (
        f"{hexed[0:8]}-{hexed[8:12]}-{hexed[12:16]}-{hexed[16:20]}-{hexed[20:32]}"
    )


def parse_dt(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def already_uuid(con: sqlite3.Connection) -> bool:
    for col in con.execute("PRAGMA table_info(users)"):
        if col[1] == "id":
            return "VARCHAR" in (col[2] or "").upper()
    return False


def migrate(db_path: Path, dry_run: bool = False) -> int:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    if already_uuid(con):
        print("already migrated — users.id is not an INTEGER. Nothing to do.")
        return 0

    before = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in TABLES + ["settings"]}
    print("row counts before:", before)

    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("BEGIN")
    try:
        # 1. one UUID per existing row, seeded from that row's created_at so
        #    the new ids sort in the same order as the old ones.
        id_map: dict[str, dict[int, str]] = {}
        for table in TABLES:
            cols = {c[1] for c in con.execute(f"PRAGMA table_info({table})")}
            time_col = "created_at" if "created_at" in cols else None
            rows = con.execute(
                f"SELECT id{', ' + time_col if time_col else ''} FROM {table} ORDER BY id"
            ).fetchall()
            id_map[table] = {
                r["id"]: uuid7(parse_dt(r[time_col]) if time_col else None)
                for r in rows
            }
            print(f"  {table:<15} {len(rows):>4} ids mapped")

        # 2. rebuild each table, remapping its own id and every FK
        for table in TABLES:
            columns = [c[1] for c in con.execute(f"PRAGMA table_info({table})")]
            old_rows = con.execute(f"SELECT * FROM {table}").fetchall()

            con.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
            con.execute(NEW_SCHEMA[table])

            fks = FOREIGN_KEYS.get(table, {})
            placeholders = ",".join("?" * len(columns))
            payload = []
            for row in old_rows:
                values = []
                for col in columns:
                    if col == "id":
                        values.append(id_map[table][row["id"]])
                    elif col in fks:
                        raw = row[col]
                        values.append(
                            None if raw is None else id_map[fks[col]][raw]
                        )
                    else:
                        values.append(row[col])
                payload.append(values)

            if payload:
                con.executemany(
                    f"INSERT INTO {table} ({','.join(columns)}) "
                    f"VALUES ({placeholders})",
                    payload,
                )
            con.execute(f"DROP TABLE {table}_old")
            print(f"  {table:<15} rebuilt with {len(payload)} rows")

        # 3. indexes were dropped with the old tables
        for statement in INDEXES:
            con.execute(statement)

        # 4. nothing may dangle
        dangling = con.execute("PRAGMA foreign_key_check").fetchall()
        if dangling:
            raise RuntimeError(f"foreign_key_check failed: {dangling[:5]}")

        after = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                 for t in TABLES + ["settings"]}
        if after != before:
            raise RuntimeError(f"row counts changed: {before} -> {after}")

        if dry_run:
            con.execute("ROLLBACK")
            print("\nDRY RUN — rolled back, database untouched")
        else:
            con.execute("COMMIT")
            con.execute("PRAGMA foreign_keys = ON")
            con.execute("VACUUM")
            print("\ncommitted")
        print("row counts after: ", after)
    except Exception as exc:  # noqa: BLE001 — abort on anything
        con.execute("ROLLBACK")
        print(f"\nFAILED, rolled back: {exc}")
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = Path(args[0]) if args else Path(os.getcwd()) / "esc.db"
    raise SystemExit(migrate(path, dry_run="--dry-run" in sys.argv))
