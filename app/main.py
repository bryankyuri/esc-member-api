from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.routers import activities, admin, attendance, auth
from app.services import seed_defaults


def _lightweight_migrations() -> None:
    """Additive column migrations for SQLite (create_all won't ALTER existing
    tables). Idempotent. Adopt Alembic if this grows beyond a few columns."""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        if "security_passed" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN security_passed "
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            # Grandfather everyone already in production — they signed up
            # before the security question existed.
            conn.execute(text("UPDATE users SET security_passed = 1"))
        if "security_attempts" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN security_attempts "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "security_attempt_date" not in cols:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN security_attempt_date VARCHAR")
            )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # v1: schema via create_all; switch to Alembic before the schema grows.
    Base.metadata.create_all(engine)
    _lightweight_migrations()
    with SessionLocal() as db:
        seed_defaults(db)
    yield


settings = get_settings()

app = FastAPI(
    title="ESC Member API",
    version="0.1.0",
    lifespan=lifespan,
)

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# SessionMiddleware backs the OAuth state/PKCE dance only (not user auth —
# user sessions are DB rows + the esc_session cookie).
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(attendance.router)
app.include_router(activities.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}
