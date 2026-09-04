"""One Settings object for the whole application (spec §3, §34)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The two thresholds of I3.  Constants, not tunables: they are written into every
# attestation, and a change is a config change with a ledger event -- never a code edit.
RELEASE_THRESHOLD = 0.85
REJECT_THRESHOLD = 0.35
CALIBRATION_VERSION = "v3"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # ── Service ─────────────────────────────────────────────────────────
    SERVICE_NAME: str = "aegis-api"
    LOG_LEVEL: str = "INFO"
    LOG_TO_KAFKA: bool = False
    # logifyx writes one rotating file per logger.  The path is declared rather
    # than left to the library's relative default, because the container runs as
    # a non-root user and a relative `logs/` under /app is not writable.
    LOG_DIR: str = "logs"
    DEMO_MODE: bool = True
    ENVIRONMENT: Literal["development", "test", "production"] = "development"

    # ── Datastores ──────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://aegis:aegis@localhost:5432/aegis"
    DATABASE_URL_SYNC: str = "postgresql+psycopg://aegis:aegis@localhost:5432/aegis"
    REDIS_URL: str = "redis://localhost:6379/0"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_ENABLED: bool = True

    # ── Object storage ──────────────────────────────────────────────────
    OBJECT_STORE: Literal["local", "s3"] = "local"
    LOCAL_STORE_PATH: str = "./data/evidence"
    S3_ENDPOINT: str = ""
    S3_BUCKET: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    MAX_ARTIFACT_BYTES: int = 20 * 1024 * 1024

    # ── Auth ────────────────────────────────────────────────────────────
    JWT_SECRET: str = "dev-only-insecure-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 14
    COOKIE_SECURE: bool = False
    PASSWORD_MIN_LENGTH: int = 10

    # ── Email ───────────────────────────────────────────────────────────
    EMAIL_PROVIDER: Literal["development", "smtp"] = "development"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    EMAIL_FROM: str = "aegis@localhost"
    PUBLIC_APP_URL: str = "http://localhost:3000"

    # ── Payment rail ────────────────────────────────────────────────────
    PAYMENT_RAIL: Literal["simulated", "razorpay"] = "simulated"
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    RAZORPAY_ROUTE_SELLER_ACCOUNT: str = ""
    RAZORPAY_BASE_URL: str = "https://api.razorpay.com/v1"

    # ── AI ──────────────────────────────────────────────────────────────
    AI_PROVIDER: Literal["anthropic", "groq", "fixture"] = "fixture"
    AI_API_KEY: str = ""
    AI_MODEL_VERIFIER: str = "claude-opus-5"
    AI_MODEL_ARBITER: str = "claude-opus-5"
    AI_MODEL_EXTRACTION: str = "claude-sonnet-5"
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL_VERIFIER: str = "llama-3.3-70b-versatile"
    GROQ_MODEL_ARBITER: str = "llama-3.3-70b-versatile"
    GROQ_MODEL_EXTRACTION: str = "llama-3.3-70b-versatile"
    AI_MAX_TOKENS: int = 16000
    AI_TIMEOUT_S: float = 120.0

    # ── Chain ───────────────────────────────────────────────────────────
    CHAIN_ENABLED: bool = True
    BLOCKCHAIN_RPC_URL: str = "https://sepolia.base.org"
    CHAIN_ID: int = 84532
    CONTRACT_ADDRESS: str = ""
    OPERATOR_PRIVATE_KEY: str = ""
    VERIFIER_PRIVATE_KEY: str = ""

    # ── Demo ────────────────────────────────────────────────────────────
    DEMO_BUYER_EMAIL: str = "owner@meridian.demo"
    DEMO_SELLER_EMAIL: str = "owner@tirupur.demo"
    DEMO_BUYER_PASSWORD: str = "aegis-demo-buyer-pw"
    DEMO_SELLER_PASSWORD: str = "aegis-demo-seller-pw"

    # ── CORS ────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # ── Rate limits (requests / window seconds) ─────────────────────────
    RATE_LIMIT_AUTH: str = "10/60"
    RATE_LIMIT_UPLOAD: str = "40/60"
    RATE_LIMIT_VERIFY: str = "12/60"

    @field_validator("LOG_LEVEL")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def release_threshold(self) -> float:
        return RELEASE_THRESHOLD

    @property
    def reject_threshold(self) -> float:
        return REJECT_THRESHOLD

    @property
    def ai_effective_provider(self) -> str:
        """The provider that will actually serve a call, given the keys present.

        Never silently claims a live provider it cannot reach: without a key the
        deterministic fixture adapter is used and every report says so.
        """
        if self.AI_PROVIDER == "anthropic" and self.AI_API_KEY:
            return "anthropic"
        if self.AI_PROVIDER == "groq" and (self.GROQ_API_KEY or self.AI_API_KEY):
            return "groq"
        return "fixture"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
