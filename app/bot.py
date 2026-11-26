"""Основная логика: события Frigate -> фото в Telegram, кнопка 'Видео' -> клип."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import OrderedDict

from .config import AppConfig, Route
from .frigate_client import FrigateClient, FrigateError
from .router import EventInfo, Router, parse_event
from .telegram import TelegramBot, TelegramError

log = logging.getLogger(__name__)

VIDEO_CB_PREFIX = "v:"
MAX_CALLBACK_LEN = 64


class AlertBot:
    def __init__(self, cfg: AppConfig, frigate: FrigateClient, tg: TelegramBot, router: Router):
        self.cfg = cfg
        self.frigate = frigate
        self.tg = tg
        self.router = router
        self._sent_events: OrderedDict[str, float] = OrderedDict()
        self._event_targets: dict[str, list[tuple[int, int | None]]] = {}
        self._video_locks: set[str] = set()
        self._update_offset: int | None = None
        self._stop = asyncio.Event()

    # ---------------- lifecycle ----------------

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        me = await self.tg.get_me()
        log.info("Подключён бот @%s (id=%s)", me.get("username"), me.get("id"))
        await self.refresh_groups()
        task = asyncio.create_task(self._poll_loop(), name="telegram-polling")
        try:
            await self._stop.wait()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def refresh_groups(self) -> None:
        if not self.cfg.groups.from_frigate:
            self.router.reload_groups()
            return
        try:
            groups = await self.frigate.get_camera_groups()
        except FrigateError as exc:
            log.warning("Не удалось загрузить группы из Frigate (%s), использую только groups.extra", exc)
        else:
            self.router.set_frigate_groups(groups)
            log.info("Группы камер из Frigate: %s", {k: v for k, v in groups.items()})

    # ---------------- MQTT events ----------------

    async def handle_mqtt_event(self, payload: dict) -> None:
        event = parse_event(payload)
        if event is None:
            return
        if event.action not in self.cfg.alerts.actions:
            log.debug("Событие %s: действие '%s' не в alerts.actions", event.event_id, event.action)
            return
        if self.cfg.alerts.require_snapshot and not event.has_snapshot:
            log.debug("Событие %s: снапшота нет, пропускаю", event.event_id)
            return
        if self.cfg.alerts.one_alert_per_event and event.event_id in self._sent_events:
            log.debug("Событие %s уже отправлено", event.event_id)
            return
        routes = self.router.match(event)
        if not routes:
            log.debug("Событие %s (%s/%s) не подходит ни под один маршрут", event.event_id, event.camera, event.label)
            return
        try:
            image = await self.frigate.get_snapshot(event.event_id)
        except FrigateError as exc:
            if not self.cfg.alerts.use_thumbnail_fallback:
                log.warning("Событие %s: %s", event.event_id, exc)
                return
            try:
                image = await self.frigate.get_thumbnail(event.event_id)
            except FrigateError as exc2:
                log.warning("Событие %s: снапшот и thumbnail недоступны: %s", event.event_id, exc2)
                return
        self._mark_sent(event.event_id)
        self._event_targets[event.event_id] = [(r.chat_id, r.thread_id) for r in routes]
        caption = event.caption(self.cfg.alerts.caption_format)
        for route in routes:
            if route.send_video is None:
                enabled = self.cfg.alerts.send_video_button
            else:
                enabled = route.send_video
            markup = self._video_markup(event) if enabled else None
            await self._send_photo(route, event, image, caption, markup)

    async def _send_photo(
        self,
        route: Route,
        event: EventInfo,
        image: bytes,
        caption: str,
        markup: dict | None,
    ) -> None:
        safe_caption = html.escape(caption)
        try:
            await self.tg.send_photo(route.chat_id, image, safe_caption, route.thread_id, markup)
            log.info("Отправлено событие %s (%s %s) -> %s", event.event_id, event.camera, event.label, route.describe())
        except TelegramError as exc:
            log.error("Не удалось отправить фото в %s: %s", route.describe(), exc)

    def _video_markup(self, event: EventInfo) -> dict | None:
        if not self.cfg.alerts.send_video_button or not event.has_clip:
            return None
        data = f"{VIDEO_CB_PREFIX}{event.event_id}"
        if len(data.encode()) > MAX_CALLBACK_LEN:
            return None
        return {"inline_keyboard": [[{"text": "🎬 Видео", "callback_data": data}]]}

    def _mark_sent(self, event_id: str) -> None:
        now = time.time()
        self._sent_events[event_id] = now
        ttl = self.cfg.alerts.event_ttl_minutes * 60
        while self._sent_events and now - next(iter(self._sent_events.values())) > ttl:
            old_id, _ = self._sent_events.popitem(last=False)
            self._event_targets.pop(old_id, None)

    # ---------------- Telegram updates ----------------

    async def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                updates = await self.tg.get_updates(self._update_offset)
            except TelegramError as exc:
                log.warning("getUpdates: %s (повтор через 5с)", exc)
                await asyncio.sleep(5)
                continue
            for update in updates:
                self._update_offset = max(self._update_offset or 0, int(update["update_id"]) + 1)
                try:
                    await self._handle_update(update)
                except Exception:  # noqa: BLE001 - polling loop must survive
                    log.exception("Ошибка обработки апдейта %s", update.get("update_id"))

    async def _handle_update(self, update: dict) -> None:
        if "callback_query" in update:
            await self._handle_callback(update["callback_query"])
        elif "message" in update:
            await self._handle_message(update["message"])

    async def _handle_message(self, msg: dict) -> None:
        text = (msg.get("text") or "").strip()
        chat_id = int(msg["chat"]["id"])
        thread_id = msg.get("message_thread_id")
        if not text.startswith("/"):
            return
        cmd = text.split("@", 1)[0].lower()
        if cmd in ("/start", "/help"):
            await self._send_help(chat_id, thread_id)
        elif cmd == "/chatid":
            await self.tg.send_message(
                chat_id,
                f"chat_id = <code>{chat_id}</code>"
                + (f"\nthread_id = <code>{thread_id}</code>" if thread_id else ""),
                thread_id,
            )
        elif cmd == "/groups":
            await self._send_groups(chat_id, thread_id)
        elif cmd == "/refresh":
            await self.refresh_groups()
            await self.tg.send_message(chat_id, "Группы камер обновлены из Frigate.", thread_id)

    async def _send_help(self, chat_id: int, thread_id: int | None) -> None:
        lines = [
            "<b>frigate-to-tg</b>",
            "",
            "Команды:",
            "/chatid — id этого чата",
            "/groups — группы камер и маршруты",
            "/refresh — перечитать группы из Frigate",
            "/help — эта справка",
        ]
        await self.tg.send_message(chat_id, "\n".join(lines), thread_id)

    async def _send_groups(self, chat_id: int, thread_id: int | None) -> None:
        groups = self.router.groups
        lines = ["<b>Группы камер:</b>"]
        if groups:
            for name in sorted(groups):
                lines.append(f"• <b>{html.escape(name)}</b>: {html.escape(', '.join(sorted(groups[name])))}")
        else:
            lines.append("— группы не найдены")
        lines.append("")
        lines.append("<b>Маршруты:</b>")
        for route in self.cfg.routes:
            lines.append("• " + html.escape(route.describe()))
        await self.tg.send_message(chat_id, "\n".join(lines), thread_id)

    async def _handle_callback(self, query: dict) -> None:
        data = query.get("data") or ""
        query_id = query["id"]
        message = query.get("message") or {}
        chat_id = int(message.get("chat", {}).get("id", 0))
        thread_id = message.get("message_thread_id")
        if not data.startswith(VIDEO_CB_PREFIX):
            await self.tg.answer_callback(query_id)
            return
        event_id = data[len(VIDEO_CB_PREFIX):]
        if chat_id not in {c for c, _ in self._event_targets.get(event_id, [])}:
            await self.tg.answer_callback(query_id, "Это событие не относится к данному чату.", show_alert=True)
            return
        if event_id in self._video_locks:
            await self.tg.answer_callback(query_id, "Видео уже отправляется…")
            return
        self._video_locks.add(event_id)
        await self.tg.answer_callback(query_id, "Загружаю видео…")
        try:
            await self._send_video(chat_id, thread_id, event_id)
        finally:
            self._video_locks.discard(event_id)

    async def _send_video(self, chat_id: int, thread_id: int | None, event_id: str) -> None:
        max_bytes = int(self.cfg.alerts.video_max_mb * 1024 * 1024)
        try:
            clip = await self.frigate.download_clip(event_id, max_bytes)
        except FrigateError as exc:
            log.error("Видео %s: %s", event_id, exc)
            await self._notify(chat_id, thread_id, f"Не удалось получить видео: {html.escape(str(exc))}")
            return
        if not clip:
            log.info("Видео %s недоступно (нет записи или больше лимита)", event_id)
            await self._notify(chat_id, thread_id, "Видео недоступно: запись не найдена или файл больше лимита.")
            return
        try:
            await self.tg.send_video(chat_id, clip, f"Видео события <code>{html.escape(event_id)}</code>", thread_id)
            log.info("Отправлено видео %s в chat %s", event_id, chat_id)
        except TelegramError as exc:
            log.warning("sendVideo %s не удался (%s), пробую как документ", event_id, exc)
            try:
                await self.tg.send_document(chat_id, clip, f"Видео события <code>{html.escape(event_id)}</code>", thread_id)
            except TelegramError as exc2:
                log.error("sendDocument %s не удался: %s", event_id, exc2)
                await self._notify(chat_id, thread_id, f"Не удалось отправить видео: {html.escape(str(exc2))}")

    async def _notify(self, chat_id: int, thread_id: int | None, text: str) -> None:
        try:
            await self.tg.send_message(chat_id, text, thread_id)
        except TelegramError as exc:
            log.error("Не удалось отправить уведомление в chat %s: %s", chat_id, exc)
