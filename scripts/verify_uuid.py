"""Phase 0 verification — compare a database before and after migrate_uuid.

    python -m scripts.verify_uuid <before.db> <after.db>

Ids are expected to change; everything they *mean* must not. So instead of
comparing ids, this compares the relationships they express, keyed by natural
values (email, activity date, etc.).
"""

from __future__ import annotations

import re
import sqlite3
import sys

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

failures: list[str] = []
checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def ro(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def fingerprint(con: sqlite3.Connection) -> dict:
    """Everything the data means, expressed without ids."""
    q = con.execute
    return {
        "counts": {
            t: q(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("users", "venues", "activities", "attendance",
                      "auth_sessions", "settings")
        },
        # who attended which session, by email + date + time
        "attendance": sorted(
            (r[0], r[1], str(r[2]))
            for r in q(
                "SELECT u.email, a.date, att.attended_at "
                "FROM attendance att "
                "JOIN users u ON u.id = att.user_id "
                "JOIN activities a ON a.id = att.activity_id"
            )
        ),
        # which activity sits at which venue
        "activity_venue": sorted(
            (r[0], r[1], r[2] or "")
            for r in q(
                "SELECT a.date, a.title, v.name FROM activities a "
                "LEFT JOIN venues v ON v.id = a.venue_id"
            )
        ),
        # who created which activity
        "activity_author": sorted(
            (r[0], r[1], r[2] or "")
            for r in q(
                "SELECT a.date, a.title, u.email FROM activities a "
                "LEFT JOIN users u ON u.id = a.created_by"
            )
        ),
        "users": sorted(
            (r["email"], r["role"], r["is_active"], r["profile_completed"],
             r["security_passed"])
            for r in q("SELECT * FROM users")
        ),
        "settings": sorted((r[0], r[1]) for r in q("SELECT key, value FROM settings")),
    }


def main() -> int:
    before_path, after_path = sys.argv[1], sys.argv[2]
    before, after = ro(before_path), ro(after_path)

    print("== data preserved ==")
    fb, fa = fingerprint(before), fingerprint(after)
    for key in fb:
        check(f"{key} identical", fb[key] == fa[key],
              "" if fb[key] == fa[key] else f"{len(fb[key])} vs {len(fa[key])}")

    print("\n== ids converted ==")
    for table in ("users", "venues", "activities", "attendance", "auth_sessions"):
        ids = [r[0] for r in after.execute(f"SELECT id FROM {table}")]
        bad = [i for i in ids if not UUID_RE.match(str(i))]
        check(f"{table}: all ids are UUIDv7", not bad,
              f"{len(ids)} rows" if not bad else f"bad: {bad[:3]}")
        check(f"{table}: ids unique", len(ids) == len(set(ids)))

    fk_ok = not after.execute("PRAGMA foreign_key_check").fetchall()
    check("foreign_key_check clean", fk_ok)
    check("integrity_check ok",
          after.execute("PRAGMA integrity_check").fetchone()[0] == "ok")

    print("\n== constraints & indexes survived ==")
    idx = {r[0] for r in after.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'")}
    for expected in ("ix_users_email", "ix_users_google_sub",
                     "ix_auth_sessions_token_hash", "ix_attendance_user_id",
                     "ix_attendance_activity_id", "ix_activities_date"):
        check(f"index {expected}", expected in idx)
    sql = after.execute(
        "SELECT sql FROM sqlite_master WHERE name='attendance'").fetchone()[0]
    check("UNIQUE(user_id, activity_id) kept",
          "uq_attendance_user_activity" in sql)

    print("\n== ordering preserved (UUIDv7 is time-ordered) ==")
    by_uuid = [r[0] for r in after.execute(
        "SELECT email FROM users ORDER BY id")]
    by_created = [r[0] for r in after.execute(
        "SELECT email FROM users ORDER BY created_at, id")]
    check("users sort the same by id as by created_at", by_uuid == by_created)

    before.close()
    after.close()
    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED:", ", ".join(failures))
        return 1
    print("Phase 0 verification PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
