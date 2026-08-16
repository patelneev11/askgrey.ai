from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Long enough to satisfy RFC 7518's HMAC key guidance so local runs are not noisy; it is still
# a published literal, which is why deployed environments refuse to boot on it.
DEV_JWT_SECRET = "dev-secret-change-me-before-deploying"
# Every value a deployment could inherit from the repo rather than choose. Anyone holding one
# of these can mint an access token for any user id, so a deployed process must not start
# with one.
PLACEHOLDER_JWT_SECRETS = frozenset(
    {DEV_JWT_SECRET, "change-me-in-every-deployed-environment", "changeme", "secret"}
)
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "askgrey.ai"
    environment: str = "development"
    # SQLite by default so a clone runs with no services to install. A deployment must point
    # this at a managed database instead: the host filesystem is replaced on every deploy,
    # and the stored paper bytes live in this database, so a file-backed URL loses every saved
    # workspace on the next release.
    database_url: str = "sqlite:///./askgrey.db"
    # Connections are recycled well inside the idle timeout a managed Postgres or its pooler
    # imposes, so a checked-out connection is never one the far end has already dropped.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800

    # Path to the built frontend (`frontend/dist`). Set it to serve the app and the API from
    # one origin, which removes CORS and third-party-cookie handling from the deployment
    # entirely; left empty, this process serves only the API.
    frontend_dist_dir: str = ""

    jwt_secret: str = DEV_JWT_SECRET
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

    # PubChem PUG-REST. Unauthenticated and capped at 5 requests/second per IP.
    pubchem_base_url: str = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    pubchem_timeout_seconds: float = 20.0
    pubchem_rate_limit: float = 5.0
    pubchem_max_candidates: int = 10

    # ClinicalTrials.gov v2. Unauthenticated; the rate limit is a politeness measure.
    clinicaltrials_base_url: str = "https://clinicaltrials.gov/api/v2"
    clinicaltrials_timeout_seconds: float = 20.0
    clinicaltrials_rate_limit: float = 5.0
    clinicaltrials_page_size: int = 25

    # Federal funding. grants.gov search2/fetchOpportunity and the SBIR.gov solicitations
    # API are both public and need no key or registration.
    grants_gov_base_url: str = "https://api.grants.gov/v1/api"
    grants_gov_timeout_seconds: float = 20.0
    grants_gov_rate_limit: float = 5.0
    # search2 omits the synopsis, so each hit needs a fetchOpportunity call to become
    # matchable; this caps how many of them one page pays for.
    grants_enrich_limit: int = 25
    sbir_base_url: str = "https://api.www.sbir.gov/public/api"
    sbir_timeout_seconds: float = 20.0
    sbir_rate_limit: float = 2.0
    grants_match_max_tokens: int = 2048
    grants_match_timeout_seconds: float = 45.0

    # PDF extraction. Documents are parsed locally; only the extracted text reaches the LLM.
    pdf_fetch_timeout_seconds: float = 30.0
    pdf_extraction_timeout_seconds: float = 60.0
    pdf_extraction_max_tokens: int = 2048
    pdf_extraction_context_chars: int = 40000
    pdf_extraction_max_pages: int = 40

    # Claude, used for natural-language -> Entrez query translation. Without a key the
    # service falls back to a deterministic rule-based translator.
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_version: str = "2023-06-01"
    llm_model: str = "claude-sonnet-4-5"
    llm_max_tokens: int = 1024
    llm_timeout_seconds: float = 30.0

    # Observability. The DSN is empty in development, which turns error reporting into a
    # no-op rather than requiring a Sentry project to run the app.
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.0
    release: str = "dev"
    log_level: str = "INFO"
    log_json: bool = True
    # Warn once a day when metered Claude spend crosses this; 0 disables the alert.
    llm_daily_cost_alert_usd: float = 25.0

    # Abuse and cost controls. Turned off only in tests that assert on unthrottled behaviour.
    rate_limit_enabled: bool = True
    auth_rate_limit_per_minute: int = 10
    auth_account_rate_limit_per_hour: int = 30
    api_rate_limit_per_minute: int = 120
    llm_rate_limit_per_minute: int = 12
    # Same ceiling by source address: an account is cheap to create, an LLM pass is not.
    llm_ip_rate_limit_per_minute: int = 20
    llm_daily_call_budget: int = 250

    @model_validator(mode="after")
    def _reject_ephemeral_database_outside_development(self) -> "Settings":
        """A file-backed SQLite database is data loss on a deployed platform, not a warning.

        Containers get a fresh filesystem on each deploy and no sharing between replicas, so
        the saved workspaces and the stored paper bytes would silently vanish on release and
        differ per replica before that. `sqlite://` (in-memory) stays allowed because tests
        construct settings with an explicit environment.
        """
        if self.environment == "development":
            return self
        url = self.database_url.strip()
        if url.startswith("sqlite") and url not in ("sqlite://", "sqlite:///:memory:"):
            raise ValueError(
                "DATABASE_URL points at a SQLite file, whose contents are lost on every "
                "deploy and are not shared between replicas; set a managed database URL "
                f"(environment={self.environment!r})"
            )
        return self

    @model_validator(mode="after")
    def _reject_wildcard_cors_with_credentials(self) -> "Settings":
        """Sessions ride on a cookie, so a wildcard origin would let any site drive the API.

        Browsers reject `Access-Control-Allow-Origin: *` alongside credentials anyway; failing
        at boot is better than discovering it as a mystery CORS error in production.
        """
        if self.environment != "development" and "*" in self.cors_origin_list:
            raise ValueError(
                "CORS_ORIGINS must list explicit origins outside development; '*' cannot be "
                f"combined with credentialed requests (environment={self.environment!r})"
            )
        return self

    @model_validator(mode="after")
    def _reject_placeholder_jwt_secret(self) -> "Settings":
        if self.environment == "development":
            return self
        if self.jwt_secret in PLACEHOLDER_JWT_SECRETS:
            raise ValueError(
                "JWT_SECRET is still the placeholder value; set a unique random secret "
                f"outside the development environment (environment={self.environment!r})"
            )
        if len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters "
                f"outside the development environment (environment={self.environment!r})"
            )
        return self

    @property
    def sqlalchemy_url(self) -> str:
        """The URL with a driver SQLAlchemy 2 can actually load.

        Managed providers hand out `postgres://` (Heroku-era) or bare `postgresql://`, which
        SQLAlchemy resolves to psycopg2 — a driver this project does not install. Rewriting
        the scheme here means a deployment can paste the provider's URL unchanged.
        """
        url = self.database_url.strip()
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @property
    def serves_frontend(self) -> bool:
        return bool(self.frontend_dist_dir.strip())

    @property
    def entrez_rate_limit(self) -> float:
        return 10.0 if self.ncbi_api_key else 3.0

    @property
    def llm_translation_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def sso_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
