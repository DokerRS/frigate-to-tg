"""HTTP-клиент Frigate API: конфиг (группы камер), снапшоты и клипы событий."""

from __future__ import annotations

import logging

import httpx

from .config import FrigateConfig

log = logging.getLogger(__name__)


class FrigateError(Exception):
    """Ошибка обращения к Frigate API."""


class FrigateClient:
    def __init__(self, cfg: FrigateConfig):
        headers = {}
        auth = None
        if cfg.token:
            headers["Authorization"] = f"Bearer {cfg.token}"
        elif cfg.username:
            auth = httpx.BasicAuth(cfg.username, cfg.password or "")
        self._cfg = cfg
        self._client = httpx.AsyncClient(
            base_url=cfg.url,
            headers=headers,
            auth=auth,
            timeout=cfg.timeout,
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_camera_groups(self) -> dict[str, list[str]]:
        """Возвращает camera_groups из конфига Frigate: {имя группы: [камеры]}."""
        try:
            resp = await self._client.get("/api/config")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise FrigateError(f"Не удалось получить конфиг Frigate: {exc}") from exc
        groups = resp.json().get("camera_groups") or {}
        return {str(name): [str(c) for c in (g.get("cameras") or [])] for name, g in groups.items()}

    async def get_snapshot(self, event_id: str) -> bytes:
        url = f"/api/events/{event_id}/snapshot.jpg"
        try:
            resp = await self._client.get(url, params={"quality": self._cfg.snapshot_quality})
            if resp.status_code == 404:
                raise FrigateError(f"Снапшот события {event_id} не найден (404)")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise FrigateError(f"Ошибка скачивания снапшота {event_id}: {exc}") from exc
        return resp.content

    async def get_thumbnail(self, event_id: str) -> bytes:
        """Запасной вариант: маленькая thumbnail события (webp)."""
        try:
            resp = await self._client.get(f"/api/events/{event_id}/thumbnail.jpg")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise FrigateError(f"Ошибка скачивания thumbnail {event_id}: {exc}") from exc
        return resp.content

    async def download_clip(self, event_id: str, max_bytes: int) -> bytes | None:
        """Скачивает clip.mp4 события; None, если запись недоступна или больше лимита."""
        try:
            async with self._client.stream("GET", f"/api/events/{event_id}/clip.mp4") as resp:
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                header_len = resp.headers.get("content-length")
                if header_len and int(header_len) > max_bytes:
                    log.warning("Клип %s больше лимита %d байт (%s)", event_id, max_bytes, header_len)
                    return None
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        log.warning("Клип %s превысил лимит %d байт, отменено", event_id, max_bytes)
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise FrigateError(f"Ошибка скачивания клипа {event_id}: {exc}") from exc
