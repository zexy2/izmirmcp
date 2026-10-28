from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from app.connectors.http import SourceError, get_json
from app.core.settings import Settings


class CkanError(SourceError):
    pass


class CkanNotFoundError(CkanError):
    """The action is reachable, but the requested ID does not exist."""


class CkanClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.ckan_base_url.rstrip("/")

    async def _action(self, action: str, params: dict[str, Any]) -> Any:
        url = f"{self.base_url}/{action}?{urlencode(params)}"
        payload = await get_json(
            url,
            timeout=self.settings.request_timeout_seconds,
            attempts=self.settings.request_attempts,
            max_bytes=self.settings.response_max_bytes,
        )
        if not isinstance(payload, dict):
            raise CkanError("invalid CKAN response")
        if payload.get("success") is not True:
            error = payload.get("error")
            message = str(error.get("message", "")) if isinstance(error, dict) else str(error or "")
            if "not found" in message.casefold():
                raise CkanNotFoundError(f"CKAN {action} target not found")
            raise CkanError(f"CKAN action failed: {action}")
        return payload.get("result")

    async def package_search(
        self, *, query: str, rows: int, formats: list[str] | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"q": query, "rows": rows}
        if formats:
            params["fq"] = " OR ".join(f"res_format:{fmt.upper()}" for fmt in formats)
        result = await self._action("package_search", params)
        return result if isinstance(result, dict) else {}

    async def package_show(self, dataset_id: str) -> dict[str, Any]:
        result = await self._action("package_show", {"id": dataset_id})
        return result if isinstance(result, dict) else {}

    async def datastore_search(
        self,
        *,
        resource_id: str,
        limit: int,
        filters: dict[str, Any] | None = None,
        offset: int = 0,
        query: str | None = None,
        sort: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "resource_id": resource_id,
            "limit": limit,
            "offset": offset,
        }
        if filters:
            params["filters"] = json.dumps(filters, ensure_ascii=False)
        if query:
            params["q"] = query
        if sort:
            params["sort"] = sort
        result = await self._action("datastore_search", params)
        return result if isinstance(result, dict) else {}
