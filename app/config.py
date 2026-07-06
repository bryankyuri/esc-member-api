from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./esc.db"
    session_secret: str = "dev-secret-change-me"

    google_client_id: str = ""
    google_client_secret: str = ""

    member_frontend_url: str = "http://localhost:3001"
    dashboard_frontend_url: str = "http://localhost:3002"

    cookie_domain: str = ""  # empty = host-only cookie (localhost dev)
    cookie_secure: bool = False

    superadmin_emails: str = ""  # comma-separated

    timezone: str = "Asia/Jakarta"
    session_ttl_days: int = 30

    @property
    def superadmin_list(self) -> list[str]:
        return [e.strip().lower() for e in self.superadmin_emails.split(",") if e.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [self.member_frontend_url, self.dashboard_frontend_url]


@lru_cache
def get_settings() -> Settings:
    return Settings()
