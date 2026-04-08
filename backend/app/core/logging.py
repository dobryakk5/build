import logging
import sys

from app.core.config import settings


def configure_logging() -> None:
    if getattr(configure_logging, "_configured", False):
        return

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    formatter = logging.Formatter(settings.LOG_FORMAT)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery", "celery.app.trace"):
        named_logger = logging.getLogger(logger_name)
        named_logger.handlers.clear()
        named_logger.setLevel(level)
        named_logger.propagate = True

    configure_logging._configured = True
