"""Seed the local dev database from a sanitised copy of production.

    python -m scripts.seed_local [path-to-seed.db]

Defaults to ./esc-sanitized.db. Backs up the current esc.db first, then points
one admin account at the Google identity used for local login — the sanitised
copy has placeholder google_sub values, so without that step every login would
create a fresh, empty user instead of landing in the real data.

How the sanitised copy is produced (on the server, see AUTH-ROLES-PLAN.md):
hot-copy esc.db with sqlite3's backup API, blank out email/full_name/whatsapp/
instagram/avatar_url/google_sub, delete auth_sessions, VACUUM.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent
TARGET = API_DIR / "esc.db"
DEFAULT_SEED = API_DIR / "esc-sanitized.db"
# Matches SUPERADMIN_EMAILS in .env so the seeded admin is reachable locally.
LOGIN_EMAIL = "bryanqurniawan@gmail.com"


def main() -> int:
    seed = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEED
    if not seed.exists():
        print(f"seed file not found: {seed}")
        return 1

    if TARGET.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = API_DIR / f"esc.db.bak-{stamp}"
        shutil.copy2(TARGET, backup)
        print(f"backed up current dev db -> {backup.name}")

    # A stale WAL/SHM from the old database would be applied to the new file.
    for suffix in ("-wal", "-shm"):
        stale = Path(str(TARGET) + suffix)
        if stale.exists():
            stale.unlink()

    shutil.copy2(seed, TARGET)
    print(f"seeded {TARGET.name} from {seed.name}")

    con = sqlite3.connect(TARGET)
    cur = con.cursor()
    row = cur.execute(
        "SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1"
    ).fetchone()
    if row:
        uid = row[0]
        cur.execute(
            "UPDATE users SET email=?, full_name='Bryan (local)', google_sub=?,"
            " security_passed=1, profile_completed=1, is_active=1 WHERE id=?",
            (LOGIN_EMAIL, f"local-{uid}", uid),
        )
        con.commit()
        print(f"user id={uid} -> {LOGIN_EMAIL} (admin)")
    else:
        print("!! no admin row in the seed — local login will create a new user")

    for table in ("users", "activities", "attendance", "venues", "settings"):
        count = cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"  {table:<12}{count:>5}")
    print("integrity:", cur.execute("PRAGMA integrity_check").fetchone()[0])
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
