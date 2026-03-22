"""Loguru logger configured for stdout (Railway-friendly)."""

import sys

from loguru import logger as _logger

from core.config import get_settings

settings = get_settings()

_logger.remove()

if settings.environment == "production":
    _logger.add(
        sys.stdout,
        format="{time:YYYY-MM-DDTHH:mm:ss.SSS}Z | {level} | {name}:{line} | {message}",
        level=settings.log_level,
        serialize=True,
    )
else:
    _logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
        level=settings.log_level,
        colorize=True,
    )

logger = _logger
