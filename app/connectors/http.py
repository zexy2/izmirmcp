from __future__ import annotations

import asyncio
import io
import ipaddress
import json
import os
import socket
import time
import zipfile
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

USER_AGENT = "izmir-mcp/0.1 (+https://github.com/; read-only city data client)"

ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


class SourceError(RuntimeError):
    """An upstream source failed or returned an unusable payload."""


class SourceTimeoutError(SourceError):
    """The upstream request exceeded the configured timeout."""


class SourceRateLimitedError(SourceError):
    """The upstream rejected the request with HTTP 429.

    ``retry_after_seconds`` echoes the source's own ``Retry-After`` header when
    present; the caller can then back off for the period the publisher asked for
    instead of hammering on a fixed schedule.
    """

    def __init__(self, message: str, *, retry_after_seconds: float = 0.0):
        super().__init__(message)
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))


MAX_REDIRECTS = 3
MAX_RETRY_AFTER_SECONDS = 300


def _retry_after_seconds(response: httpx.Response) -> float:
    """Parse ``Retry-After`` as seconds; ignore dates and absurd values.

    Only the delta-seconds form is honoured. A malformed or hostile value must
    not park the caller forever, so it is clamped.
    """
    raw = (response.headers.get("retry-after") or "").strip()
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    if value < 0 or value != value:  # negative or NaN
        return 0.0
    return min(value, MAX_RETRY_AFTER_SECONDS)


# --- Upstream destination policy -------------------------------------------
#
# Every upstream is a public government endpoint. A hostname that resolves to
# loopback, RFC1918, link-local (169.254.169.254 metadata), CGNAT, multicast or
# any reserved range is refused. The check runs on the address the socket will
# actually use: ``_GuardedTransport`` resolves once, validates every answer and
# connects to the vetted IP, so DNS rebinding between check and connect is not
# possible. ``IZMIR_MCP_ALLOW_PRIVATE_UPSTREAMS=1`` exists only for local test
# servers and is never on by default.

ALLOW_PRIVATE_ENV = "IZMIR_MCP_ALLOW_PRIVATE_UPSTREAMS"
DEFAULT_CONNECT_TIMEOUT = 5.0
HOST_COOLDOWN_SECONDS = 60.0
MAX_COOLDOWN_HOSTS = 256
_NAT64_PREFIX = ipaddress.IPv6Network("64:ff9b::/96")


