"""Promote (or demote) a user by email from the CLI.

Usage:
    python -m scripts.promote_admin someone@gmail.com          # make admin
    python -m scripts.promote_admin someone@gmail.com member   # demote
"""

import sys

sys.path.insert(0, ".")

from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    email = sys.argv[1].strip().lower()
    role = sys.argv[2] if len(sys.argv) > 2 else "admin"
    if role not in ("admin", "member"):
        print("role must be 'admin' or 'member' (superadmin is env-only)")
        raise SystemExit(1)

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            print(f"no user with email {email} — they must sign in once first")
            raise SystemExit(1)
        user.role = role
        db.commit()
        print(f"{email} is now {role}")


if __name__ == "__main__":
    main()
