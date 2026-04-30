from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_BASE_URL: str = "http://localhost:3000"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_RELOAD: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:secret@localhost:5432/construction"

    # JWT
    SECRET_KEY: str = "change-me-in-production-256-bit-secret"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    AUTH_COOKIE_DOMAIN: str | None = None
    AUTH_COOKIE_SECURE: bool = False
    AUTH_ACCESS_COOKIE_NAME: str = "access_token"
    AUTH_REFRESH_COOKIE_NAME: str = "refresh_token"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # S3 (для вложений к комментариям)
    S3_BUCKET: str = "construction-files"
    S3_ENDPOINT: str = "https://s3.amazonaws.com"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""

    # Email
    EMAIL_FROM: str = "noreply@example.com"
    EMAIL_PROVIDER: str = "log"
    RESEND_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: int = 10

    # Embeddings / OpenRouter
    OPENROUTER_API_KEY: str = ""
    openrouter_API: str = ""
    EMBEDDING_BASE_URL: str = "https://openrouter.ai/api/v1"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536
    NORMALIZATION_MODEL: str = "openai/gpt-4o-mini"
    RERANK_MODEL: str = "openai/gpt-4o"
    HYBRID_VECTOR_WEIGHT: float = 0.65
    HYBRID_FTS_WEIGHT: float = 0.35
    RERANK_ENABLED: bool = False
    RERANK_SCORE_THRESHOLD: float = 0.72
    RERANK_GAP_THRESHOLD: float = 0.05
    RERANK_CANDIDATE_COUNT: int = 20
    FER_EXAMPLE_MATCH_THRESHOLD: float = 0.93
    FER_GROUP_SECTION_SCORE_THRESHOLD: float = 0.72
    FER_GROUP_SECTION_GAP_THRESHOLD: float = 0.05
    FER_GROUP_COLLECTION_CONFIDENT_THRESHOLD: float = 0.65
    FER_GROUP_COLLECTION_AMBIGUOUS_THRESHOLD: float = 0.40

    # КТП — Карты Технологического Процесса
    KTP_GENERATION_MODEL: str = "openai/gpt-4o-mini"
    KTP_MAX_TOKENS: int = 3000

    # КТП — Карты Технологического Процесса
    KTP_GENERATION_MODEL: str = "openai/gpt-4o-mini"
    KTP_MAX_TOKENS: int = 3000

    # Token lifetimes
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_EXPIRE_HOURS: int = 2

    # Rate limiting
    RATE_LIMIT_LOGIN_ATTEMPTS: int = 5
    RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = 15 * 60
    RATE_LIMIT_REGISTER_ATTEMPTS: int = 5
    RATE_LIMIT_REGISTER_WINDOW_SECONDS: int = 60 * 60
    RATE_LIMIT_PASSWORD_ATTEMPTS: int = 3
    RATE_LIMIT_PASSWORD_WINDOW_SECONDS: int = 60 * 60

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
