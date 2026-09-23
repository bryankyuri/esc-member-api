"""Seed sample articles for local development.

    python -m scripts.seed_articles

Dummy content for the prototype (decision, 2026-09-23): real posts arrive
through the CMS. Safe to re-run — it replaces the samples it created.
"""

from __future__ import annotations

import sys
from datetime import timedelta

sys.path.insert(0, ".")

from app.db import SessionLocal  # noqa: E402
from app.models import Article, User  # noqa: E402
from app.services import now_local  # noqa: E402


def block(text_id: str, text_en: str) -> dict:
    return {"type": "paragraph", "text": {"id": text_id, "en": text_en}}


SAMPLES = [
    {
        "slug": "cara-menulis-chorus-yang-nempel",
        "category": "tips-menulis",
        "featured": True,
        "title": {
            "id": "Cara menulis chorus yang nempel di kepala",
            "en": "How to write a chorus people remember",
        },
        "excerpt": {
            "id": "Chorus yang diingat orang jarang yang paling rumit. Biasanya yang paling jujur.",
            "en": "The choruses people remember are rarely the cleverest. Usually they are the most honest.",
        },
        "body": [
            block(
                "Chorus adalah bagian yang paling sering diulang, jadi ia harus tahan diulang. "
                "Kalau satu baris terasa pintar di pendengaran pertama tapi membosankan di "
                "pendengaran kelima, baris itu belum selesai.",
                "A chorus is the part that repeats most, so it has to survive repetition. If a "
                "line feels clever the first time and tiring the fifth, it is not finished.",
            ),
            {
                "type": "list",
                "items": [
                    {
                        "id": "Tulis satu kalimat inti dulu, baru bangun barisnya di sekitar itu.",
                        "en": "Write the one line first, then build the rest around it.",
                    },
                    {
                        "id": "Baca keras-keras. Kalau tersandung, pendengar juga akan tersandung.",
                        "en": "Read it aloud. If you stumble, so will the listener.",
                    },
                ],
            },
            {
                "type": "tip",
                "text": {
                    "id": "Kalau chorus-mu butuh penjelasan, itu belum chorus.",
                    "en": "If your chorus needs explaining, it is not a chorus yet.",
                },
            },
        ],
    },
    {
        "slug": "catatan-sesi-object-writing-september",
        "category": "catatan-sesi",
        "title": {
            "id": "Catatan sesi: sepuluh menit tentang kunci rumah",
            "en": "Session notes: ten minutes about a house key",
        },
        "excerpt": {
            "id": "Empat belas orang menulis tentang benda yang sama, dan tidak ada dua tulisan yang mirip.",
            "en": "Fourteen people wrote about the same object, and no two pieces were alike.",
        },
        "body": [
            block(
                "Kata minggu ini: kunci rumah. Sepuluh menit, tanpa berhenti, tanpa menghapus. "
                "Yang menarik bukan bendanya, tapi ke mana benda itu membawa masing-masing orang.",
                "This week's word: a house key. Ten minutes, no stopping, no deleting. What is "
                "interesting is not the object, but where it takes each person.",
            ),
        ],
    },
    {
        "slug": "kelas-menulis-lirik-sudah-dibuka",
        "category": "kabar",
        "title": {
            "id": "Kelas \"Menulis Lirik: Dasar\" sudah bisa diakses",
            "en": "The \"Lyric Writing: Foundations\" course is open",
        },
        "excerpt": {
            "id": "Empat modul, tiga belas materi, gratis dan tanpa perlu jadi anggota.",
            "en": "Four modules, thirteen items, free and open to everyone.",
        },
        "course_slug": "menulis-lirik-dasar",
        "body": [
            block(
                "Kelasnya bisa diikuti kapan saja. Kemajuan belajarmu tersimpan di akun, jadi "
                "bisa dilanjutkan dari perangkat mana pun.",
                "Take it whenever you like. Your progress is saved to your account, so you can "
                "continue from any device.",
            ),
        ],
    },
]


def main() -> int:
    db = SessionLocal()
    author = db.query(User).filter(User.role.in_(("admin", "contributor"))).first()
    now = now_local(db)

    for offset, sample in enumerate(SAMPLES):
        existing = db.query(Article).filter(Article.slug == sample["slug"]).first()
        if existing is not None:
            db.delete(existing)
            db.flush()
        db.add(
            Article(
                slug=sample["slug"],
                category=sample["category"],
                status="published",
                title_id=sample["title"]["id"],
                title_en=sample["title"]["en"],
                excerpt_id=sample["excerpt"]["id"],
                excerpt_en=sample["excerpt"]["en"],
                body=sample["body"],
                featured=sample.get("featured", False),
                course_slug=sample.get("course_slug"),
                author_id=author.id if author else None,
                published_at=now - timedelta(days=offset * 3),
            )
        )
        print(f"seeded {sample['slug']}")

    db.commit()
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
