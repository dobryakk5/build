import uvicorn

from app.core.config import settings
from app.core.logging import configure_logging


def main() -> None:
    configure_logging()
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_RELOAD,
        access_log=True,
        log_config=None,
    )


if __name__ == "__main__":
    main()
