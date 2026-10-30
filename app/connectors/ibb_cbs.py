"""İzmir Büyükşehir open API: CBS point layers, events, hal prices, all pharmacies.

The CBS layer names were compiled from the endpoint inventory of
izmir-open-data-py (Apache License 2.0). No code was copied; only the public
layer names are reused. See NOTICE at the repository root for attribution.

Live behaviour observed on 2026-10-30:

* ``ibb/cbs/{layer}`` answers ``{"kayit_sayisi", "sayfadaki_kayitsayisi",
  "sayfa_numarasi", "toplam_sayfa_sayisi", "onemliyer": [...]}``. The page
  metadata says 10 per page but the first response carried every row; extra
  pages are only fetched when rows are actually missing, and are capped.
* ``ibb/halfiyatlari/{kind}/{YYYY-MM-DD}`` answers 204 No Content for a day
  without a bulletin.
* ``ibb/eczaneler`` names latitude ``LokasyonX`` and longitude ``LokasyonY``.
"""
from __future__ import annotations

import json
from typing import Any

from app.connectors.http import SourceError, get_json, get_text
from app.connectors.schema import expect_type
from app.core.envelope import bounded_id, bounded_text, finite_number
from app.core.geo import valid_lat_lon
from app.core.settings import Settings
from app.core.source_cache import CacheInfo, cached_source_data

CBS_LAYERS: tuple[str, ...] = (
    "acilyardimistasyonu", "adayarimada", "afetaciltoplanmaalani",
    "agizvedissagligimerkezleri", "ailedayanismamerkezleri", "ailesagligimerkezleri",
    "anacocuksagligimerkezleri", "anaokullari", "antikkentler", "antikkentyapilari",
    "aracmuayeneistasyonlari", "bankalar", "belediyeler", "bolgemudurlukleri", "burunlar",
    "cocukvegenclikmerkezleri", "cocukyuvalari", "dagtepe", "dalmerkezleri",
    "defterdarliklar", "dernekler", "engelliokullari", "etutmerkezleri",
    "evlendirmedaireleri", "fuar", "galerivesalonlar", "goller", "halkegitim", "hamamlar",
    "hastaneler", "havaalani", "hipodrom", "huzurevleri", "ilkokullar",
    "ilveilcemudurlukleri", "itfaiyegruplari", "izbbhizmetnoktalari", "kanmerkezleri",
    "kaplicalar", "kolejler", "konsolosluklar", "korfezvekoylar", "koskvekonaklar",
    "kuleanitveheykeller", "kulturmerkezleri", "kutuphaneler", "laboratuvarlar", "liseler",
    "maskematiknoktalari", "meslekliseleri", "meslekodalari", "meydanlar", "milliegitim",
    "muhtarliklar", "muzeler", "nehirvecaylar", "noterler", "nufusmudurlukleri",
    "operavebale", "ormanlar", "ortaokullar", "otobusterminalleri", "pazaryerleri",
    "plajlar", "poliklinikler", "ptt", "sanatokullari", "senfoniorkestrasi", "sinemalar",
    "sporsalonlari", "stadyumlar", "taksiduraklari", "tarihicarsivehanlar",
    "tarihisuyapilari", "tarihiyapilar", "tipmerkezleri", "tiyatrolar", "toplummerkezleri",
    "toplumsagligimerkezleri", "trengarlari", "turizmdanisma", "universiteler",
    "veremsavasdispanserleri", "vergidaireleri", "veterinerlikler", "wizmirnetnoktalari",
    "yetistirmeyurtlari",
)
MARKET_KINDS = ("sebzemeyve", "balik")


def _number(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
        try:
            value = float(value)
        except ValueError:
            return None
    return finite_number(value)


def _point(lat_value: Any, lon_value: Any) -> tuple[float, float] | None:
    lat, lon = _number(lat_value), _number(lon_value)
    if not valid_lat_lon(lat, lon):
        return None
    return lat, lon


def parse_cbs_rows(items: Any) -> list[dict[str, Any]]:
    rows = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        pair = _point(item.get("ENLEM"), item.get("BOYLAM"))
        if pair is None:
            continue
        rows.append(
            {
                "name": bounded_text(item.get("ADI")),
                "district": bounded_text(item.get("ILCE"), 128),
                "neighborhood": bounded_text(item.get("MAHALLE"), 128),
                "street": bounded_text(item.get("YOL"), 256),
                "door_no": bounded_text(item.get("KAPINO"), 32),
                "description": bounded_text(item.get("ACIKLAMA"), 1000),
                "lat": pair[0],
                "lon": pair[1],
            }
        )
    return rows


def parse_pharmacy_rows(payload: Any) -> list[dict[str, Any]]:
    rows = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        # The source names latitude X and longitude Y.
        pair = _point(item.get("LokasyonX"), item.get("LokasyonY"))
        if pair is None:
            continue
        rows.append(
            {
                "id": bounded_id(item.get("EczaneId")),
                "name": bounded_text(item.get("Adi")),
                "phone": bounded_text(item.get("Telefon"), 64),
                "address": bounded_text(item.get("Adres")),
                "area": bounded_text(item.get("Bolge"), 128),
                "lat": pair[0],
                "lon": pair[1],
            }
        )
    return rows


def parse_event_rows(payload: Any) -> list[dict[str, Any]]:
    rows = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        slug = item.get("EtkinlikUrl")
        rows.append(
            {
                "id": item.get("Id"),
                "name": bounded_text(item.get("Adi")),
                "type": bounded_text(item.get("Tur"), 64),
                "venue": bounded_text(item.get("EtkinlikMerkezi")),
                "starts_at": bounded_text(item.get("EtkinlikBaslamaTarihi"), 32),
                "ends_at": bounded_text(item.get("EtkinlikBitisTarihi"), 32),
                "free": item.get("UcretsizMi") if isinstance(item.get("UcretsizMi"), bool) else None,
                "summary": bounded_text(item.get("KisaAciklama"), 500),
                "ticket_url": bounded_text(item.get("BiletSatisLinki"), 500),
                "url": f"https://kultursanat.izmir.bel.tr/Etkinlikler/{slug}"
                if isinstance(slug, str) and slug else None,
            }
        )
    return rows


def parse_market_prices(payload: Any) -> tuple[str | None, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise SourceError("hal price payload is not an object")
    rows = []
    for item in payload.get("HalFiyatListesi") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "product": bounded_text(item.get("MalAdi"), 128),
                "category": bounded_text(item.get("MalTipAdi"), 64),
                "unit": bounded_text(item.get("Birim"), 16),
                "min_price": _number(item.get("AsgariUcret")),
                "max_price": _number(item.get("AzamiUcret")),
                "avg_price": _number(item.get("OrtalamaUcret")),
            }
        )
    bulletin = payload.get("BultenTarihi")
    return (str(bulletin)[:10] if bulletin else None), rows


