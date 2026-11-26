"""Точка входа frigate-to-tg."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from .bot import AlertBot
from .config import ConfigError, load_config
from .frigate_client import FrigateClient
from .mqtt_client import MqttListener
from .router import Router
from .telegram import TelegramBot

DEFAULT_CONFIG = os.environ.get("CONFIG_PATH", "config/config.yaml")


def setup_logging(level: str) -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        root.removeHandler(handler)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def main() -> int:
    log = logging.getLogger("frigate-to-tg")
    try:
        cfg = load_config(DEFAULT_CONFIG)
    except ConfigError as exc:
        setup_logging("INFO")
        log.error("Ошибка конфигурации: %s", exc)
        return 2
    setup_logging(cfg.log_level)

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

    mqtt_listener = MqttListener(cfg.mqtt, bot.handle_mqtt_event, loop)
    mqtt_listener.start()
    try:
        await bot.run()
    finally:
        mqtt_listener.stop()
        await frigate.close()
        await tg.close()
    log.info("Остановлен.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
