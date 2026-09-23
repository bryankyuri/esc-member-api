"""Import the frontend's course JSON into the database, once.

    python -m scripts.import_courses [--force]

Phase 5 moves course content out of
`public-frontend/src/content/data/courses.json` and into the CMS. This carries
the existing content across so nothing has to be retyped.

The important part is `content_id`: every item keeps the id it had in the JSON
("lyr-1", "ow-3"), because `learning_progress` rows already point at those.
Anyone who finished a lesson before the move still has it afterwards.

Idempotent: a course that already exists is skipped unless --force, which
replaces its modules and items while keeping the same content ids.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.db import SessionLocal  # noqa: E402
from app.models import Course, CourseItem, CourseModule  # noqa: E402

# Lives here, not in the frontend repo. The frontend's copy was deleted when
# the content moved into the database, and pointing at a sibling checkout would
# not work on the server anyway — the container has only this repo.
SOURCE = Path(__file__).resolve().parent / "seed_data" / "courses.json"


def main() -> int:
    force = "--force" in sys.argv
    if not SOURCE.exists():
        print(f"course JSON not found: {SOURCE}")
        return 1

    courses = json.loads(SOURCE.read_text(encoding="utf-8"))
    db = SessionLocal()

    for order, data in enumerate(courses):
        existing = db.query(Course).filter(Course.slug == data["slug"]).first()
        if existing is not None and not force:
            print(f"skip {data['slug']} (already imported)")
            continue
        if existing is not None:
            # Replacing content, not identity: cascade removes the old modules
            # and items, and the ids below are re-used verbatim.
            db.delete(existing)
            db.flush()

        course = Course(
            slug=data["slug"],
            title_id=data["title"]["id"],
            title_en=data["title"].get("en", ""),
            summary_id=data["summary"]["id"],
            summary_en=data["summary"].get("en", ""),
            level=data.get("level", "beginner"),
            progression=data.get("progression", "linear"),
            accent=data.get("accent", "#ffc778"),
            icon=data.get("icon", "✍️"),
            outcomes=data.get("outcomes", []),
            is_published=True,
            sort_order=order,
        )
        db.add(course)
        db.flush()

        items_total = 0
        for m_order, module_data in enumerate(data.get("modules", [])):
            module = CourseModule(
                course_id=course.id,
                content_id=module_data["id"],
                title_id=module_data["title"]["id"],
                title_en=module_data["title"].get("en", ""),
                summary_id=(module_data.get("summary") or {}).get("id", ""),
                summary_en=(module_data.get("summary") or {}).get("en", ""),
                unlock_after_module=module_data.get("unlockAfterModule"),
                sort_order=m_order,
            )
            db.add(module)
            db.flush()

            for i_order, item in enumerate(module_data.get("items", [])):
                db.add(
                    CourseItem(
                        module_id=module.id,
                        # The id learners' progress already points at.
                        content_id=item["id"],
                        slug=item["slug"],
                        kind=item.get("kind", "lesson"),
                        title_id=item["title"]["id"],
                        title_en=item["title"].get("en", ""),
                        minutes=item.get("minutes", 5),
                        video_url=item.get("videoUrl"),
                        blocks=item.get("blocks", []),
                        quiz=item.get("quiz"),
                        tool=item.get("tool"),
                        prerequisites=item.get("prerequisites", []),
                        completion=item.get("completion", {"kind": "manual"}),
                        is_published=True,
                        sort_order=i_order,
                    )
                )
                items_total += 1

        print(
            f"imported {data['slug']}: {len(data.get('modules', []))} modules, "
            f"{items_total} items"
        )

    db.commit()
    db.close()
    print("\ndone — course content now lives in the database")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
