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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 24 * 60
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
    KTP_GENERATION_MODEL: str = "openai/gpt-4o-mini"
    KTP_MAX_TOKENS: int = 3000
    KTP_ESTIMATE_MAX_TOKENS: int = 6000
    KTP_ESTIMATE_CHUNK_ROWS: int = 80
    KTP_STAGE1_GAP_FILL_ENABLED: bool = True
    KTP_STAGE1_PER_GROUP_GAP_FILL_ENABLED: bool = True
    KTP_STAGE1_PROJECT_GAP_FILL_ENABLED: bool = True
    KTP_STAGE1_STALE_AFTER_SECONDS: int = 2 * 60 * 60

    # Item-level NW→ФЕР matching (calibration targets — NOT quality gates yet).
    # Toggles the post-Stage-1 pass that matches each estimate item to a ФЕР row
    # so that durations are grounded in fer_rows.h_hour instead of LLM guesses.
    KTP_ITEM_FER_MATCH_ENABLED: bool = True
    # Which keyword-confidence levels of estimate_nw_matcher are auto-accepted as NW scope.
    NW_KEYWORD_AUTO_LEVELS: list[str] = ["high"]
    # Batching / concurrency for the ФЕР matching pass.
    FER_MATCH_BATCH_SIZE: int = 40
    FER_MATCH_CONCURRENCY: int = 8
    # WT vote thresholds (group-level work-type assignment from item NW votes).
    WT_VOTE_AUTO_SHARE: float = 0.6
    WT_VOTE_REVIEW_SHARE: float = 0.3

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
