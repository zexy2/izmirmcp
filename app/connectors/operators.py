"""Announcement feeds for the transport operators other than ESHOT.

All three endpoints in this module were verified live on 2026-10-28:

- Metro/tram: ``https://metrotramapi.iztek.tr/api/v1/announcements`` returns
  ``{"data": [...], "isSuccessful": true, ...}`` (empty array at verification
  time, so the connector is honest about "no rows" instead of a failure).
- İZDENİZ: ``https://coreapi.izdeniz.com.tr/api/v1/announcements`` returns
  ``{"data": {"data": [...]}}`` with real published announcements.
- İZBAN: **no reachable feed.** ``Rss.aspx?MenuId=45`` and every
  ``Single.aspx?MenuId=*`` page returned HTTP 302 to ``FileNotFound.htm``;
  ``metrotramapi`` has no İZBAN announcement route (404). İZBAN is therefore
  reported as unavailable, never as "no disruptions".
"""
from __future__ import annotations

from typing import Any

from app.connectors.http import SourceError, get_json
from app.core.settings import Settings
from app.core.source_cache import CacheInfo, cached_source_data

METRO_BASE_URL = "https://metrotramapi.iztek.tr/api/v1"
FERRY_BASE_URL = "https://coreapi.izdeniz.com.tr/api/v1"


def _text(value: Any) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def parse_metro_announcements(payload: Any) -> list[dict[str, Any]]:
    """Flatten the İZTEK envelope; an unexpected shape is a source error."""
    if not isinstance(payload, dict):
        raise SourceError("metro announcement payload was not an object")
    if payload.get("isSuccessful") is False:
        raise SourceError("metro announcement API reported failure")
    rows = payload.get("data")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise SourceError("metro announcement rows were not a list")
    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title") or item.get("name"))
        if not title:
            continue
        out.append(
            {
                "id": _text(item.get("id")),
                "title": title,
                "summary": _text(item.get("summary") or item.get("content")),
                "published_at": _text(
                    item.get("publishedAt") or item.get("publishDate") or item.get("date")
                ),
                "url": None,
            }
        )
    return out


def parse_ferry_announcements(payload: Any) -> list[dict[str, Any]]:
    """İZDENİZ nests rows under ``data.data`` and paginates."""
    if not isinstance(payload, dict):
        raise SourceError("ferry announcement payload was not an object")
    body = payload.get("data")
    if body is None:
        return []
    rows = body.get("data") if isinstance(body, dict) else body
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise SourceError("ferry announcement rows were not a list")
    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"))
        if not title:
            continue
        slug = _text(item.get("slug"))
        out.append(
            {
                "id": _text(item.get("id")),
                "title": title,
                "summary": _text(item.get("summary")),
                "published_at": _text(
                    item.get("publishDate") or item.get("createdAt") or item.get("date")
                ),
                "url": f"https://www.izdeniz.com.tr/duyurular/{slug}" if slug else None,
            }
        )
    return out


class OperatorAnnouncementConnector:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def _fetch(
        self, key: str, url: str, parser
    ) -> tuple[list[dict[str, Any]], CacheInfo]:
        async def loader() -> list[dict[str, Any]]:
            payload = await get_json(
                url,
                timeout=self.settings.request_timeout_seconds,
                attempts=self.settings.request_attempts,
                max_bytes=self.settings.response_max_bytes,
            )
            return parser(payload)

        return await cached_source_data(
            key,
            ttl_seconds=self.settings.eshot_notices_cache_ttl_seconds,
            loader=loader,
        )

    async def metro_announcements(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        return await self._fetch(
            "operator.metro.announcements",
            f"{METRO_BASE_URL}/announcements",
            parse_metro_announcements,
        )

    async def ferry_announcements(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        return await self._fetch(
            "operator.izdeniz.announcements",
            f"{FERRY_BASE_URL}/announcements?version=1&isPublished=true&page=1&pageSize=20",
            parse_ferry_announcements,
        )
