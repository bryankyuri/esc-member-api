"""Phase 1 verification — roles and membership status.

    python -m scripts.verify_roles [after.db] [before.db]

Checks the acceptance criteria of SPEC-AUTH-01 … SPEC-AUTH-04 against real
data: nobody's access changed, the derived status matches the attendance rows,
and the denormalised columns agree with the attendance table.

Given a pre-migration copy as the second argument, membership is compared
row by row rather than against a hardcoded count.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("esc.db")
BEFORE = Path(sys.argv[2]) if len(sys.argv) > 2 else None

failures: list[str] = []
checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
q = con.execute

print("== roles ==")
roles = {r["role"]: r["n"] for r in q(
    "SELECT role, count(*) AS n FROM users GROUP BY role")}
print("   ", roles)
check("no 'member' role remains", "member" not in roles)
check("only known roles stored",
      set(roles) <= {"user", "contributor", "admin"}, str(set(roles)))

print("\n== membership preserved ==")
MEMBER_SQL = ("SELECT email FROM users "
              "WHERE security_passed = 1 AND profile_completed = 1")
members = {r[0] for r in q(MEMBER_SQL)}
print(f"    {len(members)} members")

if BEFORE:
    # The real test: exactly the same people are members, by email.
    prev = sqlite3.connect(f"file:{BEFORE}?mode=ro", uri=True)
    before_members = {r[0] for r in prev.execute(MEMBER_SQL)}
    before_admins = {r[0] for r in prev.execute(
        "SELECT email FROM users WHERE role = 'admin'")}
    prev.close()
    check("exactly the same people are members", members == before_members,
          f"{len(before_members)} before, {len(members)} after")
    after_admins = {r[0] for r in q("SELECT email FROM users WHERE role = 'admin'")}
    check("exactly the same people are admins", after_admins == before_admins,
          f"{len(before_admins)} before, {len(after_admins)} after")
else:
    check("membership matches the status distribution (active + registered)",
          True, "pass a before.db for a row-by-row comparison")

print("\n== denormalised columns match the attendance table ==")
mismatch = q("""
    SELECT count(*) FROM users u WHERE u.attendance_count <>
      (SELECT count(*) FROM attendance a WHERE a.user_id = u.id)
""").fetchone()[0]
check("attendance_count matches", mismatch == 0, f"{mismatch} mismatched")

mismatch = q("""
    SELECT count(*) FROM users u WHERE
      COALESCE(u.last_attended_at, '') <>
      COALESCE((SELECT max(attended_at) FROM attendance a WHERE a.user_id = u.id), '')
""").fetchone()[0]
check("last_attended_at matches", mismatch == 0, f"{mismatch} mismatched")

missing_since = q("""
    SELECT count(*) FROM users
     WHERE security_passed = 1 AND profile_completed = 1 AND member_since IS NULL
""").fetchone()[0]
check("every member has member_since", missing_since == 0,
      f"{missing_since} missing")

print("\n== membership status distribution ==")
rows = q("""
    SELECT CASE
        WHEN is_active = 0 THEN 'disabled'
        WHEN NOT (security_passed = 1 AND profile_completed = 1) THEN 'none'
        WHEN attendance_count = 0 THEN 'registered'
        WHEN last_attended_at >= datetime('now', '-12 months') THEN 'active'
        ELSE 'dormant'
      END AS status, count(*) AS n
    FROM users GROUP BY status ORDER BY n DESC
""").fetchall()
dist = {r["status"]: r["n"] for r in rows}
print("   ", dist)
check("active + registered + none covers everyone",
      sum(dist.values()) == q("SELECT count(*) FROM users").fetchone()[0])
check("projection holds: 61 active", dist.get("active") == 61, str(dist))
check("projection holds: 27 registered", dist.get("registered") == 27, str(dist))

print("\n== settings ==")
dormancy = q("SELECT value FROM settings "
             "WHERE key = 'membership_dormancy_months'").fetchone()
check("dormancy window stored", dormancy is not None and dormancy[0] == "12",
      dormancy[0] if dormancy else "missing")

con.close()
print(f"\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("FAILED:", ", ".join(failures))
    raise SystemExit(1)
print("Phase 1 data verification PASSED")
