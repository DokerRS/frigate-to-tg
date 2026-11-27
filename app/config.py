"""Загрузка конфигурации из переменных окружения и .env файла."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Ошибка конфигурации."""


_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_ROUTE_KEY_RE = re.compile(r"^ROUTE_(\d+)_(\w+)$")
_GROUP_PREFIX = "GROUP_"
_TRUE = {"1", "true", "yes", "on", "да"}
_FALSE = {"0", "false", "no", "off", "нет"}


def _read_env_file(path: str | os.PathLike[str]) -> dict[str, str]:
    """Разбирает .env: KEY=VALUE, строки с # — комментарии, кавычки необязательны."""
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Не удалось прочитать {p}: {exc}") from exc
    values: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_LINE_RE.match(line)
        if not m:
            raise ConfigError(f"{p}, строка {lineno}: ожидалось KEY=VALUE, получено: {raw.strip()!r}")
        key, val = m.group(1), m.group(2)
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif not val.startswith(("\"", "'")):
            # inline-комментарий: "KEY=value # комментарий" (как в стандартном dotenv)
            val = re.split(r"\s+#", val, maxsplit=1)[0].strip()
        values[key] = val
    return values


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
    poll_interval: float = 3.0   # как часто опрашивать /api/events
    lookback: int = 60           # за сколько секунд назад смотреть события при каждом опросе


@dataclass
class TelegramConfig:
    bot_token: str = ""
    proxy_url: str | None = None
    api_base: str = "https://api.telegram.org"
    timeout: float = 60.0
    poll_timeout: float = 30.0


@dataclass
class AlertsConfig:
    one_alert_per_event: bool = True
    require_snapshot: bool = True
    min_score: float = 0.0
    use_thumbnail_fallback: bool = True
    caption_format: str = "{camera}: {label} — {score}%"
    caption_card: bool = True
    timezone: str | None = None
    photo_as_document: bool = False  # исходное качество: файл без сжатия Telegram
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
    telegram: TelegramConfig
    alerts: AlertsConfig
    groups: GroupsConfig
    routes: list[Route]
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @property
    def known_chats(self) -> set[int]:
        return {r.chat_id for r in self.routes}


class _Env:
    """Доступ к переменным с приведением типов; ошибки — с именем переменной."""

    def __init__(self, values: dict[str, str]):
        self._v = values

    def keys(self):
        return self._v.keys()

    def get(self, name: str, default: str = "") -> str:
        return (self._v.get(name) or default).strip()

    def opt(self, name: str) -> str | None:
        return self.get(name) or None

    def int(self, name: str, default: int) -> int:
        return self._num(name, default, int)

    def float(self, name: str, default: float) -> float:
        return self._num(name, default, float)

    def _num(self, name: str, default, cast):
        raw = self.get(name)
        if not raw:
            return default
        try:
            return cast(raw)
        except ValueError as exc:
            raise ConfigError(f"{name} должно быть числом, получено: {raw!r}") from exc

    def bool(self, name: str, default: bool) -> bool:
        raw = self.get(name).lower()
        if not raw:
            return default
        if raw in _TRUE:
            return True
        if raw in _FALSE:
            return False
        raise ConfigError(f"{name}: ожидалось true/false, получено: {raw!r}")

    def lst(self, name: str) -> tuple[str, ...]:
        raw = self.get(name)
        if not raw:
            return ()
        return tuple(part.strip() for part in raw.split(",") if part.strip())


def _parse_logging(env: _Env) -> LoggingConfig:
    return LoggingConfig(
        level=env.get("LOG_LEVEL", "INFO").upper(),
        file=env.opt("LOG_FILE"),
        http_debug=env.bool("LOG_HTTP_DEBUG", False),
    )


def _parse_frigate(env: _Env) -> FrigateConfig:
    return FrigateConfig(
        url=env.get("FRIGATE_URL", "http://frigate:5000").rstrip("/"),
        public_url=(env.opt("FRIGATE_PUBLIC_URL") or "").rstrip("/") or None,
        username=env.opt("FRIGATE_USER"),
        password=env.opt("FRIGATE_PASSWORD"),
        token=env.opt("FRIGATE_TOKEN"),
        snapshot_quality=env.int("FRIGATE_SNAPSHOT_QUALITY", 80),
        timeout=env.float("FRIGATE_TIMEOUT", 30.0),
        poll_interval=env.float("FRIGATE_POLL_INTERVAL", 3.0),
        lookback=env.int("FRIGATE_LOOKBACK", 60),
    )


