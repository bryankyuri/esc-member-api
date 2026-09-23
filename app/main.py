from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import SessionLocal
from app.migrations import run_migrations
from app.routers import (
    activities,
    admin,
    articles_admin,
    attendance,
    auth,
    certificates,
    courses_admin,
    learning,
    public,
)
from app.security import purge_expired_sessions
from app.services import seed_defaults


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Schema is owned by Alembic (see app/migrations.py). A database created
    # before Alembic was adopted is stamped with the baseline first, so this is
    # safe on production as well as on an empty file.
    run_migrations()
    with SessionLocal() as db:
        seed_defaults(db)
        # Expired rows are already rejected on use; this keeps the table tidy.
        purge_expired_sessions(db)
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
app.include_router(learning.router)
app.include_router(certificates.router)
app.include_router(public.router)
app.include_router(articles_admin.router)
app.include_router(courses_admin.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}
