from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "askgrey.ai"
    environment: str = "development"
    database_url: str = "sqlite:///./askgrey.db"

    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14

    cors_origins: str = "http://localhost:5173"

    # SSO / OIDC. Populated per corporate tenant; left empty in development.
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_url: str = "http://localhost:5173/auth/callback"

    # NCBI Entrez. An API key raises the rate limit from 3 to 10 requests/second.
    ncbi_api_key: str = ""
    ncbi_tool_name: str = "askgrey"
    ncbi_contact_email: str = ""
    ncbi_timeout_seconds: float = 20.0

    # LLM used for natural-language -> Entrez query translation. Without a key the
    # service falls back to a deterministic rule-based translator.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0

    @property
    def entrez_rate_limit(self) -> float:
        return 10.0 if self.ncbi_api_key else 3.0

    @property
    def llm_translation_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def sso_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
