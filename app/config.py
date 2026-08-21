"""Application configuration.

Loaded once at startup from environment variables (and a local .env file, if
present) and treated as the single source of truth for configuration
throughout the application.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Application ---
    app_port: int = Field(default=8080, alias="APP_PORT")
    app_env: str = Field(default="development", alias="APP_ENV")

    # --- Database ---
    database_url: str = Field(alias="DATABASE_URL")

    # --- Security ---
    encryption_key: str = Field(alias="ENCRYPTION_KEY")
    session_secret: str = Field(alias="SESSION_SECRET")

    # --- Google OAuth2 (Gmail API) ---
    google_credentials_path: str = Field(
        default="./credentials.json", alias="GOOGLE_CREDENTIALS_PATH"
    )
    # For hosts with no way to upload a file (e.g. Railway) — the raw
    # contents of credentials.json, written out to google_credentials_path
    # at startup if set (see app.main's lifespan). Local dev keeps using the
    # file directly and leaves this unset.
    google_credentials_json: str | None = Field(default=None, alias="GOOGLE_CREDENTIALS_JSON")
    google_redirect_url: str = Field(default="", alias="GOOGLE_REDIRECT_URL")

    # --- IMAP IDLE ---
    gmail_imap_host: str = Field(default="imap.gmail.com:993", alias="GMAIL_IMAP_HOST")
    gmail_imap_user: str = Field(default="", alias="GMAIL_IMAP_USER")
    gmail_imap_app_password: str = Field(default="", alias="GMAIL_IMAP_APP_PASSWORD")

    # --- LLM extraction (M4) ---
    anthropic_api_key: str = Field(alias="ANTHROPIC_API_KEY")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings instance.

    Cached so the .env file is parsed once per process rather than on every
    call site.
    """
    return Settings()
