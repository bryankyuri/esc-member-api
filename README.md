# ESC Member API

FastAPI + SQLite backend for `api-member.earhousesongwritingclub.com` —
Google-only auth, geofenced attendance, activities/venues management.
Implements exactly the `ApiClient` / `AdminApiClient` contracts frozen in
`../member-frontend` and `../member-dashboard` (camelCase JSON).
See `../member_system_sdd.md` for the full design.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (source .venv/bin/activate on Linux)
pip install -r requirements.txt
copy .env.example .env           # then edit — see below
uvicorn app.main:app --reload --port 8000
```

Or with Docker (same image as production): `docker compose up --build`.

## Deployment

Docker image → GHCR → VPS via docker compose behind Caddy, driven by
GitHub Actions on push to `main` (same pattern as dictionary-service).
See `../DEPLOYMENT.md` for server prep and repo secrets.

OpenAPI docs: http://localhost:8000/docs
The SQLite file (`esc.db`) and schema are created automatically on first boot,
with a placeholder default venue (Pasar Kita — fix the coordinates in the
dashboard Settings/Venues).

## Google OAuth setup (one-time, ~5 minutes)

1. https://console.cloud.google.com → create project "ESC Member".
2. **APIs & Services → OAuth consent screen**: External, app name, your
   email; add yourself under **Test users**. (Publish to Production later —
   basic scopes need no verification.)
3. **Credentials → Create credentials → OAuth client ID → Web application**:
   - Authorized JavaScript origins: `http://localhost:3001`, `http://localhost:3002`
   - Authorized redirect URIs: `http://localhost:8000/auth/google/callback`
4. Copy Client ID + Secret into `.env`
   (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`).
5. Set `SESSION_SECRET` to a long random string and put your Gmail in
   `SUPERADMIN_EMAILS` so you always have dashboard access.

For production add the `https://api-member.earhousesongwritingclub.com/auth/google/callback`
redirect URI to the same client and set `COOKIE_DOMAIN=.earhousesongwritingclub.com`,
`COOKIE_SECURE=true`.

## Roles

- `member` / `admin` live in the DB (admins manage them in the dashboard,
  or `python -m scripts.promote_admin someone@gmail.com`).
- `superadmin` is **env-only** (`SUPERADMIN_EMAILS`) — applied as an overlay
  at request time, never stored, cannot be modified via the API.

## Database schema (Alembic)

The schema is owned by **Alembic** and applied automatically when the app
starts (`app/migrations.py`), so a deploy needs no extra step:

- a database created before Alembic is **stamped** with `0001_baseline`, then
  upgraded;
- an empty database runs every migration;
- ids are **UUIDv7 strings** (`app/ids.py`), never auto-increment integers.

```bash
alembic revision -m "add x"     # new migration (autogenerate needs DATABASE_URL set)
alembic upgrade head            # normally unnecessary — startup does it
alembic current                 # where this database stands
python -m scripts.seed_local    # refresh local dev data from a sanitised copy
python -m scripts.verify_uuid before.db after.db
python -m scripts.verify_roles esc.db [before.db]
```

## How the public site learns about new articles

Articles are readable the moment they are saved — the site fetches them at
runtime. What a rebuild adds is the prerendered HTML and the sitemap entry.

**This API never triggers a build.** It exposes a fingerprint of the public
content instead:

```
GET /public/content-version
{ "version": "746b748e3c710cd8", "articleCount": 3,
  "latestUpdatedAt": …, "latestPublishedAt": …, "nextScheduledAt": … }
```

A Cloudflare Worker (`public-frontend/scripts/rebuild-worker/`) polls this and
the version baked into the deployed site, and rebuilds **only when they
differ**. So:

- a draft edit changes nothing public → no build minutes spent;
- a **scheduled post falling due** moves the fingerprint even though no row was
  written, which a "has any row changed?" check would miss;
- publishing never depends on this API being able to reach Cloudflare, and a
  missed tick self-heals on the next one.

No Cloudflare credentials live here.

## Courses

Course content lives in the database (`courses` → `course_modules` →
`course_items`), managed from the dashboard by admins only. Certificates are
issued when the **server** confirms every published item of a course is
complete, read straight from those tables — the generated
`courses_manifest.json` and `scripts/sync_course_manifest.py` were deleted in
Phase 5, so there is no duplicate to keep in step.

One thing here is load-bearing: **`course_items.content_id`**, not the row id,
is what the public API exposes and what `learning_progress` and certificates
are keyed on. The ids were inherited from the original JSON (`lyr-1`, `ow-3`)
so that progress written before the move still counts. The admin API refuses
to change an item's `content_id` for exactly that reason.

First deploy of this phase, once:

```bash
alembic upgrade head              # 0007 creates the course tables
python -m scripts.import_courses  # carries the original course content across
```

`import_courses` is idempotent (`--force` replaces a course's modules and items
while keeping their content ids). `scripts/import_events.py` seeds the public
calendar the same way; its `--anchor` flag shifts every date to sit around
today, which is for a dev database and **never** for production.

## Notes

- Weekly session rows are auto-created on the configured day
  (`ensure_today_session`) if the admin hasn't created one.
- Attendance validation (server-authoritative): time window, `is_holiday`,
  geofence (haversine vs resolved venue), GPS accuracy threshold, optional
  attendance code, and a DB `UNIQUE(user_id, activity_id)` constraint.
- Schema is managed by Alembic (see above); `create_all` and the old
  hand-rolled column migrations were removed in Phase 0.
