"""Маршрутизация событий Frigate в чаты/топики Telegram по группам камер."""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import AppConfig, Route

log = logging.getLogger(__name__)

# Эмодзи для популярных объектов Frigate (для карточки).
LABEL_EMOJI = {
    "person": "👤",
    "face": "🙂",
    "car": "🚗",
    "truck": "🚚",
    "bus": "🚌",
    "motorcycle": "🏍️",
    "bicycle": "🚲",
    "dog": "🐕",
    "cat": "🐈",
    "bird": "🐦",
    "horse": "🐎",
    "cow": "🐄",
    "sheep": "🐑",
    "bear": "🐻",
    "fox": "🦊",
    "raccoon": "🦝",
    "deer": "🦌",
    "package": "📦",
    "amazon": "📦",
}
DEFAULT_EMOJI = "⚠️"


def label_emoji(label: str) -> str:
    return LABEL_EMOJI.get(label.lower(), DEFAULT_EMOJI)


def score_bar(score: float, blocks: int = 5) -> str:
    """Визуальная шкала уверенности: 🟩🟩🟩⬜⬜."""
    filled = round(max(0.0, min(1.0, score)) * blocks)
    return "🟩" * filled + "⬜" * (blocks - filled)




@dataclass(frozen=True)
class EventInfo:
    """Извлечённые из MQTT-сообщения данные события."""

    event_id: str
    camera: str
    label: str
    score: float
    action: str  # new | update | end
    has_snapshot: bool
    has_clip: bool
    zones: tuple[str, ...] = ()
    start_time: float | None = None
    sub_label: str | None = None

    def caption(self, fmt: str) -> str:
        return fmt.format(
            camera=self.camera,
            label=self.label,
            score=int(round(self.score * 100)),
            zones=", ".join(self.zones),
            id=self.event_id,
            sub_label=self.sub_label or "",
        )

    def card_html(self, tz_name: str | None = None) -> str:
        """Компактная HTML-подпись к фото в две строки (parse_mode=HTML)."""
        pct = int(round(self.score * 100))
        where = html.escape(self.camera)
        if self.zones:
            where += " · " + html.escape(", ".join(self.zones))
        title = f"{label_emoji(self.label)} <b>{html.escape(self.label.capitalize())}</b>"
        if self.sub_label:
            title += f" · {html.escape(self.sub_label)}"
        title += f" — <b>{html.escape(where)}</b>"
        line2 = f"<code>{pct}%</code> {score_bar(self.score)}"
        ts = self._time_str(tz_name)
        if ts:
            line2 += f" · 🕒 {ts}"
        return f"{title}\n{line2}"

    def _time_str(self, tz_name: str | None) -> str:
        if not self.start_time:
            return ""
        dt = datetime.fromtimestamp(self.start_time)
        if tz_name:
            try:
                dt = dt.astimezone(ZoneInfo(tz_name))
            except (ZoneInfoNotFoundError, ValueError):
                log.warning("Неизвестная таймзона '%s', показываю время сервера", tz_name)
        return dt.strftime("%d.%m.%Y %H:%M:%S")


def parse_event(payload: dict) -> EventInfo | None:
    """Разбирает сообщение frigate/events. Берётся часть 'after' — она актуальнее."""
    after = payload.get("after")
    if not isinstance(after, dict) or not after.get("id"):
        return None
    action = str(payload.get("type", "update")).lower()
    snapshot = after.get("snapshot") or {}
    score = after.get("top_score") or after.get("score") or snapshot.get("score") or 0.0
    sub_label = after.get("sub_label")
    if isinstance(sub_label, list) and sub_label:
        sub_label = str(sub_label[0])
    elif not isinstance(sub_label, str):
        sub_label = None
    zones = tuple(str(z) for z in (after.get("entered_zones") or after.get("current_zones") or []))
    return EventInfo(
        event_id=str(after["id"]),
        camera=str(after.get("camera", "")),
        label=str(after.get("label", "object")).lower(),
        score=float(score or 0.0),
        action=action if action in ("new", "update", "end") else "update",
        has_snapshot=bool(after.get("has_snapshot")) or bool(snapshot.get("frame_time")),
        has_clip=bool(after.get("has_clip")),
        zones=zones,
        start_time=after.get("start_time"),
        sub_label=sub_label,
    )


class Router:
    def __init__(self, cfg: AppConfig, frigate_groups: dict[str, list[str]] | None = None):
        self._cfg = cfg
        self._frigate_groups = frigate_groups or {}
        self._groups: dict[str, set[str]] = {}
        for name, cameras in self._frigate_groups.items():
            self._groups.setdefault(name.lower(), set()).update(c.lower() for c in cameras)
        for name, cameras in cfg.groups.extra.items():
            self._groups.setdefault(name.lower(), set()).update(c.lower() for c in cameras)

    def set_frigate_groups(self, groups: dict[str, list[str]]) -> None:
        self._frigate_groups = groups
        self.reload_groups()

    def reload_groups(self) -> None:
        self._groups = {}
        for name, cameras in self._frigate_groups.items():
            self._groups.setdefault(name.lower(), set()).update(c.lower() for c in cameras)
        for name, cameras in self._cfg.groups.extra.items():
            self._groups.setdefault(name.lower(), set()).update(c.lower() for c in cameras)
        log.info("Группы камер: %s", {k: sorted(v) for k, v in self._groups.items()})

    @property
    def groups(self) -> dict[str, set[str]]:
        return dict(self._groups)

    def cameras_for_group(self, name: str) -> set[str] | None:
        return self._groups.get(name.lower())

    def resolve(self, name: str) -> set[str]:
        """Камеры для имени: имя группы, имя камеры или '*'; None-маршрут => все известные камеры."""
        lowered = name.lower()
        if lowered in ("*", "all", "все"):
            return set(self._all_known_cameras())
        if lowered in self._groups:
            return set(self._groups[lowered])
        return {lowered}

    def _all_known_cameras(self) -> set[str]:
        cameras: set[str] = set()
        for group in self._groups.values():
            cameras |= group
        for route in self._cfg.routes:
            cameras |= {c.lower() for c in route.cameras}
        return cameras

    def route_cameras(self, route: Route) -> set[str] | None:
        """None означает 'любые камеры'."""
        if not route.groups and not route.cameras:
            return None
        cameras: set[str] = set()
        for group in route.groups:
            resolved = self.cameras_for_group(group)
            if resolved is None:
                log.warning("Маршрут %s ссылается на неизвестную группу '%s'", route.describe(), group)
            else:
                cameras |= resolved
        cameras |= {c.lower() for c in route.cameras}
        return cameras

    def match(self, event: EventInfo) -> list[Route]:
        """Все маршруты, которым подходит событие."""
        matched: list[Route] = []
        camera = event.camera.lower()
        for route in self._cfg.routes:
            cameras = self.route_cameras(route)
            if cameras is not None and camera not in cameras:
                continue
            if route.objects and event.label not in route.objects:
                continue
            if event.score < max(self._cfg.alerts.min_score, route.min_score):
                continue
            matched.append(route)
        return matched

    def route_for_chat(self, chat_id: int) -> Route | None:
        for route in self._cfg.routes:
            if route.chat_id == chat_id:
                return route
        return None
