"""End-to-end smoke test against the migrated database, without a browser.

Creates a session row directly (the same thing the Google callback does), then
exercises the admin endpoints that take ids in the path — which is exactly what
the UUID change touches.
"""

import sys
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\Users\bryan\Desktop\Ongoing\ESC - Copy\member-api")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Activity, AuthSession, User  # noqa: E402
from app.security import SESSION_COOKIE, hash_token, new_session_token  # noqa: E402

db = SessionLocal()
admin = db.query(User).filter(User.role == "admin").first()
print("admin id:", admin.id, "| email:", admin.email)

token = new_session_token()
db.add(AuthSession(
    user_id=admin.id,
    token_hash=hash_token(token),
    expires_at=datetime.utcnow() + timedelta(hours=1),
))
db.commit()

activity = db.query(Activity).order_by(Activity.date.desc()).first()
member = db.query(User).filter(User.role != "admin").first()
db.close()

client = TestClient(app)
client.cookies.set(SESSION_COOKIE, token)

checks = [
    ("GET /auth/me", "get", "/auth/me"),
    ("GET /admin/overview", "get", "/admin/overview"),
    ("GET /admin/members", "get", "/admin/members"),
    (f"GET /admin/members/{{uuid}}", "get", f"/admin/members/{member.id}"),
    ("GET /admin/members/{uuid}/attendance", "get",
     f"/admin/members/{member.id}/attendance?page=1&page_size=5"),
    ("GET /admin/sessions", "get", "/admin/sessions"),
    (f"GET /admin/attendance?activity", "get",
     f"/admin/attendance?activity_id={activity.id}"),
    ("GET /admin/activities", "get", "/admin/activities?month=2026-09"),
    ("GET /admin/venues", "get", "/admin/venues"),
    ("GET /admin/settings", "get", "/admin/settings"),
    ("GET /activities (member)", "get", "/activities?month=2026-09"),
    ("GET /attendance/status", "get", "/attendance/status"),
    ("GET /attendance/me/history", "get", "/attendance/me/history?page=1&page_size=5"),
]

failed = 0
for label, method, url in checks:
    res = getattr(client, method)(url)
    ok = res.status_code == 200
    failed += 0 if ok else 1
    body = res.json() if ok else res.text[:120]
    if ok and isinstance(body, list):
        detail = f"{len(body)} rows"
    elif ok and isinstance(body, dict):
        detail = ", ".join(list(body)[:4])
    else:
        detail = str(body)
    print(f"[{'ok ' if ok else 'FAIL'}] {label:<38} {res.status_code}  {detail}")

# a write path that has to resolve a UUID foreign key
res = client.patch(f"/admin/members/{member.id}", json={"isActive": True})
print(f"[{'ok ' if res.status_code == 200 else 'FAIL'}] PATCH /admin/members/"
      f"{{uuid}}            {res.status_code}")
failed += 0 if res.status_code == 200 else 1

# ids in responses must be UUID strings, not integers
me = client.get("/auth/me").json()
print("\n/auth/me id ->", repr(me["id"]))
members = client.get("/admin/members").json()
print("first member id ->", repr(members[0]["id"]) if members else "no rows")

print(f"\n{len(checks) + 1 - failed}/{len(checks) + 1} endpoint checks passed")
sys.exit(1 if failed else 0)
