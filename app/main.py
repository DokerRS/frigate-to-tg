"""Точка входа frigate-to-tg."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from .bot import AlertBot
from .config import AppConfig, ConfigError, LoggingConfig, load_config
from .frigate_client import FrigateClient
from .logging_setup import setup_logging
from .router import Router
from .telegram import TelegramBot

DEFAULT_CONFIG = os.environ.get("CONFIG_PATH", "config/config.yaml")


async def main() -> int:
    log = logging.getLogger("frigate-to-tg")
    try:
        cfg: AppConfig = load_config(DEFAULT_CONFIG)
    except ConfigError as exc:
        setup_logging(LoggingConfig())
        log.error("Ошибка конфигурации: %s", exc)
        return 2
    setup_logging(cfg.logging)
    log.info("Конфигурация загружена: %s (log_level=%s)", DEFAULT_CONFIG, cfg.logging.level)

    frigate = FrigateClient(cfg.frigate)
    tg = TelegramBot(cfg.telegram)
    router = Router(cfg)
    bot = AlertBot(cfg, frigate, tg, router)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bot.request_stop)
        except NotImplementedError:  # Windows
            pass

    try:
        await bot.run()
    finally:
        await frigate.close()
        await tg.close()
    log.info("Остановлен.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
