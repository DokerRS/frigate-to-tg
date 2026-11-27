"""Клиент Telegram Bot API (HTTP) с поддержкой прокси через httpx."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .config import TelegramConfig

log = logging.getLogger(__name__)


class TelegramError(Exception):
    """Ошибка Telegram Bot API."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class TelegramBot:
    def __init__(self, cfg: TelegramConfig):
        self._cfg = cfg
        kwargs: dict[str, Any] = {
            "base_url": f"{cfg.api_base}/bot{cfg.bot_token}",
            "timeout": httpx.Timeout(cfg.timeout, read=cfg.poll_timeout + 10),
        }
        if cfg.proxy_url:
            kwargs["proxy"] = cfg.proxy_url
        self._client = httpx.AsyncClient(**kwargs)

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, *, data: dict | None = None, files: dict | None = None) -> Any:
        try:
            resp = await self._client.post(f"/{method}", data=data, files=files)
        except httpx.HTTPError as exc:
            raise TelegramError(f"Сетевая ошибка Telegram ({method}): {exc}") from exc
        try:
            payload = resp.json()
        except ValueError:
            raise TelegramError(f"Telegram вернул не-JSON для {method}: HTTP {resp.status_code}") from None
        if not payload.get("ok"):
            raise TelegramError(
                f"{method}: {payload.get('description', 'unknown error')}",
                code=payload.get("error_code"),
            )
        return payload["result"]

    async def get_me(self) -> dict:
        return await self._call("getMe")

    async def get_updates(self, offset: int | None) -> list[dict]:
        data = {
            "timeout": int(self._cfg.poll_timeout),
            "allowed_updates": '["message","callback_query"]',
        }
        if offset:
            data["offset"] = offset
        return await self._call("getUpdates", data=data)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        thread_id: int | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict:
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        if thread_id:
            data["message_thread_id"] = thread_id
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        return await self._call("sendMessage", data=data)

    async def send_photo(
        self,
        chat_id: int,
        photo: bytes,
        caption: str,
        thread_id: int | None = None,
        reply_markup: dict | None = None,
    ) -> dict:
        data: dict[str, Any] = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        if thread_id:
            data["message_thread_id"] = thread_id
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        files = {"photo": ("snapshot.jpg", photo, "image/jpeg")}
        return await self._call("sendPhoto", data=data, files=files)

    async def send_video(
        self,
        chat_id: int,
        video: bytes,
        caption: str = "",
        thread_id: int | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict:
        data: dict[str, Any] = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        if thread_id:
            data["message_thread_id"] = thread_id
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        files = {"video": ("clip.mp4", video, "video/mp4")}
        return await self._call("sendVideo", data=data, files=files)

    async def send_document(
        self,
        chat_id: int,
        document: bytes,
        filename: str,
        content_type: str,
        caption: str = "",
        thread_id: int | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict | None = None,
    ) -> dict:
        data: dict[str, Any] = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        if thread_id:
            data["message_thread_id"] = thread_id
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        files = {"document": (filename, document, content_type)}
        return await self._call("sendDocument", data=data, files=files)

    async def answer_callback(self, callback_id: str, text: str | None = None, show_alert: bool = False) -> None:
        data: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            data["text"] = text
            data["show_alert"] = "true" if show_alert else "false"
        try:
            await self._call("answerCallbackQuery", data=data)
        except TelegramError as exc:
            log.debug("answerCallbackQuery: %s", exc)

    async def edit_reply_markup(self, chat_id: int, message_id: int, reply_markup: dict) -> None:
        data = {"chat_id": chat_id, "message_id": message_id, "reply_markup": json.dumps(reply_markup)}
        await self._call("editMessageReplyMarkup", data=data)
