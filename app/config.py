"""Загрузка и валидация конфигурации из YAML с подстановкой переменных окружения."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(Exception):
    """Ошибка конфигурации."""


def _substitute_env(value: Any) -> Any:
    """Рекурсивно раскрывает ${VAR} и ${VAR:-default} в строках конфигурации."""
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(v) for v in value]
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1)) or (m.group(2) or ""), value)
    return value


def _as_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Поле '{name}' должно быть числом, получено: {value!r}") from exc


def _as_float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Поле '{name}' должно быть числом, получено: {value!r}") from exc


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str | None = None
    http_debug: bool = False


@dataclass
class FrigateConfig:
    url: str = "http://frigate:5000"
    public_url: str | None = None  # внешний адрес для ссылок в Telegram (по умолчанию = url)
    username: str | None = None
    password: str | None = None
    token: str | None = None
    snapshot_quality: int = 80
    timeout: float = 30.0


@dataclass
class MqttConfig:
    host: str = "mqtt"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    prefix: str = "frigate"
    client_id: str = "frigate-to-tg"
    tls: bool = False

    @property
    def events_topic(self) -> str:
        return f"{self.prefix.strip('/')}/events"


@dataclass
class TelegramConfig:
    bot_token: str = ""
    proxy_url: str | None = None
    api_base: str = "https://api.telegram.org"
    timeout: float = 60.0
    poll_timeout: float = 30.0


@dataclass
class AlertsConfig:
    actions: tuple[str, ...] = ("update",)
    one_alert_per_event: bool = True
    require_snapshot: bool = True
    min_score: float = 0.0
    use_thumbnail_fallback: bool = True
    caption_format: str = "{camera}: {label} — {score}%"
    caption_card: bool = True
    timezone: str | None = None
    send_video_button: bool = True
    video_max_mb: float = 45.0
    event_ttl_minutes: int = 120


@dataclass
class GroupsConfig:
    from_frigate: bool = True
    extra: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Route:
    chat_id: int
    thread_id: int | None = None
    title: str = ""
    groups: tuple[str, ...] = ()
    cameras: tuple[str, ...] = ()
    objects: tuple[str, ...] = ()
    min_score: float = 0.0
    send_video: bool | None = None

    def describe(self) -> str:
        parts = [f"chat={self.chat_id}"]
        if self.thread_id:
            parts.append(f"topic={self.thread_id}")
        if self.title:
            parts.append(f"'{self.title}'")
        if self.groups:
            parts.append("groups=" + ",".join(self.groups))
        if self.cameras:
            parts.append("cameras=" + ",".join(self.cameras))
        if self.objects:
            parts.append("objects=" + ",".join(self.objects))
        if self.min_score:
            parts.append(f"min_score={self.min_score:g}")
        return " ".join(parts)


@dataclass
class AppConfig:
    frigate: FrigateConfig
    mqtt: MqttConfig
    telegram: TelegramConfig
    alerts: AlertsConfig
    groups: GroupsConfig
    routes: list[Route]
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @property
    def known_chats(self) -> set[int]:
        return {r.chat_id for r in self.routes}


def _parse_logging(raw: dict, legacy_level: Any = None) -> LoggingConfig:
    level = raw.get("level", legacy_level) or "INFO"
    return LoggingConfig(
        level=str(level).upper(),
        file=str(raw["file"]) if raw.get("file") else None,
        http_debug=bool(raw.get("http_debug", False)),
    )


def _parse_frigate(raw: dict) -> FrigateConfig:
    auth = raw.get("auth") or {}
    return FrigateConfig(
        url=str(raw.get("url", "http://frigate:5000")).rstrip("/"),
        public_url=(str(raw["public_url"]).strip().rstrip("/") or None) if raw.get("public_url") else None,
        username=auth.get("user") or raw.get("username") or None,
        password=auth.get("password") or raw.get("password") or None,
        token=auth.get("token") or raw.get("token") or None,
        snapshot_quality=_as_int(raw.get("snapshot_quality", 80), "frigate.snapshot_quality"),
        timeout=_as_float(raw.get("timeout", 30), "frigate.timeout"),
    )


def _parse_mqtt(raw: dict) -> MqttConfig:
    return MqttConfig(
        host=str(raw.get("host", "mqtt")),
        port=_as_int(raw.get("port", 1883), "mqtt.port"),
        username=raw.get("username") or None,
        password=raw.get("password") or None,
        prefix=str(raw.get("prefix", raw.get("topic", "frigate")).removesuffix("/events").strip("/") or "frigate"),
        client_id=str(raw.get("client_id", "frigate-to-tg")),
        tls=bool(raw.get("tls", False)),
    )


def _parse_telegram(raw: dict) -> TelegramConfig:
    token = str(raw.get("bot_token", "")).strip()
    if not token:
        raise ConfigError("Не задан telegram.bot_token в config.yaml")
    return TelegramConfig(
        bot_token=token,
        proxy_url=(str(raw.get("proxy_url")).strip() or None) if raw.get("proxy_url") else None,
        api_base=str(raw.get("api_base", "https://api.telegram.org")).rstrip("/"),
        timeout=_as_float(raw.get("timeout", 60), "telegram.timeout"),
        poll_timeout=_as_float(raw.get("poll_timeout", 30), "telegram.poll_timeout"),
    )


def _parse_alerts(raw: dict) -> AlertsConfig:
    actions = raw.get("actions", ["update"])
    if isinstance(actions, str):
        actions = [actions]
    actions = tuple(str(a).strip().lower() for a in actions)
    unknown = set(actions) - {"new", "update", "end", "unknown"}
    if unknown:
        raise ConfigError(f"alerts.actions: неизвестные действия {sorted(unknown)}")
    return AlertsConfig(
        actions=actions,
        one_alert_per_event=bool(raw.get("one_alert_per_event", True)),
        require_snapshot=bool(raw.get("require_snapshot", True)),
        min_score=_as_float(raw.get("min_score", 0.0), "alerts.min_score"),
        use_thumbnail_fallback=bool(raw.get("use_thumbnail_fallback", True)),
        caption_format=str(raw.get("caption_format", AlertsConfig.caption_format)),
        caption_card=bool(raw.get("caption_card", True)),
        timezone=(str(raw.get("timezone")).strip() or None) if raw.get("timezone") else None,
        send_video_button=bool(raw.get("send_video_button", True)),
        video_max_mb=_as_float(raw.get("video_max_mb", 45.0), "alerts.video_max_mb"),
        event_ttl_minutes=_as_int(raw.get("event_ttl_minutes", 120), "alerts.event_ttl_minutes"),
    )


def _parse_groups(raw: dict) -> GroupsConfig:
    extra_raw = raw.get("extra") or {}
    if not isinstance(extra_raw, dict):
        raise ConfigError("groups.extra должен быть словарём 'имя группы: [камеры]'")
    extra = {}
    for name, cameras in extra_raw.items():
        if isinstance(cameras, str):
            cameras = [cameras]
        if not isinstance(cameras, list) or not cameras:
            raise ConfigError(f"groups.extra.{name}: ожидается непустой список камер")
        extra[str(name)] = [str(c) for c in cameras]
    return GroupsConfig(from_frigate=bool(raw.get("from_frigate", True)), extra=extra)


def _parse_routes(raw: list) -> list[Route]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError("Нужен непустой список routes")
    routes: list[Route] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ConfigError(f"routes[{idx}] должен быть словарём")
        if "chat_id" not in item:
            raise ConfigError(f"routes[{idx}]: не задан chat_id")
        thread_id = item.get("thread_id", item.get("topic_id"))
        send_video = item.get("send_video")
        route = Route(
            chat_id=_as_int(item["chat_id"], f"routes[{idx}].chat_id"),
            thread_id=_as_int(thread_id, f"routes[{idx}].thread_id") if thread_id not in (None, "", 0, "0") else None,
            title=str(item.get("title", "")),
            groups=tuple(str(g) for g in ([item["groups"]] if isinstance(item.get("groups"), str) else item.get("groups") or [])),
            cameras=tuple(str(c) for c in ([item["cameras"]] if isinstance(item.get("cameras"), str) else item.get("cameras") or [])),
            objects=tuple(str(o).lower() for o in ([item["objects"]] if isinstance(item.get("objects"), str) else item.get("objects") or [])),
            min_score=_as_float(item.get("min_score", 0.0), f"routes[{idx}].min_score"),
            send_video=None if send_video is None else bool(send_video),
        )
        if not route.groups and not route.cameras:
            route.title = route.title or "все камеры"
        routes.append(route)
    return routes


def load_config(path: str | os.PathLike[str]) -> AppConfig:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"Файл конфигурации не найден: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        where = ""
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        if mark is not None:
            where = f" (строка {mark.line + 1}, колонка {mark.column + 1})"
        problem = getattr(exc, "problem", None) or getattr(exc, "context", None) or str(exc)
        raise ConfigError(f"Ошибка YAML в {p}{where}: {problem}. "
                          "Элементы списка должны начинаться с '-' в одном столбце.") from exc
    if not isinstance(raw, dict):
        raise ConfigError("Корень конфигурации должен быть словарём")
    raw = _substitute_env(raw)
    return AppConfig(
        frigate=_parse_frigate(raw.get("frigate") or {}),
        mqtt=_parse_mqtt(raw.get("mqtt") or {}),
        telegram=_parse_telegram(raw.get("telegram") or {}),
        alerts=_parse_alerts(raw.get("alerts") or {}),
        groups=_parse_groups(raw.get("groups") or {}),
        logging=_parse_logging(raw.get("logging") or {}, raw.get("log_level")),
        routes=_parse_routes(raw.get("routes") or []),
    )