def _private_upstreams_allowed() -> bool:
    return os.environ.get(ALLOW_PRIVATE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None:
            ip = mapped
        elif ip.teredo is not None:
            ip = ip.teredo[1]
        elif ip in _NAT64_PREFIX:
            # A NAT64 gateway would translate 64:ff9b::7f00:1 to 127.0.0.1.
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast


def _check_literal_host(host: str) -> None:
    """Refuse a URL whose host is a non-public IP literal or a local name."""
    if _private_upstreams_allowed():
        return
    bare = host.strip("[]").rstrip(".").lower()
    if not bare:
        raise SourceError("source URL has no host")
    if bare == "localhost" or bare.endswith((".localhost", ".local", ".internal")):
        raise SourceError("source URL points to a local host")
    try:
        ipaddress.ip_address(bare.split("%", 1)[0])
    except ValueError:
        return
    if not _is_public_ip(bare):
        raise SourceError("source URL points to a non-public address")


async def _resolve_public(host: str, port: int) -> str:
    """Resolve ``host`` and return one vetted public address.

    All answers must be public: a resolver returning a mix of public and private
    records is treated as hostile rather than filtered.
    """
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise httpx.ConnectError(f"could not resolve {host}") from exc
    addresses = [str(info[4][0]) for info in infos]
    if not addresses:
        raise httpx.ConnectError(f"could not resolve {host}")
    if not all(_is_public_ip(address) for address in addresses):
        raise SourceError("source host resolves to a non-public address")
    return addresses[0]


class _GuardedTransport(httpx.AsyncBaseTransport):
    """Connect only to vetted public IPs, keeping Host and TLS SNI intact."""

    def __init__(self, **kwargs: Any):
        self._inner = httpx.AsyncHTTPTransport(**kwargs)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        _check_literal_host(host)
        if _private_upstreams_allowed():
            return await self._inner.handle_async_request(request)
        try:
            ipaddress.ip_address(host)
            is_literal = True
        except ValueError:
            is_literal = False
        if not is_literal:
            port = request.url.port or (443 if request.url.scheme == "https" else 80)
            address = await _resolve_public(host, port)
            request.url = request.url.copy_with(host=address)
            request.extensions = {**request.extensions, "sni_hostname": host}
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


# Per-host "recently unreachable" memory. A dead host otherwise costs every
# caller the full connect timeout × attempts; after a connect failure the host
# is skipped for ``HOST_COOLDOWN_SECONDS``. Bounded LRU so hostile hostnames
# cannot grow it without limit.
_host_cooldowns: OrderedDict[str, float] = OrderedDict()


def _cooldown_active(host: str) -> bool:
    until = _host_cooldowns.get(host)
    if until is None:
        return False
    if until <= time.monotonic():
        _host_cooldowns.pop(host, None)
        return False
    return True


def _mark_unreachable(host: str) -> None:
    _host_cooldowns[host] = time.monotonic() + HOST_COOLDOWN_SECONDS
    _host_cooldowns.move_to_end(host)
    while len(_host_cooldowns) > MAX_COOLDOWN_HOSTS:
        _host_cooldowns.popitem(last=False)


def clear_host_cooldowns() -> None:
    _host_cooldowns.clear()


async def _get_same_origin(client: httpx.AsyncClient, url: str) -> tuple[httpx.Response, str]:
    """GET ``url`` following at most ``MAX_REDIRECTS`` same-origin redirects.

    A cross-host or scheme-changing redirect is refused with ``SourceError`` so
    a hijacked source cannot redirect us into the local network. The returned
    response is *streamed*: the caller owns it and must ``aclose()`` it.
    """
    original = urlsplit(url)
    origin = (original.scheme, original.netloc.lower())
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _check_literal_host(httpx.URL(current).host)
        request = client.build_request("GET", current)
        response = await client.send(request, stream=True)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response, origin[1]
        location = response.headers.get("location")
        if not location:
            return response, origin[1]
        await response.aclose()
        target = httpx.URL(current).join(location)
        target_origin = (target.scheme, target.netloc.lower())
        if target_origin != origin:
            raise SourceError("source redirected to a different origin")
        current = str(target)
    raise SourceError("source redirected too many times")


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
    total_deadline: float | None = None,
) -> bytes:
    host = (urlsplit(url).hostname or "").lower()
    if _cooldown_active(host):
        raise SourceError("source host is temporarily unreachable")
    deadline = total_deadline if total_deadline is not None else timeout * 2
    try:
        async with asyncio.timeout(deadline):
            return await _get_bytes_inner(url, timeout=timeout, attempts=attempts, max_bytes=max_bytes, accept=accept)
    except TimeoutError as exc:
        raise SourceTimeoutError("source request exceeded its total deadline") from exc


