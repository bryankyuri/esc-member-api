# Phase 0 — UUID primary keys + Alembic: production runbook

Status: **built and rehearsed 2026-09-23 on a sanitised copy of production
(102 users, 183 attendance rows). Not yet run on the server.**

What changes: every integer primary key becomes a **UUIDv7 string**, and the
schema is handed over to **Alembic**. Specs: `../../PLATFORM-V2-SPEC.md`
§3 (SPEC-ID-01 … SPEC-ID-04).

---

## What was verified locally

| Check | Result |
|---|---|
| `alembic upgrade head` on a copy of production data | 26/26 verification checks passed |
| Row counts (users/venues/activities/attendance/settings) | identical before and after |
| Relationships (who attended what, venue and author of each activity) | identical, compared by email/date rather than id |
| `PRAGMA foreign_key_check` / `integrity_check` | clean / ok |
| Indexes + `UNIQUE(user_id, activity_id)` | all survived |
| Row ordering (UUIDv7 is time-ordered) | `ORDER BY id` still matches `ORDER BY created_at` |
| API against the migrated database | 14/14 endpoints 200, including every `/{id}` route and a write |
| App boot on a **pre-Alembic** database | stamps baseline → upgrades → healthy |
| App boot on an **empty** database | creates everything at `0002_uuid_pks` |
| `member-dashboard`, `member-frontend` | `tsc --noEmit` clean, `vite build` clean |

Reproduce any of it:

```bash
python -m scripts.migrate_uuid  path/to/copy.db --dry-run   # standalone version
python -m scripts.verify_uuid   before.db after.db          # 26 checks
python -m scripts.seed_local                                # refresh local dev data
```

---

## How the schema is applied from now on

`app/migrations.py` runs at startup:

1. tables exist but no `alembic_version` → **stamp `0001_baseline`** (this is
   production's current state), then upgrade;
2. empty database → run every migration;
3. already stamped → upgrade whatever is outstanding.

So **the deploy needs no extra step** — pulling the new image is enough.
`create_all()` and the old `_lightweight_migrations()` are gone; Alembic owns
the schema.

---

## Running it on production

Nothing here is reversible by a downgrade — `0002_uuid_pks.downgrade()` raises
on purpose, because integers cannot be invented back. **The backup is the
rollback.**

1. **Pick a window with no session** (no check-ins in progress).
2. **Back up first** and keep it off the server:
   ```bash
   ssh ubuntu@<ip>
   docker exec -i esc-member-api-1 python -c "
   import sqlite3
   s=sqlite3.connect('/app/data/esc.db'); d=sqlite3.connect('/app/data/esc-prebackup.db')
   s.backup(d); d.close(); s.close(); print('backup ok')"
   sudo chown ubuntu:ubuntu ~/esc-member/data/esc-prebackup.db
   ```
   Download it with WinSCP. **Do not continue without this file.**
3. **Deploy the new image** (GitHub Actions on push to `main`, as usual). On
   boot the API stamps the baseline and runs `0002_uuid_pks`. Watch it:
   ```bash
   docker logs -f esc-member-api-1
   # expect: Running stamp_revision -> 0001_baseline
   #         Running upgrade 0001_baseline -> 0002_uuid_pks
   #         database schema is up to date
   ```
4. **Verify on the server:**
   ```bash
   docker exec -i esc-member-api-1 python -c "
   import sqlite3
   c=sqlite3.connect('/app/data/esc.db')
   print('version', c.execute('SELECT version_num FROM alembic_version').fetchone())
   print('users', c.execute('SELECT count(*) FROM users').fetchone()[0])
   print('attendance', c.execute('SELECT count(*) FROM attendance').fetchone()[0])
   print('sample id', c.execute('SELECT id FROM users LIMIT 1').fetchone()[0])
   print('fk', c.execute('PRAGMA foreign_key_check').fetchall() or 'clean')"
   curl -s https://api-member.earhousesongwritingclub.com/health
   ```
   Expect `0002_uuid_pks`, the same counts as before, a UUID, and `clean`.
5. **Deploy both frontends** (Cloudflare Pages, push to `main`). They now send
   and receive string ids.
6. **Check by hand:** sign in to the dashboard, open a member (the URL is now
   `/members/<uuid>`), open an attendance log, edit an activity, and do one
   real check-in from the member app.
7. **Remove the backup from the server** once satisfied:
   `rm ~/esc-member/data/esc-prebackup.db` (keep your local copy).

### If something goes wrong

```bash
docker compose -f ~/esc-member/docker-compose.prod.yml down
cp ~/esc-member/data/esc-prebackup.db ~/esc-member/data/esc.db
rm -f ~/esc-member/data/esc.db-wal ~/esc-member/data/esc.db-shm
# redeploy the previous image tag, then bring it up
docker compose -f ~/esc-member/docker-compose.prod.yml up -d
```

Old dashboard bookmarks such as `/members/12` stop working — that is expected
and affects admins only. No public URL contains a database id.

---

## Phase 1 ships with this deploy

Phase 1 (roles + membership status) is on the same branch, so the deploy
applies **`0002_uuid_pks` then `0003_roles`** in order. Everything above still
applies; the extra checks are:

```bash
docker exec -i esc-member-api-1 python -c "
import sqlite3
c=sqlite3.connect('/app/data/esc.db')
print('version', c.execute('SELECT version_num FROM alembic_version').fetchone())
print('roles', c.execute('SELECT role, count(*) FROM users GROUP BY role').fetchall())
print('members', c.execute('SELECT count(*) FROM users WHERE security_passed=1 AND profile_completed=1').fetchone()[0])"
```

Expect `0003_roles`, roles of only `user`/`contributor`/`admin`, and the **same
member count as before the deploy** (88 in the September data).

**Deploy the API before the frontends** — the old dashboard build sends
`role: "member"`, which the new API rejects with 422.

Follow-ups now closed: session rotation on login, expired-session purge, and
the deprecated `datetime.utcnow()` calls.