def _parse_telegram(env: _Env) -> TelegramConfig:
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ConfigError("Не задан TELEGRAM_BOT_TOKEN (в .env или переменных окружения)")
    return TelegramConfig(
        bot_token=token,
        proxy_url=env.opt("TELEGRAM_PROXY_URL"),
        api_base=env.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
        timeout=env.float("TELEGRAM_TIMEOUT", 60.0),
        poll_timeout=env.float("TELEGRAM_POLL_TIMEOUT", 30.0),
    )


def _parse_alerts(env: _Env) -> AlertsConfig:
    return AlertsConfig(
        one_alert_per_event=env.bool("ONE_ALERT_PER_EVENT", True),
        require_snapshot=env.bool("REQUIRE_SNAPSHOT", True),
        min_score=env.float("ALERT_MIN_SCORE", 0.0),
        use_thumbnail_fallback=env.bool("USE_THUMBNAIL_FALLBACK", True),
        caption_format=env.get("CAPTION_FORMAT", AlertsConfig.caption_format),
        caption_card=env.bool("CAPTION_CARD", True),
        timezone=env.opt("TIMEZONE"),
        photo_as_document=env.bool("PHOTO_AS_DOCUMENT", False),
        send_video_button=env.bool("SEND_VIDEO_BUTTON", True),
        video_max_mb=env.float("VIDEO_MAX_MB", 45.0),
        event_ttl_minutes=env.int("EVENT_TTL_MINUTES", 120),
    )


def _parse_groups(env: _Env) -> GroupsConfig:
    extra: dict[str, list[str]] = {}
    for key in sorted(env.keys()):
        if key.startswith(_GROUP_PREFIX) and key != "GROUPS_FROM_FRIGATE":
            cameras = env.lst(key)
            if cameras:
                extra[key[len(_GROUP_PREFIX):].lower()] = list(cameras)
    return GroupsConfig(from_frigate=env.bool("GROUPS_FROM_FRIGATE", True), extra=extra)


def _parse_routes(env: _Env) -> list[Route]:
    indexes = sorted({int(m.group(1)) for key in env.keys() if (m := _ROUTE_KEY_RE.match(key))})
    if not indexes:
        raise ConfigError("Не задан ни один маршрут: добавьте ROUTE_1_CHAT_ID=... (см. .env.example)")
    routes: list[Route] = []
    for i in indexes:
        p = f"ROUTE_{i}_"
        chat_raw = env.get(p + "CHAT_ID")
        if not chat_raw:
            raise ConfigError(f"{p}CHAT_ID не задан")
        try:
            chat_id = int(chat_raw)
        except ValueError as exc:
            raise ConfigError(f"{p}CHAT_ID должно быть числом, получено: {chat_raw!r}") from exc
        send_video_raw = env.get(p + "SEND_VIDEO")
        route = Route(
            chat_id=chat_id,
            thread_id=env.int(p + "THREAD_ID", 0) or None,
            title=env.get(p + "TITLE"),
            groups=env.lst(p + "GROUPS"),
            cameras=env.lst(p + "CAMERAS"),
            objects=tuple(o.lower() for o in env.lst(p + "OBJECTS")),
            min_score=env.float(p + "MIN_SCORE", 0.0),
            send_video=env.bool(p + "SEND_VIDEO", True) if send_video_raw else None,
        )
        if not route.groups and not route.cameras:
            route.title = route.title or "все камеры"
        routes.append(route)
    return routes


def load_config(env_file: str | os.PathLike[str] | None = None) -> AppConfig:
    """Читает .env (если существует) и переменные окружения; реальные переменные приоритетнее файла."""
    path = env_file or os.environ.get("ENV_PATH", ".env")
    values: dict[str, str] = {**_read_env_file(path), **os.environ}
    env = _Env(values)
    return AppConfig(
        frigate=_parse_frigate(env),
        telegram=_parse_telegram(env),
        alerts=_parse_alerts(env),
        groups=_parse_groups(env),
        logging=_parse_logging(env),
        routes=_parse_routes(env),
    )