class IbbCbsConnector:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.openapi_base_url.rstrip("/")

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    async def _json(self, path: str) -> Any:
        return await get_json(
            self._url(path),
            timeout=self.settings.request_timeout_seconds,
            attempts=self.settings.request_attempts,
            max_bytes=self.settings.response_max_bytes,
            strict=True,
        )

    async def layer(self, name: str) -> tuple[list[dict[str, Any]], CacheInfo]:
        if name not in CBS_LAYERS:
            raise ValueError(f"unknown CBS layer {name!r}")
        max_pages = int(getattr(self.settings, "cbs_max_pages", 10))

        async def loader() -> list[dict[str, Any]]:
            payload = expect_type(await self._json(f"ibb/cbs/{name}"), dict, what="cbs layer")
            items = list(payload.get("onemliyer") or [])
            total = payload.get("kayit_sayisi")
            pages = payload.get("toplam_sayfa_sayisi")
            page = 2
            # Sequential on purpose: the host shares a cooldown with every
            # openapi connector, so a burst of parallel pages could trip it.
            while (
                isinstance(total, int) and len(items) < total
                and isinstance(pages, int) and page <= min(pages, max_pages)
            ):
                more = expect_type(
                    await self._json(f"ibb/cbs/{name}?sayfa_numarasi={page}"), dict, what="cbs page"
                )
                batch = more.get("onemliyer") or []
                if not batch:
                    break
                items.extend(batch)
                page += 1
            return parse_cbs_rows(items)

        return await cached_source_data(
            f"ibb.cbs.{name}",
            ttl_seconds=int(getattr(self.settings, "cbs_cache_ttl_seconds", 86_400)),
            stale_if_error_seconds=self.settings.openapi_stale_if_error_seconds,
            loader=loader,
        )

    async def events(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        async def loader() -> list[dict[str, Any]]:
            payload = expect_type(
                await self._json("ibb/kultursanat/etkinlikler"), list, what="events"
            )
            return parse_event_rows(payload)

        return await cached_source_data(
            "ibb.events",
            ttl_seconds=int(getattr(self.settings, "events_cache_ttl_seconds", 3_600)),
            stale_if_error_seconds=self.settings.openapi_stale_if_error_seconds,
            loader=loader,
        )

    async def market_prices(
        self, kind: str, day: str, *, today: bool = False
    ) -> tuple[dict[str, Any] | None, CacheInfo]:
        """Hal bulletin for one ISO date; ``None`` when the source has none (204)."""
        if kind not in MARKET_KINDS:
            raise ValueError(f"unknown market kind {kind!r}")

        async def loader() -> dict[str, Any] | None:
            text = await get_text(
                self._url(f"ibb/halfiyatlari/{kind}/{day}"),
                timeout=self.settings.request_timeout_seconds,
                attempts=self.settings.request_attempts,
                max_bytes=self.settings.response_max_bytes,
                accept="application/json",
                strict=True,
            )
            if not text.strip():
                return None
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SourceError("hal prices returned invalid JSON") from exc
            bulletin, rows = parse_market_prices(payload)
            return {"bulletin_date": bulletin or day, "rows": rows}

        ttl = 1_800 if today else 7 * 86_400
        return await cached_source_data(
            f"ibb.hal.{kind}.{day}",
            ttl_seconds=int(getattr(self.settings, "hal_cache_ttl_seconds", ttl)) if not today else ttl,
            stale_if_error_seconds=self.settings.openapi_stale_if_error_seconds,
            loader=loader,
        )

    async def all_pharmacies(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        async def loader() -> list[dict[str, Any]]:
            payload = expect_type(await self._json("ibb/eczaneler"), list, what="pharmacies")
            return parse_pharmacy_rows(payload)

        return await cached_source_data(
            "ibb.pharmacies.all",
            ttl_seconds=int(getattr(self.settings, "pharmacies_all_cache_ttl_seconds", 86_400)),
            stale_if_error_seconds=self.settings.openapi_stale_if_error_seconds,
            loader=loader,
        )
