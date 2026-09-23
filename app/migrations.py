"""Run database migrations at startup.

The container has no separate migration step, so the app brings the schema up
to date itself when it boots. Two cases have to be handled:

* **A database that predates Alembic** (production, before Phase 0) — the
  tables exist but there is no `alembic_version` row. Running the baseline
  migration would try to re-create existing tables and fail, so such a database
  is *stamped* with the baseline first and then upgraded.
* **A brand-new database** — no tables at all; every migration simply runs.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import get_settings
from app.db import engine

log = logging.getLogger("uvicorn.error")

BASELINE = "0001_baseline"
API_DIR = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def run_migrations() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    cfg = _alembic_config()

    if "users" in tables and "alembic_version" not in tables:
        # Pre-Alembic database: record where it already is, then move forward.
        log.info("existing schema without alembic_version — stamping %s", BASELINE)
        command.stamp(cfg, BASELINE)

    command.upgrade(cfg, "head")
    log.info("database schema is up to date")
