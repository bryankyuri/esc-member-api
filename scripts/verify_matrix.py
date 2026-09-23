"""Phase 1 acceptance test — the permission matrix, end to end.

Creates a real session per role (the same rows the Google callback writes),
then asserts what each role may and may not do. Restores every role it changed
before exiting.
"""

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"C:\Users\bryan\Desktop\Ongoing\ESC - Copy\member-api")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.deps import effective_role, is_member  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuthSession, User  # noqa: E402
from app.security import SESSION_COOKIE, hash_token, new_session_token  # noqa: E402

failures: list[str] = []
checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


db = SessionLocal()

superadmin = db.query(User).filter(
    User.email == "bryanqurniawan@gmail.com").first()
plain_admin = db.query(User).filter(
    User.role == "admin", User.email != superadmin.email).first()
member = db.query(User).filter(
    User.role == "user", User.security_passed.is_(True),
    User.profile_completed.is_(True)).first()
plain_user = db.query(User).filter(
    User.role == "user", User.security_passed.is_(False)).first()
contributor = db.query(User).filter(
    User.role == "user", User.id != member.id, User.id != plain_user.id).first()

original_roles = {u.id: u.role for u in (plain_admin, member, plain_user, contributor)}
contributor.role = "contributor"
db.commit()

target = db.query(User).filter(
    User.role == "user", User.id.notin_([member.id, plain_user.id, contributor.id])
).first()


def session_for(user: User) -> str:
    token = new_session_token()
    db.add(AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
    ))
    db.commit()
    return token


tokens = {
    "superadmin": session_for(superadmin),
    "admin": session_for(plain_admin),
    "contributor": session_for(contributor),
    "member": session_for(member),
    "user": session_for(plain_user),
}
ids = {"member": member.id, "target": target.id, "superadmin": superadmin.id}
db.close()


def client_as(role: str) -> TestClient:
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, tokens[role])
    return c


print("== /auth/me reports role, membership and status ==")
for role in ("superadmin", "admin", "contributor", "member", "user"):
    me = client_as(role).get("/auth/me").json()
    print(f"    {role:<12} role={me['role']:<12} isMember={me['isMember']!s:<5} "
          f"status={me['membershipStatus']}")
    check(f"{role}: /auth/me returns membership fields",
          "isMember" in me and "membershipStatus" in me)

me_user = client_as("user").get("/auth/me").json()
check("plain user is not a member", me_user["isMember"] is False,
      f"status={me_user['membershipStatus']}")
me_member = client_as("member").get("/auth/me").json()
check("member is a member", me_member["isMember"] is True,
      f"status={me_member['membershipStatus']}")

print("\n== member area needs membership, not a role ==")
check("user cannot reach attendance",
      client_as("user").get("/attendance/status").status_code == 403)
check("user cannot list activities",
      client_as("user").get("/activities?month=2026-09").status_code == 403)
check("member can reach attendance",
      client_as("member").get("/attendance/status").status_code == 200)

print("\n== dashboard needs a role, not membership ==")
check("user blocked from /admin", client_as("user").get("/admin/members").status_code == 403)
check("member blocked from /admin", client_as("member").get("/admin/members").status_code == 403)
check("contributor blocked from /admin (admin-only areas)",
      client_as("contributor").get("/admin/members").status_code == 403)
check("admin allowed", client_as("admin").get("/admin/members").status_code == 200)
check("superadmin allowed", client_as("superadmin").get("/admin/members").status_code == 200)

print("\n== require_contributor accepts the right roles ==")
from app.deps import require_contributor  # noqa: E402
from fastapi import HTTPException  # noqa: E402

db2 = SessionLocal()
for role_name, uid, expected in (
    ("contributor", contributor.id, True),
    ("admin", plain_admin.id, True),
    ("superadmin", superadmin.id, True),
    ("member", member.id, False),
):
    u = db2.get(User, uid)
    try:
        require_contributor(u)
        allowed = True
    except HTTPException:
        allowed = False
    check(f"require_contributor({role_name}) = {expected}", allowed == expected)
db2.close()

print("\n== granting admin is superadmin-only ==")
r = client_as("admin").patch(f"/admin/members/{ids['target']}", json={"role": "contributor"})
check("admin may grant contributor", r.status_code == 200,
      f"{r.status_code} {r.text[:80]}")
r = client_as("admin").patch(f"/admin/members/{ids['target']}", json={"role": "admin"})
check("admin may NOT grant admin", r.status_code == 403, str(r.status_code))
r = client_as("superadmin").patch(f"/admin/members/{ids['target']}", json={"role": "admin"})
check("superadmin may grant admin", r.status_code == 200, str(r.status_code))
r = client_as("admin").patch(f"/admin/members/{ids['target']}", json={"role": "user"})
check("admin may NOT demote an admin", r.status_code == 403, str(r.status_code))
r = client_as("superadmin").patch(f"/admin/members/{ids['target']}", json={"role": "user"})
check("superadmin may demote an admin", r.status_code == 200, str(r.status_code))
r = client_as("superadmin").patch(f"/admin/members/{ids['superadmin']}", json={"role": "user"})
check("superadmin cannot be changed via API", r.status_code == 403, str(r.status_code))
r = client_as("superadmin").patch(f"/admin/members/{ids['target']}", json={"role": "superadmin"})
check("role 'superadmin' is rejected by validation", r.status_code == 422, str(r.status_code))

print("\n== member list and overview expose status ==")
rows = client_as("admin").get("/admin/members").json()
check("member rows carry membershipStatus", "membershipStatus" in rows[0])
registered = client_as("admin").get("/admin/members?status=registered").json()
check("status filter works",
      all(r["membershipStatus"] == "registered" for r in registered),
      f"{len(registered)} rows")
ov = client_as("admin").get("/admin/overview").json()
check("overview counts active + dormant + registered",
      {"activeMembers", "dormantMembers", "registeredMembers"} <= set(ov),
      f"active={ov.get('activeMembers')} dormant={ov.get('dormantMembers')} "
      f"registered={ov.get('registeredMembers')}")

# restore
db3 = SessionLocal()
for uid, role in original_roles.items():
    db3.get(User, uid).role = role
db3.get(User, ids["target"]).role = "user"
db3.query(AuthSession).filter(
    AuthSession.token_hash.in_([hash_token(t) for t in tokens.values()])).delete(
    synchronize_session=False)
db3.commit()
db3.close()

print(f"\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("Phase 1 matrix verification PASSED")
