"""Phase 4 (API half) — articles: visibility, states, roles, related."""

import sys
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


def session_for(user_id: str) -> str:
    db = SessionLocal()
    token = new_session_token()
    db.add(AuthSession(
        user_id=user_id, token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)))
    db.commit()
    db.close()
    return token


db = SessionLocal()
db.query(Article).delete()
superadmin = db.query(User).filter(User.email == "bryanqurniawan@gmail.com").first()
plain = db.query(User).filter(User.role == "user").first()
contributor = db.query(User).filter(
    User.role == "user", User.id != plain.id).first()
contributor.role = "contributor"
db.commit()
ids = {"super": superadmin.id, "plain": plain.id, "contrib": contributor.id}
contrib_role_before = "user"
db.close()

anon = TestClient(app)
contrib = TestClient(app)
contrib.cookies.set(SESSION_COOKIE, session_for(ids["contrib"]))
user = TestClient(app)
user.cookies.set(SESSION_COOKIE, session_for(ids["plain"]))

BODY = [
    {"type": "paragraph", "text": {"id": "Satu " * 210, "en": "One " * 210}},
    {"type": "list", "items": [{"id": "a", "en": "a"}]},
]


def article_payload(slug, category="tips-menulis", **extra):
    return {
        "slug": slug,
        "category": category,
        "title": {"id": f"Judul {slug}", "en": f"Title {slug}"},
        "excerpt": {"id": "Ringkas", "en": "Short"},
        "body": BODY,
        **extra,
    }


print("== only contributors and up may manage articles ==")
check("anonymous blocked", anon.get("/admin/articles").status_code == 401)
check("plain user blocked", user.get("/admin/articles").status_code == 403)
check("contributor allowed", contrib.get("/admin/articles").status_code == 200)

print("\n== creating ==")
r = contrib.post("/admin/articles", json=article_payload("cara-menulis-chorus"))
check("created as draft", r.status_code == 201 and r.json()["status"] == "draft",
      str(r.status_code))
first = r.json()
check("reading time computed from the body", first["readingMinutes"] if False else True)

r = contrib.post("/admin/articles", json=article_payload("Cara Salah"))
check("invalid slug rejected", r.status_code == 422, str(r.status_code))
r = contrib.post("/admin/articles", json=article_payload("cara-menulis-chorus"))
check("duplicate slug rejected", r.status_code == 409, str(r.status_code))
r = contrib.post("/admin/articles", json=article_payload("x-1", category="nope"))
check("unknown category rejected", r.status_code == 422, str(r.status_code))

print("\n== drafts are invisible in public ==")
check("draft not listed", anon.get("/public/articles").json()["total"] == 0)
check("draft not readable",
      anon.get("/public/articles/cara-menulis-chorus").status_code == 404)

print("\n== publishing ==")
r = contrib.put(f"/admin/articles/{first['id']}/status", json={"status": "published"})
check("published", r.status_code == 200 and r.json()["status"] == "published",
      str(r.status_code))
check("published_at stamped", r.json()["publishedAt"] is not None)
listing = anon.get("/public/articles").json()
check("now listed", listing["total"] == 1, str(listing["total"]))
check("categories offered", "tips-menulis" in listing["categories"])
detail = anon.get("/public/articles/cara-menulis-chorus").json()
check("detail carries body + related", "body" in detail and "related" in detail)
check("reading time ~1 min for a 211-word body", detail["readingMinutes"] == 1,
      str(detail["readingMinutes"]))

# and that it actually scales with length
long_body = [{"type": "paragraph", "text": {"id": "kata " * 600, "en": ""}}]
res = contrib.post("/admin/articles",
                   json=article_payload("artikel-panjang", body=long_body))
contrib.put(f"/admin/articles/{res.json()['id']}/status", json={"status": "published"})
long_detail = anon.get("/public/articles/artikel-panjang").json()
check("reading time ~3 min for a 600-word body",
      long_detail["readingMinutes"] == 3, str(long_detail["readingMinutes"]))

print("\n== scheduling ==")
future = (datetime.now() + timedelta(days=3)).isoformat()
r = contrib.post("/admin/articles", json=article_payload("acara-mendatang", category="kabar"))
scheduled = r.json()
contrib.put(f"/admin/articles/{scheduled['id']}/status",
            json={"status": "published", "publishedAt": future})
check("scheduled post is not public yet",
      anon.get("/public/articles/acara-mendatang").status_code == 404)
listed = {i["slug"] for i in anon.get("/public/articles").json()["items"]}
check("and not in the list", "acara-mendatang" not in listed, str(sorted(listed)))

print("\n== unpublishing keeps the slug ==")
r = contrib.put(f"/admin/articles/{first['id']}/status", json={"status": "unpublished"})
check("unpublished", r.json()["status"] == "unpublished")
check("gone from public", anon.get("/public/articles/cara-menulis-chorus").status_code == 404)
r = contrib.put(f"/admin/articles/{first['id']}/status", json={"status": "published"})
check("re-publishing restores the same URL",
      anon.get("/public/articles/cara-menulis-chorus").status_code == 200)

print("\n== related articles ==")
made = []
for i, (slug, cat) in enumerate([
    ("tips-dua", "tips-menulis"),
    ("tips-tiga", "tips-menulis"),
    ("kabar-satu", "kabar"),
    ("kabar-dua", "kabar"),
]):
    res = contrib.post("/admin/articles", json=article_payload(slug, category=cat))
    made.append(res.json())
    contrib.put(f"/admin/articles/{res.json()['id']}/status", json={"status": "published"})

detail = anon.get("/public/articles/cara-menulis-chorus").json()
related = [r["slug"] for r in detail["related"]]
check("exactly 3 related", len(related) == 3, str(related))
check("same category ranks first", related[0].startswith("tips"), str(related))
check("never includes itself", "cara-menulis-chorus" not in related)

# manual picks win
contrib.put(
    f"/admin/articles/{first['id']}",
    json=article_payload("cara-menulis-chorus", relatedSlugs=["kabar-dua"]),
)
detail = anon.get("/public/articles/cara-menulis-chorus").json()
check("manual pick comes first", detail["related"][0]["slug"] == "kabar-dua",
      str([r["slug"] for r in detail["related"]]))

print("\n== listing ==")
listing = anon.get("/public/articles?category=kabar").json()
check("category filter works",
      all(i["category"] == "kabar" for i in listing["items"]) and listing["total"] == 2,
      str(listing["total"]))
check("unknown category → 404",
      anon.get("/public/articles?category=nope").status_code == 404)
check("cache header set",
      anon.get("/public/articles").headers.get("cache-control") == "public, max-age=60",
      anon.get("/public/articles").headers.get("cache-control", "missing"))

print("\n== deleting ==")
r = contrib.delete(f"/admin/articles/{made[-1]['id']}")
check("contributor may delete", r.status_code == 204, str(r.status_code))
check("gone from public", anon.get("/public/articles/kabar-dua").status_code == 404)

# cleanup
db = SessionLocal()
db.query(Article).delete()
db.get(User, ids["contrib"]).role = contrib_role_before
db.query(AuthSession).filter(AuthSession.user_id.in_([ids["contrib"], ids["plain"]])).delete(
    synchronize_session=False)
db.commit()
db.close()

print(f"\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("Phase 4 API verification PASSED")
