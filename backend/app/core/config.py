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

    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14

    cors_origins: str = "http://localhost:5173"

    # Absolute path to the built frontend. Set in a single-origin deployment, where this
    # process serves the SPA as well as the API; empty when Vite serves the frontend.
    frontend_dist_dir: str = ""

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
    # The mock review board makes one call per persona, each writing a scored review, so it
    # gets a larger token allowance and a longer timeout than ranking does.
    grants_review_max_tokens: int = 2048
    grants_review_timeout_seconds: float = 60.0

    # PDF extraction. Documents are parsed locally; only the extracted text reaches the LLM.
    pdf_fetch_timeout_seconds: float = 30.0
    pdf_extraction_timeout_seconds: float = 60.0
    pdf_extraction_max_tokens: int = 2048
    pdf_extraction_context_chars: int = 40000
    pdf_extraction_max_pages: int = 40

    # Protocol drafting. A full protocol is longer than a query translation, so it gets its own
    # token ceiling and a timeout that tolerates the larger completion.
    # 4096 truncated a routine multi-stage assay (a western blot with lysis and readout) mid-JSON,
    # so the ceiling is a limit on runaway output rather than on an ordinary protocol.
    protocol_draft_max_tokens: int = 8192
    protocol_draft_timeout_seconds: float = 90.0
    protocol_review_max_tokens: int = 2048

    # Regulatory drafting. Narratives are longer than an extraction reply, hence the larger
    # token ceiling; the audit of what comes back is local and costs nothing.
    regulatory_max_tokens: int = 3072
    regulatory_timeout_seconds: float = 90.0
    # Replaces the preclinical narrative drafter with a fixture that writes deliberately wrong
    # numbers, so the audit's flagged view can be exercised through the running app. Refused
    # outside development below: it produces text that is not a draft of anything.
    regulatory_fixture_drafter: bool = False

    # Screening. Descriptors are computed locally by RDKit; only the SMILES string and the
    # descriptors computed from it are sent to Claude for substituent suggestions.
    sar_suggestion_max_tokens: int = 2048
    sar_suggestion_timeout_seconds: float = 45.0

    # USPTO Open Data Portal patent search. Registration is free but a key is mandatory: with
    # no key the patents service reports the source as unavailable instead of searching. USPTO
    # publishes no per-key rate, so the limit below is a politeness measure.
    uspto_odp_base_url: str = "https://api.uspto.gov/api/v1"
    uspto_odp_api_key: str = ""
    uspto_odp_timeout_seconds: float = 20.0
    uspto_odp_rate_limit: float = 2.0

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

    # Stored document bytes are encrypted by the app before they reach the database, so a
    # dump, a provider backup or a replica is ciphertext. Base64, 32 bytes decoded; empty
    # derives the key from JWT_SECRET (see app.core.crypto), which keeps a clone runnable at
    # the cost of making stored papers unreadable if that secret is rotated — allowed in
    # development only, and refused at boot elsewhere by the validator below.
    document_encryption_key: str = ""
    # KMS key id, ARN or alias for envelope encryption. Set it and each document gets its own
    # data key minted by KMS, stored only in wrapped form, with the master key never entering
    # this process and every read recorded in CloudTrail. Empty means the local key above.
    document_kms_key_id: str = ""
    # Region for the KMS client. Empty defers to the ambient AWS configuration (AWS_REGION,
    # the instance profile, ~/.aws/config), which is what an ECS task normally has.
    aws_region: str = ""
    # How long a stored paper is kept. Enforced on every read and write rather than by a cron:
    # an expired row is never served, and is deleted the moment it is next encountered.
    document_retention_days: int = 90
    # How long security audit events are kept before the writer prunes them, and the ceiling on
    # rows one account can accumulate. Both are what the Audit Trails tab reports; neither is a
    # 21 CFR Part 11 retention scheme, which would need an append-only store the app cannot
    # delete from at all.
    audit_retention_days: int = 365
    audit_max_events_per_user: int = 2000

    # Abuse and cost controls. Turned off only in tests that assert on unthrottled behaviour.
    rate_limit_enabled: bool = True
    # Number of trusted reverse proxies in front of the app. 0 means the peer address is the
    # client and X-Forwarded-For is ignored; behind Railway's single edge proxy set 1, so the
    # per-IP limits key on the visitor instead of collapsing into one shared bucket. Only count
    # proxies you control: each hop you claim is one entry of attacker-supplied XFF trusted.
    trusted_proxy_hops: int = 0
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
    def _reject_fixture_drafter_outside_development(self) -> "Settings":
        """The fixture drafter fabricates numbers; a deployed process must not serve them."""
        if self.regulatory_fixture_drafter and self.environment != "development":
            raise ValueError(
                "REGULATORY_FIXTURE_DRAFTER is a development-only test fixture that returns "
                "deliberately incorrect numbers; it cannot be enabled when "
                f"environment={self.environment!r}"
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

    @model_validator(mode="after")
    def _require_a_document_key_of_its_own_outside_development(self) -> "Settings":
        """A deployed environment must own the key its stored papers are readable under.

        With neither set the key is derived from `JWT_SECRET`, which means rotating that secret
        — the thing you rotate first after a suspected token leak — destroys every stored
        paper, and one secret's blast radius covers both sessions and documents. Failing at boot
        is the only way that surfaces before it costs data.
        """
        if self.environment == "development":
            return self
        if not (self.document_encryption_key.strip() or self.document_kms_key_id.strip()):
            raise ValueError(
                "set DOCUMENT_KMS_KEY_ID (KMS envelope encryption) or DOCUMENT_ENCRYPTION_KEY "
                "(a base64 32-byte key) outside development; deriving the document key from "
                f"JWT_SECRET ties stored papers to it (environment={self.environment!r})"
            )
        return self

    @model_validator(mode="after")
    def _reject_unusable_retention_windows(self) -> "Settings":
        """A zero or negative window would delete on write, which is a silently broken store."""
        for name in ("document_retention_days", "audit_retention_days"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name.upper()} must be at least 1 day")
        return self

    @model_validator(mode="after")
    def _reject_negative_proxy_hops(self) -> "Settings":
        if self.trusted_proxy_hops < 0:
            raise ValueError("TRUSTED_PROXY_HOPS cannot be negative")
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
    def document_encryption_scheme(self) -> str:
        """Which key the next stored document will be sealed under, for logs and /api/health."""
        if self.document_kms_key_id.strip():
            return "kms"
        return "local-key" if self.document_encryption_key.strip() else "derived-from-jwt-secret"

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
