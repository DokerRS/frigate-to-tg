"""MQTT-подписка на события Frigate."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import paho.mqtt.client as mqtt

from .config import MqttConfig

log = logging.getLogger(__name__)

EventHandler = Callable[[dict], Awaitable[None]]


class MqttListener:
    def __init__(self, cfg: MqttConfig, handler: EventHandler, loop: asyncio.AbstractEventLoop):
        self._cfg = cfg
        self._handler = handler
        self._loop = loop
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=cfg.client_id,
            protocol=mqtt.MQTTv311,
        )
        if cfg.username:
            self._client.username_pw_set(cfg.username, cfg.password)
        if cfg.tls:
            self._client.tls_set()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        if getattr(reason_code, "is_failure", False):
            log.error("MQTT подключение отклонено: %s", reason_code)
            return
        client.subscribe(self._cfg.topic, qos=1)
        log.info("Подписан на MQTT-топик '%s'", self._cfg.topic)

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties=None) -> None:
        log.warning("MQTT соединение разорвано: %s (переподключение автоматически)", reason_code)

    def _on_message(self, _client, _userdata, message: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            log.warning("Игнорирую не-JSON сообщение в %s: %s", message.topic, exc)
            return
        if not isinstance(payload, dict):
            return
        asyncio.run_coroutine_threadsafe(self._handler(payload), self._loop)

    def start(self) -> None:
        log.info("Подключаюсь к MQTT %s:%s", self._cfg.host, self._cfg.port)
        # connect_async + loop_start: paho сам повторяет и подключение, и переподключение
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._client.connect_async(self._cfg.host, self._cfg.port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
