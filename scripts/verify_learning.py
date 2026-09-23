"""Phase 2 acceptance test — progress on the account (SPEC-LRN-05, LRN-06).

Uses a plain `user` (not a member) on purpose: learning must work for someone
who never registered with the club.
"""

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"C:\Users\bryan\Desktop\Ongoing\ESC - Copy\member-api")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuthSession, LearningDraft, LearningProgress, User  # noqa: E402
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
learner = db.query(User).filter(
    User.role == "user", User.security_passed.is_(False)).first()
print(f"learner: {learner.email} (role={learner.role}, member=no)")

# clean slate for a repeatable run
db.query(LearningProgress).filter(LearningProgress.user_id == learner.id).delete()
db.query(LearningDraft).filter(LearningDraft.user_id == learner.id).delete()
token = new_session_token()
db.add(AuthSession(
    user_id=learner.id,
    token_hash=hash_token(token),
    expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
))
db.commit()
learner_id = learner.id
db.close()

client = TestClient(app)

print("\n== signed out ==")
anon = TestClient(app)
check("anonymous cannot read progress", anon.get("/me/learning").status_code == 401)
check("anonymous cannot save progress",
      anon.put("/me/learning/items/lyr-1",
               json={"courseSlug": "menulis-lirik-dasar"}).status_code == 401)

client.cookies.set(SESSION_COOKIE, token)

print("\n== a non-member user can learn ==")
r = client.get("/me/learning")
check("empty state readable", r.status_code == 200 and r.json()["items"] == [],
      str(r.status_code))

r = client.put("/me/learning/items/lyr-1",
               json={"courseSlug": "menulis-lirik-dasar", "via": "manual"})
check("mark complete", r.status_code == 200 and len(r.json()["items"]) == 1,
      str(r.status_code))

first_ts = r.json()["items"][0]["completedAt"]
r = client.put("/me/learning/items/lyr-1",
               json={"courseSlug": "menulis-lirik-dasar", "via": "manual"})
check("completing twice is idempotent", len(r.json()["items"]) == 1)
check("original timestamp kept", r.json()["items"][0]["completedAt"] == first_ts)

r = client.put("/me/learning/items/lyr-3",
               json={"courseSlug": "menulis-lirik-dasar", "via": "timer"})
check("timer completion recorded",
      any(i["via"] == "timer" for i in r.json()["items"]))

r = client.put("/me/learning/items/lyr-9", json={"courseSlug": "x", "via": "nonsense"})
check("invalid via rejected", r.status_code == 422, str(r.status_code))

r = client.delete("/me/learning/items/lyr-3")
check("mark incomplete", len(r.json()["items"]) == 1)

print("\n== drafts ==")
r = client.put("/me/learning/drafts/lyr-3", json={"text": "kunci rumah, dingin, berkarat"})
check("draft saved", r.json()["drafts"][0]["text"].startswith("kunci rumah"))
r = client.put("/me/learning/drafts/lyr-3", json={"text": "x" * 25000})
check("oversized draft is capped at 20k",
      len(r.json()["drafts"][0]["text"]) == 20000,
      str(len(r.json()["drafts"][0]["text"])))
r = client.put("/me/learning/drafts/lyr-3", json={"text": ""})
check("clearing a draft removes it", r.json()["drafts"] == [])

print("\n== one-time merge from localStorage ==")
local = {
    "items": [
        {"itemId": "lyr-1", "courseSlug": "menulis-lirik-dasar", "via": "manual"},
        {"itemId": "lyr-2", "courseSlug": "menulis-lirik-dasar", "via": "manual"},
        {"itemId": "ow-1", "courseSlug": "object-writing-101", "via": "manual"},
    ],
    "drafts": [{"itemId": "ow-3", "text": "sepuluh menit tentang payung basah"}],
}
r = client.post("/me/learning/merge", json=local)
state = r.json()
ids = {i["itemId"] for i in state["items"]}
check("merge adds the missing items", ids == {"lyr-1", "lyr-2", "ow-1"}, str(ids))
check("merge keeps the account's own timestamp for lyr-1",
      next(i for i in state["items"] if i["itemId"] == "lyr-1")["completedAt"] == first_ts)
check("merge imports drafts", len(state["drafts"]) == 1)

r2 = client.post("/me/learning/merge", json=local)
check("merge is idempotent", len(r2.json()["items"]) == 3,
      f"{len(r2.json()['items'])} items")

print("\n== progress is per account ==")
other = TestClient(app)
db2 = SessionLocal()
someone = db2.query(User).filter(User.id != learner_id).first()
t2 = new_session_token()
db2.add(AuthSession(
    user_id=someone.id, token_hash=hash_token(t2),
    expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)))
db2.commit()
db2.close()
other.cookies.set(SESSION_COOKIE, t2)
check("another account sees none of it", other.get("/me/learning").json()["items"] == [])

# cleanup
db3 = SessionLocal()
db3.query(LearningProgress).filter(LearningProgress.user_id == learner_id).delete()
db3.query(LearningDraft).filter(LearningDraft.user_id == learner_id).delete()
db3.query(AuthSession).filter(
    AuthSession.token_hash.in_([hash_token(token), hash_token(t2)])).delete(
    synchronize_session=False)
db3.commit()
db3.close()

print(f"\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("Phase 2 API verification PASSED")
