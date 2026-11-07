"""Standard structured logging configuration."""

import logging
import sys


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    log_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    )

    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # Suppress overly verbose third-party logs if needed
    logging.getLogger("uvicorn.access").setLevel(numeric_level)