async def _get_bytes_inner(
    url: str,
    *,
    timeout: float,
    attempts: int,
    max_bytes: int,
    accept: str,
) -> bytes:
    last_error: Exception | None = None
    host = (urlsplit(url).hostname or "").lower()
    # Redirects are followed only when the target stays on the same host and
    # scheme. Blindly following a 302 from a compromised source is a textbook
    # SSRF: the next hop could be 169.254.169.254 or an internal address.
    # ``trust_env=False``: a stray HTTP(S)_PROXY must not reroute upstream calls
    # around the destination policy.
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=min(DEFAULT_CONNECT_TIMEOUT, timeout)),
        follow_redirects=False,
        trust_env=False,
        transport=_GuardedTransport(),
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    ) as client:
        for attempt in range(max(1, attempts)):
            try:
                response, original_host = await _get_same_origin(client, url)
                try:
                    if response.status_code == 429:
                        raise SourceRateLimitedError(
                            "source rate limit exceeded",
                            retry_after_seconds=_retry_after_seconds(response),
                        )
                    response.raise_for_status()
                    return await _read_bounded(response, max_bytes)
                finally:
                    await response.aclose()
            except (httpx.HTTPError, SourceError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    break
                if isinstance(exc, SourceRateLimitedError):
                    break
                if isinstance(exc, SourceError) and not isinstance(exc, SourceTimeoutError):
                    # Policy and budget violations are deterministic; retrying
                    # only repeats the download.
                    break
                if isinstance(exc, httpx.ConnectError):
                    _mark_unreachable(host)
                    break
                if attempt + 1 < max(1, attempts):
                    await asyncio.sleep(0.35 * (attempt + 1))
    if isinstance(last_error, httpx.TimeoutException):
        raise SourceTimeoutError("source request timed out") from last_error
    if isinstance(last_error, (SourceRateLimitedError, SourceError)):
        # Re-raise the original so typed attributes (retry_after_seconds) survive;
        # rebuilding it from the message dropped them.
        raise last_error
    raise SourceError(f"source request failed: {type(last_error).__name__}") from last_error


def _decode(body: bytes, *, strict: bool) -> str:
    if not strict:
        return body.decode("utf-8-sig", errors="replace")
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceError("source returned text that is not valid UTF-8") from exc


async def get_text(
    url: str,
    *,
    timeout: float,
    attempts: int,
    max_bytes: int,
    accept: str = "text/csv,text/plain,*/*",
    strict: bool = False,
) -> str:
    body = await _get_bytes(url, timeout=timeout, attempts=attempts, max_bytes=max_bytes, accept=accept)
    return _decode(body, strict=strict)


async def get_json_with_size(
    url: str,
    *,
    timeout: float,
    attempts: int,
    max_bytes: int,
    strict: bool = False,
) -> tuple[Any, int]:
    """Fetch JSON and report the exact wire bytes consumed by the budget."""
    body = await _get_bytes(
        url,
        timeout=timeout,
        attempts=attempts,
        max_bytes=max_bytes,
        accept="application/json",
    )
    try:
        return json.loads(_decode(body, strict=strict)), len(body)
    except json.JSONDecodeError as exc:
        raise SourceError("source returned invalid JSON") from exc


async def get_json(
    url: str,
    *,
    timeout: float,
    attempts: int,
    max_bytes: int,
    strict: bool = False,
) -> Any:
    payload, _size = await get_json_with_size(
        url, timeout=timeout, attempts=attempts, max_bytes=max_bytes, strict=strict
    )
    return payload


# A 18 MB archive with 200k empty entries cost ~113 MB and ~5 s just to build
# ``namelist()``, all within the byte budget. The EShot feed needs 7 files, so a
# modest ceiling removes the amplification without touching real data.
MAX_ZIP_ENTRIES = 200
EOCD_SIGNATURE = b"PK\x05\x06"
EOCD_SIZE = 22


def _declared_entry_count(body: bytes) -> int | None:
    """Read the entry count from the End of Central Directory record.

    ``zipfile.infolist()`` parses every entry, which is exactly the work a
    hostile archive wants us to do: 200k empty entries cost ~130 MB and ~5 s
    before the ceiling was even checked. The EOCD trailer states the count in
    fixed offsets, so it can be rejected before the archive is opened.
    """
    floor = max(0, len(body) - (EOCD_SIZE + 65_535))
    end = len(body)
    # A forged EOCD planted in the archive comment can be self-consistent too,
    # so every candidate whose comment length reaches the end of the body is
    # considered and the largest count wins: a fake can only raise the count.
    counts: list[int] = []
    while True:
        index = body.rfind(EOCD_SIGNATURE, floor, end)
        if index < 0:
            break
        end = index + 3
        if index + EOCD_SIZE > len(body):
            continue
        comment_length = int.from_bytes(body[index + 20 : index + 22], "little")
        if index + EOCD_SIZE + comment_length == len(body):
            counts.append(
                max(
                    int.from_bytes(body[index + 8 : index + 10], "little"),
                    int.from_bytes(body[index + 10 : index + 12], "little"),
                )
            )
    return max(counts) if counts else None


def read_zip_members(
    body: bytes,
    *,
    max_member_bytes: Mapping[str, int],
    required: tuple[str, ...] = (),
    max_entries: int = MAX_ZIP_ENTRIES,
) -> dict[str, bytes]:
    """Extract only named members from an in-memory ZIP under per-member budgets.

    The archive is never written to disk and no member outside ``max_member_bytes``
    (or ``required``) is decompressed. A non-ZIP body, a missing required member, a
    member exceeding its budget or an archive with implausibly many entries is
    rejected instead of truncated.
    """
    if not body.startswith(ZIP_SIGNATURES):
        raise SourceError("source did not return a ZIP archive")
    declared = _declared_entry_count(body)
    if declared is not None and declared > max_entries:
        raise SourceError(f"ZIP archive declares {declared} entries; limit is {max_entries}")
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:
        raise SourceError("source returned a corrupt ZIP archive") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > max_entries:
            raise SourceError(f"ZIP archive declares {len(infos)} entries; limit is {max_entries}")
        names = {info.filename for info in infos}
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


async def get_zip(
    url: str,
    *,
    timeout: float,
    attempts: int,
    max_bytes: int,
) -> bytes:
    """Download a ZIP archive under a byte budget and verify its signature."""
    body = await _get_bytes(
        url,
        timeout=timeout,
        attempts=attempts,
        max_bytes=max_bytes,
        # www.eshot.gov.tr answers 406 to explicit zip Accept headers but serves
        # the archive to a wildcard Accept (verified 2026-10-28).
        accept="*/*",
    )
    if not body.startswith(ZIP_SIGNATURES):
        raise SourceError("source did not return a ZIP archive")
    return body


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
