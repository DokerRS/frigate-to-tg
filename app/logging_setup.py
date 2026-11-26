"""Настройка логирования: консоль + опциональный файл, смена уровня на лету."""

from __future__ import annotations

import logging
import sys

from .config import LoggingConfig

NOISY_LOGGERS = ("httpx", "httpcore")


def setup_logging(cfg: LoggingConfig) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    level = getattr(logging, cfg.level.upper(), logging.INFO)
    root.setLevel(level)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if cfg.file:
        handlers.append(logging.FileHandler(cfg.file, encoding="utf-8"))
    for handler in handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    if not cfg.http_debug:
        for name in NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)


def set_log_level(level: str) -> bool:
    """Меняет уровень логирования на лету (команда /debug). False, если уровень неизвестен."""
    lvl = getattr(logging, level.upper(), None)
    if not isinstance(lvl, int):
        return False
    root = logging.getLogger()
    root.setLevel(lvl)
    for handler in root.handlers:
        handler.setLevel(lvl)
    if lvl < logging.WARNING:
        for name in NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
    return True
