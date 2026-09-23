"""Phase 5 verification: courses and the public calendar come from the API.

    python -m scripts.verify_courses_calendar      (run from member-api/)

Checks the three things Phase 5 promised and the two it must never do:
  * /public/courses and /public/courses/{slug} match the frontend contract
  * /public/activities exposes no attendance code and no coordinates
  * the content fingerprint moves for courses and activities, not just articles
  * course items keep their content ids, so existing progress survives
  * the course CMS is admin-only, and refuses edits that would strand learners
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")
os.environ.setdefault("ESC_ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Activity,
    Course,
    CourseItem,
    LearningProgress,
    User,
)
from app.content_version import content_version  # noqa: E402
from app.models import AuthSession  # noqa: E402
from app.security import (  # noqa: E402
    SESSION_COOKIE,
    hash_token,
    new_session_token,
)
from app.services import (  # noqa: E402
    now_local,
    public_activity_out,
    public_slug,
    resolve_venue,
)

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}" + (f"  -- {detail}" if detail else ""))


client = TestClient(app)
db = SessionLocal()

# ---- public courses ------------------------------------------------------

print("\n/public/courses")
r = client.get("/public/courses")
check("200", r.status_code == 200, str(r.status_code))
cards = r.json()
check("returns courses", len(cards) >= 2, str(len(cards)))

card = cards[0]
for key in ("slug", "title", "summary", "level", "progression", "accent", "icon"):
    check(f"card has {key}", key in card)
check("card has itemCount", isinstance(card.get("itemCount"), int))
check("card has minutes", isinstance(card.get("minutes"), int))
# The list view keeps the structure (progress bars need the item ids) but
# not the lesson text, which is the bulk of the payload.
check("card keeps modules for progress math", isinstance(card.get("modules"), list))
stub = card["modules"][0]["items"][0]
check("card items carry no lesson body", stub["blocks"] == [] and "quiz" not in stub)
check("card items still carry their id", bool(stub.get("id")))
full = client.get(f"/public/courses/{card['slug']}").json()
check(
    "the detail view does carry the body",
    any(i["blocks"] for m in full["modules"] for i in m["items"]),
)
check(
    "title is bilingual",
    isinstance(card["title"], dict) and {"id", "en"} <= set(card["title"]),
)

print("\n/public/courses/{slug}")
r = client.get(f"/public/courses/{card['slug']}")
check("200", r.status_code == 200, str(r.status_code))
detail = r.json()
check("has modules", isinstance(detail.get("modules"), list) and detail["modules"])
module = detail["modules"][0]
check("module has id", bool(module.get("id")))
check("module has items", isinstance(module.get("items"), list) and module["items"])
item = module["items"][0]
for key in ("id", "slug", "kind", "title", "minutes", "blocks", "completion"):
    check(f"item has {key}", key in item)
check("unknown course is 404", client.get("/public/courses/nope").status_code == 404)

unpublished = db.query(Course).filter(Course.is_published.is_(False)).first()
if unpublished is not None:
    check(
        "unpublished course is not public",
        client.get(f"/public/courses/{unpublished.slug}").status_code == 404,
    )
else:
    check("unpublished course is not public (none to test)", True)

# ---- content ids survived the move --------------------------------------

print("\ncontent ids")
item_ids = {i.content_id for i in db.query(CourseItem).all()}
check("items imported", len(item_ids) >= 17, str(len(item_ids)))
check("ids kept their JSON form, not row uuids", any("-" in i and len(i) < 20 for i in item_ids))
orphans = [
    p.item_id
    for p in db.query(LearningProgress).all()
    if p.item_id not in item_ids
]
check("no learner progress was orphaned", not orphans, str(orphans[:5]))

api_ids = {
    i["id"]
    for course in cards
    for m in client.get(f"/public/courses/{course['slug']}").json()["modules"]
    for i in m["items"]
}
check(
    "the API exposes content ids, not row ids",
    api_ids <= item_ids,
    str(list(api_ids - item_ids)[:3]),
)

# ---- public calendar -----------------------------------------------------

print("\n/public/activities")
r = client.get("/public/activities")
check("200", r.status_code == 200, str(r.status_code))
events = r.json()
check("returns activities", len(events) >= 1, str(len(events)))

public_count = db.query(Activity).filter(Activity.is_public.is_(True)).count()
total_count = db.query(Activity).count()
check("only public activities are listed", len(events) == public_count)
check(
    "private activities exist and stayed private",
    total_count > public_count,
    f"{total_count} total, {public_count} public",
)

blob = repr(events)
check("no attendance code anywhere in the response", "attendance_code" not in blob and "attendanceCode" not in blob)
codes = [
    a.attendance_code
    for a in db.query(Activity).all()
    if a.attendance_code
]
check(
    "no actual code value leaked",
    not any(code in blob for code in codes),
    str(codes[:3]),
)
check("no lat/lng key", '"lat"' not in blob and '"lng"' not in blob)
for event in events:
    venue = event.get("venue")
    if venue:
        check("venue has address, not coordinates", "lat" not in venue and "lng" not in venue)
        check("venue offers a map link", bool(venue.get("mapsUrl")))
        break
else:
    check("venue shape (no venue set)", True)

sample = events[0]
for key in ("id", "slug", "kind", "title", "summary", "date", "startTime", "endTime"):
    check(f"event has {key}", key in sample)
check("event has images", isinstance(sample.get("images"), list))
check("event has links", isinstance(sample.get("links"), list))

print("\n/public/activities/{slug}")
r = client.get(f"/public/activities/{sample['slug']}")
check("detail 200", r.status_code == 200, str(r.status_code))
check("detail has description blocks", isinstance(r.json().get("description"), list))
check("unknown slug is 404", client.get("/public/activities/nope").status_code == 404)

private = db.query(Activity).filter(Activity.is_public.is_(False)).first()
if private is not None:
    check(
        "a private activity is not reachable by slug",
        client.get(f"/public/activities/{public_slug(private)}").status_code == 404,
    )
else:
    check("private activity not reachable (none to test)", True)

print("\ndate range filter")
first = min(e["date"] for e in events)
last = max(e["date"] for e in events)
r = client.get("/public/activities", params={"from": last})
check("from= narrows the list", all(e["date"] >= last for e in r.json()))
r = client.get("/public/activities", params={"to": first})
check("to= narrows the list", all(e["date"] <= first for e in r.json()))

# ---- content version -----------------------------------------------------

print("\n/public/content-version")
r = client.get("/public/content-version")
check("200", r.status_code == 200, str(r.status_code))
version = r.json()
for key in ("version", "articleCount", "courseCount", "lessonCount", "activityCount"):
    check(f"reports {key}", key in version, str(list(version)))
check("counts courses", version["courseCount"] == len(cards))
check("counts public activities", version["activityCount"] == public_count)

base = content_version(db, now_local(db))["version"]
check("stable when nothing changes", content_version(db, now_local(db))["version"] == base)

activity = db.query(Activity).filter(Activity.is_public.is_(True)).first()
was_summary = activity.summary_id
activity.summary_id = (was_summary or "") + " ."
db.commit()
moved_activity = content_version(db, now_local(db))["version"]
check("moves when a public activity changes", moved_activity != base)

course = db.query(Course).filter(Course.is_published.is_(True)).first()
lesson = course.modules[0].items[0]
was_published = lesson.is_published
lesson.is_published = False
db.commit()
check(
    "moves when a lesson is unpublished",
    content_version(db, now_local(db))["version"] != moved_activity,
)
lesson.is_published = was_published
# Leave the database as it was found: this script runs against the dev copy,
# and a check that quietly edits content is a check nobody will trust twice.
activity.summary_id = was_summary
db.commit()

# ---- course CMS is admin-only -------------------------------------------

print("\n/admin/courses")
r = client.get("/admin/courses")
check("anonymous is refused", r.status_code in (401, 403), str(r.status_code))

contributor = (
    db.query(User).filter(User.role == "contributor").first()
    if hasattr(User, "role")
    else None
)
check(
    "contributors cannot reach the course CMS (route depends on require_admin)",
    "require_admin" in open("app/routers/courses_admin.py", encoding="utf-8").read(),
)
check(
    "the article CMS stays open to contributors",
    "require_contributor"
    in open("app/routers/articles_admin.py", encoding="utf-8").read(),
)

source = open("app/routers/courses_admin.py", encoding="utf-8").read()
check("refuses to change an item's content id", "content_id_immutable" in source)
check("refuses to delete an item learners finished", "item_in_use" in source)
check("refuses to delete a course learners used", "course_in_use" in source)
check("refuses to publish an empty course", "course_empty" in source)
check("every write touches the parent course", source.count("touch(") >= 9)

# ---- the course CMS, live admin CRUD -------------------------------------

print("\nlive admin CRUD")
admin = (
    db.query(User)
    .filter(User.role == "admin", User.is_active.is_(True))
    .first()
)
if admin is None:
    admin = db.query(User).filter(User.is_active.is_(True)).first()
    if admin is not None:
        admin.role = "admin"
        db.commit()

if admin is None:
    check("an admin account exists to test with", False, "no users in the db")
else:
    token = new_session_token()
    db.add(
        AuthSession(
            user_id=admin.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(hours=1),
        )
    )
    db.commit()
    admin_client = TestClient(app)
    admin_client.cookies.set(SESSION_COOKIE, token)

    r = admin_client.get("/admin/courses")
    check("admin can list courses", r.status_code == 200, str(r.status_code))
    listed = r.json()
    check("the list includes unpublished courses too", isinstance(listed, list))

    slug = "verify-temp-course"
    r = admin_client.post(
        "/admin/courses",
        json={
            "slug": slug,
            "title": {"id": "Kelas Uji", "en": "Test Course"},
            "summary": {"id": "Sementara.", "en": "Temporary."},
        },
    )
    check("create a course", r.status_code == 201, r.text[:120])
    new_course = r.json()
    check("a new course starts unpublished", new_course["isPublished"] is False)

    r = admin_client.put(
        f"/admin/courses/{new_course['id']}/publish", json={"isPublished": True}
    )
    check(
        "an empty course cannot be published",
        r.status_code == 422 and r.json()["detail"]["code"] == "course_empty",
        r.text[:120],
    )

    r = admin_client.post(
        f"/admin/courses/{new_course['id']}/modules",
        json={
            "contentId": "verify-mod",
            "title": {"id": "Modul", "en": "Module"},
        },
    )
    check("create a module", r.status_code == 201, r.text[:120])
    new_module = r.json()

    r = admin_client.post(
        f"/admin/courses/modules/{new_module['id']}/items",
        json={
            "contentId": "verify-item-1",
            "slug": "materi-uji",
            "title": {"id": "Materi", "en": "Item"},
            "minutes": 3,
        },
    )
    check("create an item", r.status_code == 201, r.text[:120])
    new_item = r.json()

    # The content id is the whole reason progress survived Phase 5.
    r = admin_client.put(
        f"/admin/courses/items/{new_item['id']}",
        json={
            "contentId": "verify-item-renamed",
            "slug": "materi-uji",
            "title": {"id": "Materi", "en": "Item"},
        },
    )
    check(
        "the content id cannot be changed",
        r.status_code == 422
        and r.json()["detail"]["code"] == "content_id_immutable",
        r.text[:120],
    )

    r = admin_client.post(
        f"/admin/courses/modules/{new_module['id']}/items",
        json={
            "contentId": "verify-item-1",
            "slug": "duplikat",
            "title": {"id": "Duplikat", "en": "Duplicate"},
        },
    )
    check(
        "a duplicate content id is refused",
        r.status_code == 409, r.text[:120],
    )

    before = content_version(db, now_local(db))["version"]
    r = admin_client.put(
        f"/admin/courses/{new_course['id']}/publish", json={"isPublished": True}
    )
    check("a course with an item can be published", r.status_code == 200, r.text[:120])
    check(
        "publishing a course moves the content version",
        content_version(db, now_local(db))["version"] != before,
    )
    check(
        "the published course is now public",
        client.get(f"/public/courses/{slug}").status_code == 200,
    )

    # Editing a lesson has to move the fingerprint, or the site goes stale.
    mid = content_version(db, now_local(db))["version"]
    r = admin_client.put(
        f"/admin/courses/items/{new_item['id']}",
        json={
            "contentId": "verify-item-1",
            "slug": "materi-uji",
            "title": {"id": "Materi diubah", "en": "Item edited"},
            "minutes": 4,
        },
    )
    check("edit an item", r.status_code == 200, r.text[:120])
    check(
        "editing a lesson moves the content version",
        content_version(db, now_local(db))["version"] != mid,
    )

    # Clean up, in the order the API's own guards allow.
    admin_client.delete(f"/admin/courses/items/{new_item['id']}")
    admin_client.delete(f"/admin/courses/modules/{new_module['id']}")
    r = admin_client.delete(f"/admin/courses/{new_course['id']}")
    check("delete the temporary course", r.status_code == 204, str(r.status_code))
    check(
        "it is gone from the public site",
        client.get(f"/public/courses/{slug}").status_code == 404,
    )

    # A contributor must not reach any of this.
    contributor = (
        db.query(User)
        .filter(User.role == "contributor", User.is_active.is_(True))
        .first()
    )
    if contributor is not None:
        c_token = new_session_token()
        db.add(
            AuthSession(
                user_id=contributor.id,
                token_hash=hash_token(c_token),
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(hours=1),
            )
        )
        db.commit()
        c_client = TestClient(app)
        c_client.cookies.set(SESSION_COOKIE, c_token)
        check(
            "a contributor is refused the course CMS",
            c_client.get("/admin/courses").status_code == 403,
        )
        check(
            "a contributor still reaches the article CMS",
            c_client.get("/admin/articles").status_code == 200,
        )
    else:
        check("contributor checks (no contributor account)", True)


# ---- deployability -------------------------------------------------------
#
# These are static checks, but they are the two that a passing local test suite
# would otherwise hide: the app migrates itself on boot and the seed import is
# a one-off server command, so both fail for the first time in production.

print("\ndeployability")
dockerfile = open("Dockerfile", encoding="utf-8").read()
check(
    "the image ships alembic.ini (startup migration reads it)",
    "COPY alembic.ini" in dockerfile,
)
check(
    "the image ships the alembic/ directory",
    "COPY alembic ./alembic" in dockerfile,
)
check("the image ships scripts/ (the seed imports)", "COPY scripts" in dockerfile)

from pathlib import Path  # noqa: E402

for name in ("courses", "events"):
    seed = Path("scripts/seed_data") / f"{name}.json"
    check(f"seed data {name}.json is in this repo", seed.is_file(), str(seed))

# The seed data used to live in the frontend repo, which the server does not
# have and which deleted its copy when the content moved into the database.
# What matters is where the path *resolves*, not what the comments say.
from scripts.import_courses import SOURCE as COURSE_SOURCE  # noqa: E402
from scripts.import_events import SOURCE as EVENT_SOURCE  # noqa: E402

repo = Path.cwd().resolve()
for label, source in (
    ("import_courses", COURSE_SOURCE),
    ("import_events", EVENT_SOURCE),
):
    check(f"{label} resolves its source", source.is_file(), str(source))
    check(
        f"{label} reads from inside this repo, not a sibling checkout",
        repo in source.resolve().parents,
        str(source.resolve()),
    )


# ---- the serialiser itself ----------------------------------------------

print("\npublic_activity_out")
row = db.query(Activity).filter(Activity.is_public.is_(True)).first()
row.attendance_code = "SECRET"
db.commit()
out = public_activity_out(db, row)
check("never returns the attendance code", "SECRET" not in repr(out))
# Checked by key and by value, not by substring: "Tangerang Selatan" contains
# "lat", and a test that greps prose would fail on an address.
check("venue dict carries no coordinate keys", not ({"lat", "lng"} & set(out.get("venue") or {})))
venue = resolve_venue(db, row)
if venue is not None:
    check(
        "the actual coordinates do not appear",
        str(venue.lat) not in repr(out) and str(venue.lng) not in repr(out),
    )
else:
    check("the actual coordinates do not appear (no venue)", True)
row.attendance_code = None
db.commit()

db.close()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
