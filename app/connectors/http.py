from __future__ import annotations

import asyncio
import io
import json
import zipfile
from collections.abc import Mapping
from typing import Any

import httpx

USER_AGENT = "izmir-mcp/0.1 (+https://github.com/; read-only city data client)"

ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


class SourceError(RuntimeError):
    """An upstream source failed or returned an unusable payload."""


class SourceTimeoutError(SourceError):
    """The upstream request exceeded the configured timeout."""


class SourceRateLimitedError(SourceError):
    """The upstream rejected the request with HTTP 429."""


async def _read_bounded(response: httpx.Response, max_bytes: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared is not None and (not declared.isdecimal() or int(declared) > max_bytes):
        raise SourceError("response exceeds the configured byte budget")
    body = bytearray()
    async for chunk in response.aiter_bytes(65_536):
        if len(body) + len(chunk) > max_bytes:
            raise SourceError("response exceeds the configured byte budget")
        body.extend(chunk)
    return bytes(body)


async def _get_bytes(
    url: str,
    *,
    timeout: float,
    attempts: int,
    max_bytes: int,
    accept: str,
) -> bytes:
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    ) as client:
        for attempt in range(max(1, attempts)):
            try:
                response = await client.get(url)
                if response.status_code == 429:
                    raise SourceRateLimitedError("source rate limit exceeded")
                response.raise_for_status()
                return await _read_bounded(response, max_bytes)
            except (httpx.HTTPError, SourceError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    break
                if isinstance(exc, SourceRateLimitedError):
                    break
                if attempt + 1 < max(1, attempts):
                    await asyncio.sleep(0.35 * (attempt + 1))
    if isinstance(last_error, httpx.TimeoutException):
        raise SourceTimeoutError("source request timed out") from last_error
    if isinstance(last_error, (SourceRateLimitedError, SourceError)):
        raise type(last_error)(str(last_error)) from last_error
    raise SourceError(f"source request failed: {type(last_error).__name__}") from last_error


async def get_text(
    url: str,
    *,
    timeout: float,
    attempts: int,
    max_bytes: int,
    accept: str = "text/csv,text/plain,*/*",
) -> str:
    body = await _get_bytes(
        url, timeout=timeout, attempts=attempts, max_bytes=max_bytes, accept=accept
    )
    return body.decode("utf-8-sig", errors="replace")


async def get_json(
    url: str,
    *,
    timeout: float,
    attempts: int,
    max_bytes: int,
) -> Any:
    text = await get_text(
        url,
        timeout=timeout,
        attempts=attempts,
        max_bytes=max_bytes,
        accept="application/json",
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError("source returned invalid JSON") from exc


def read_zip_members(
    body: bytes,
    *,
    max_member_bytes: Mapping[str, int],
    required: tuple[str, ...] = (),
) -> dict[str, bytes]:
    """Extract only named members from an in-memory ZIP under per-member budgets.

    The archive is never written to disk and no member outside ``max_member_bytes``
    (or ``required``) is decompressed. A non-ZIP body, a missing required member or
    a member exceeding its budget is rejected instead of truncated.
    """
    if not body.startswith(ZIP_SIGNATURES):
        raise SourceError("source did not return a ZIP archive")
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:
        raise SourceError("source returned a corrupt ZIP archive") from exc
    with archive:
        names = set(archive.namelist())
        missing = [name for name in required if name not in names]
        if missing:
            raise SourceError(f"ZIP archive is missing {', '.join(missing)}")
        extracted: dict[str, bytes] = {}
        for name, budget in max_member_bytes.items():
            if name not in names:
                continue
            info = archive.getinfo(name)
            if info.file_size > budget:
                raise SourceError(f"ZIP member {name} exceeds its byte budget")
            with archive.open(info) as handle:
                data = handle.read(budget + 1)
            if len(data) > budget:
                raise SourceError(f"ZIP member {name} exceeds its byte budget")
            extracted[name] = data
        return extracted


async def get_zip_members(
    url: str,
    *,
    timeout: float,
    attempts: int,
    max_bytes: int,
    max_member_bytes: Mapping[str, int],
    required: tuple[str, ...] = (),
) -> dict[str, bytes]:
    body = await _get_bytes(
        url,
        timeout=timeout,
        attempts=attempts,
        max_bytes=max_bytes,
        # www.eshot.gov.tr answers 406 to explicit zip Accept headers but serves
        # the archive to a wildcard Accept (verified 2026-10-28).
        accept="*/*",
    )
    return read_zip_members(body, max_member_bytes=max_member_bytes, required=required)
