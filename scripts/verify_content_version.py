"""SPEC-ART-07 — the content fingerprint moves only when the public site would
actually look different, so a rebuild is spent only when it is worth it."""

import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"C:\Users\bryan\Desktop\Ongoing\ESC - Copy\member-api")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Article, AuthSession, User  # noqa: E402
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
db.query(Article).filter(Article.slug.like("ver-test%")).delete()
admin = db.query(User).filter(User.role == "admin").first()
token = new_session_token()
db.add(AuthSession(
    user_id=admin.id, token_hash=hash_token(token),
    expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)))
db.commit()
db.close()

client = TestClient(app)
client.cookies.set(SESSION_COOKIE, token)
anon = TestClient(app)


def version() -> str:
    return anon.get("/public/content-version").json()["version"]


def payload(slug: str) -> dict:
    return {
        "slug": slug,
        "category": "kabar",
        "title": {"id": f"Judul {slug}", "en": f"Title {slug}"},
        "excerpt": {"id": "Ringkas", "en": "Short"},
        "body": [{"type": "paragraph", "text": {"id": "Isi", "en": "Body"}}],
    }


print("== the endpoint itself ==")
res = anon.get("/public/content-version")
check("public, no auth needed", res.status_code == 200, str(res.status_code))
body = res.json()
check("reports a version and a count",
      "version" in body and "articleCount" in body, str(list(body)))
check("is cacheable", res.headers.get("cache-control") == "public, max-age=30",
      res.headers.get("cache-control", "missing"))
check("stable when nothing happens", version() == version())

print("\n== drafts cost nothing ==")
before = version()
created = client.post("/admin/articles", json=payload("ver-test-satu")).json()
check("creating a draft does not move it", version() == before)
client.put(f"/admin/articles/{created['id']}", json=payload("ver-test-satu"))
check("editing a draft does not move it", version() == before)

print("\n== publishing moves it ==")
client.put(f"/admin/articles/{created['id']}/status", json={"status": "published"})
after_publish = version()
check("publishing moves it", after_publish != before, f"{before} → {after_publish}")
check("count went up",
      anon.get("/public/content-version").json()["articleCount"] >= 1)

print("\n== editing a published article moves it ==")
time.sleep(1.1)  # updated_at has second resolution
edited = payload("ver-test-satu")
edited["title"] = {"id": "Judul baru", "en": "New title"}
client.put(f"/admin/articles/{created['id']}", json=edited)
after_edit = version()
check("editing a live article moves it", after_edit != after_publish,
      f"{after_publish} → {after_edit}")

print("\n== taking it down moves it ==")
client.put(f"/admin/articles/{created['id']}/status", json={"status": "unpublished"})
after_down = version()
check("unpublishing moves it", after_down != after_edit,
      f"{after_edit} → {after_down}")
check("and it equals the pre-publish state (nothing public again)",
      after_down == before, f"{after_down} vs {before}")

print("\n== a scheduled post moves it when its time arrives ==")
soon = (datetime.now() + timedelta(seconds=2)).isoformat()
scheduled = client.post("/admin/articles", json=payload("ver-test-dua")).json()
client.put(f"/admin/articles/{scheduled['id']}/status",
           json={"status": "published", "publishedAt": soon})
while_waiting = version()
check("still unchanged while it is in the future", while_waiting == after_down,
      f"{while_waiting} vs {after_down}")
check("but the poller is told when to expect it",
      anon.get("/public/content-version").json()["nextScheduledAt"] is not None)
time.sleep(2.5)
check("moves once due, with no row being written", version() != while_waiting,
      f"{while_waiting} → {version()}")

print("\n== deleting ==")
before_delete = version()
draft = client.post("/admin/articles", json=payload("ver-test-tiga")).json()
client.delete(f"/admin/articles/{draft['id']}")
check("deleting a draft does not move it", version() == before_delete)
client.delete(f"/admin/articles/{scheduled['id']}")
check("deleting a published article moves it", version() != before_delete)

# cleanup
db = SessionLocal()
db.query(Article).filter(Article.slug.like("ver-test%")).delete()
db.query(AuthSession).filter(AuthSession.token_hash == hash_token(token)).delete()
db.commit()
db.close()

print(f"\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("Content-version verification PASSED")
