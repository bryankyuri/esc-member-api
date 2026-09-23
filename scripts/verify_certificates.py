"""Phase 3 acceptance test — certificates (SPEC-CRT-01 … SPEC-CRT-05)."""

import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"C:\Users\bryan\Desktop\Ongoing\ESC - Copy\member-api")

from fastapi.testclient import TestClient  # noqa: E402

from app.certificates import course_items  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuthSession, Certificate, LearningProgress, User  # noqa: E402
from app.security import SESSION_COOKIE, hash_token, new_session_token  # noqa: E402

COURSE = "menulis-lirik-dasar"
failures: list[str] = []
checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


db = SessionLocal()
learner = db.query(User).filter(
    User.role == "user", User.security_passed.is_(False)).first()
learner_id = learner.id
db.query(LearningProgress).filter(LearningProgress.user_id == learner_id).delete()
db.query(Certificate).filter(Certificate.user_id == learner_id).delete()
learner.first_name = None
learner.last_name = None
token = new_session_token()
db.add(AuthSession(
    user_id=learner_id, token_hash=hash_token(token),
    expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)))
db.commit()

client = TestClient(app)
client.cookies.set(SESSION_COOKIE, token)

# Since Phase 5 the course tables are the source of truth, so this needs a
# session rather than the generated manifest it used to read.
items = course_items(db, COURSE)
db.close()
print(f"course '{COURSE}' has {len(items)} items")

print("\n== a course must actually be finished ==")
r = client.post("/me/certificates", json={"courseSlug": COURSE})
check("no progress → refused", r.status_code == 409, str(r.status_code))

# Complete all but one.
for item in items[:-1]:
    client.put(f"/me/learning/items/{item}", json={"courseSlug": COURSE})
r = client.post("/me/certificates", json={"courseSlug": COURSE})
check("one item short → refused", r.status_code == 409,
      f"{r.status_code} {r.json().get('detail', {}).get('message', '')}")

r = client.post("/me/certificates", json={"courseSlug": "does-not-exist"})
check("unknown course → 404", r.status_code == 404, str(r.status_code))

print("\n== the learner profile gate ==")
client.put(f"/me/learning/items/{items[-1]}", json={"courseSlug": COURSE})
r = client.post("/me/certificates", json={"courseSlug": COURSE})
check("complete but unnamed → asks for the name", r.status_code == 422,
      f"{r.status_code} {r.json().get('detail', {}).get('code', '')}")

r = client.put("/me/profile/learner",
               json={"firstName": "  Budi ", "lastName": " Santoso "})
check("learner profile saved", r.status_code == 200 and r.json()["firstName"] == "Budi",
      str(r.status_code))
me = client.get("/auth/me").json()
check("membership untouched by the learner profile",
      me["isMember"] is False and me["membershipStatus"] == "none")

print("\n== issuing ==")
r = client.post("/me/certificates", json={"courseSlug": COURSE})
check("issued on 100%", r.status_code == 201, str(r.status_code))
cert = r.json()
code = cert["code"]
print(f"    code: {code}")
check("code is readable and random",
      bool(re.fullmatch(r"ESC-[A-Z]{3}-[A-HJ-NP-Z2-9]{5}", code)), code)
check("name snapshot trimmed", cert["firstName"] == "Budi" and cert["lastName"] == "Santoso")
check("email on the holder's own copy", cert["email"].endswith("@example.test"))
check("course title resolved", cert["courseTitle"].startswith("Menulis"), cert["courseTitle"])

r2 = client.post("/me/certificates", json={"courseSlug": COURSE})
check("re-issuing returns the same certificate", r2.json()["code"] == code)

print("\n== snapshots do not drift ==")
client.put("/me/profile/learner", json={"firstName": "Berubah", "lastName": "Nama"})
again = client.get("/me/certificates").json()[0]
check("issued certificate keeps the original name",
      again["firstName"] == "Budi", again["firstName"])

print("\n== public verification ==")
anon = TestClient(app)
r = anon.get(f"/certificates/{code}")
check("anyone can verify", r.status_code == 200, str(r.status_code))
v = r.json()
check("shows the holder and course", v["holderName"] == "Budi Santoso" and v["valid"] is True)
check("does NOT expose the email", "email" not in v, str(list(v)))
check("lowercase code still verifies",
      anon.get(f"/certificates/{code.lower()}").status_code == 200)
check("unknown code → 404", anon.get("/certificates/ESC-MEN-00000").status_code == 404)

print("\n== revocation ==")
db2 = SessionLocal()
row = db2.query(Certificate).filter(Certificate.code == code).first()
row.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
db2.commit()
db2.close()
v = anon.get(f"/certificates/{code}").json()
check("revoked verifies as invalid rather than vanishing",
      v["valid"] is False and v["code"] == code)

print("\n== other people's certificates ==")
db3 = SessionLocal()
other = db3.query(User).filter(User.id != learner_id).first()
t2 = new_session_token()
db3.add(AuthSession(
    user_id=other.id, token_hash=hash_token(t2),
    expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)))
db3.commit()
db3.close()
other_client = TestClient(app)
other_client.cookies.set(SESSION_COOKIE, t2)
check("another account has none of them",
      other_client.get("/me/certificates").json() == [])

# cleanup
db4 = SessionLocal()
db4.query(Certificate).filter(Certificate.user_id == learner_id).delete()
db4.query(LearningProgress).filter(LearningProgress.user_id == learner_id).delete()
u = db4.get(User, learner_id)
u.first_name, u.last_name = None, None
db4.query(AuthSession).filter(
    AuthSession.token_hash.in_([hash_token(token), hash_token(t2)])).delete(
    synchronize_session=False)
db4.commit()
db4.close()

print(f"\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("Phase 3 API verification PASSED")
