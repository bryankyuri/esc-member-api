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

## Notes

- Weekly session rows are auto-created on the configured day
  (`ensure_today_session`) if the admin hasn't created one.
- Attendance validation (server-authoritative): time window, `is_holiday`,
  geofence (haversine vs resolved venue), GPS accuracy threshold, optional
  attendance code, and a DB `UNIQUE(user_id, activity_id)` constraint.
- Schema is `create_all` for now; adopt Alembic before the first production
  schema change.
