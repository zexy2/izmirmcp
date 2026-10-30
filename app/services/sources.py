from __future__ import annotations

from app.connectors.http import SourceError, SourceRateLimitedError, SourceTimeoutError
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.envelope import Source

PARKING = Source(
    name="İZELMAN / İZUM otopark doluluk servisi",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://www.izmir.bel.tr",
    scope="parking_occupancy",
)
PHARMACY = Source(
    name="İzmir nöbetçi eczane listesi",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://www.izmir.bel.tr/tr/NobetciEczane/27",
    scope="on_duty_roster",
)
METRO = Source(
    name="İzmir Metro istasyonları",
    publisher="İzmir Metro A.Ş.",
    url="https://www.izmirmetro.com.tr",
    scope="stations",
)
IZBAN = Source(
    name="İZBAN istasyonları",
    publisher="İZBAN A.Ş.",
    url="https://www.izban.com.tr",
    scope="stations",
)
FERRY = Source(
    name="İZDENİZ iskeleleri",
    publisher="İZDENİZ A.Ş.",
    url="https://www.izdeniz.com.tr",
    scope="piers",
)
WATER = Source(
    name="İZSU baraj doluluk oranları",
    publisher="İzmir Su ve Kanalizasyon İdaresi (İZSU)",
    url="https://www.izsu.gov.tr",
    scope="dam_levels",
)
AIR = Source(
    name="İzmir hava kalitesi ölçüm değerleri",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://www.izmir.bel.tr",
    scope="station_readings",
)
TRANSIT_METRO = Source(
    name="İzmir Metro sefer sıklığı",
    publisher="İzmir Metro A.Ş.",
    url="https://www.izmirmetro.com.tr",
    scope="published_timetable",
)
TRANSIT_IZBAN = Source(
    name="İZBAN sefer saatleri",
    publisher="İZBAN A.Ş.",
    url="https://www.izban.com.tr",
    scope="published_timetable",
)
TRANSIT_FERRY = Source(
    name="İZDENİZ vapur sefer saatleri",
    publisher="İZDENİZ A.Ş.",
    url="https://www.izdeniz.com.tr",
    scope="published_timetable",
)
ESHOT_STOPS = Source(
    name="EShot otobüs durakları",
    publisher="İzmir Büyükşehir Belediyesi / EShot",
    url="https://acikveri.bizizmir.com/dataset/eshot-otobus-duraklari",
    scope="stops",
    dataset_id="eshot-otobus-duraklari",
    resource_id="0c791266-a2e4-4f14-82b8-9a9b102fbf94",
)
ESHOT_ARRIVALS = Source(
    name="EShot durağa yaklaşan otobüsler",
    publisher="İzmir İnovasyon ve Teknoloji A.Ş. (İZTEK)",
    url="https://acikveri.bizizmir.com/dataset/duraga-yaklasan-otobusler",
    scope="live_vehicle_positions",
    dataset_id="duraga-yaklasan-otobusler",
)
ESHOT_GTFS = Source(
    name="EShot GTFS toplu ulaşım verisi",
    publisher="İzmir Büyükşehir Belediyesi / EShot",
    url="https://acikveri.bizizmir.com/dataset/toplu-ulasim-gtfs-verileri",
    scope="published_timetable",
    dataset_id="toplu-ulasim-gtfs-verileri",
    resource_id="822f89be-48bf-4b36-8ed8-1912511032c4",
)
MARKET = Source(
    name="İzmir semt pazar yerleri",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com/dataset/semt-pazar-yerleri",
    scope="static_market_locations",
    dataset_id="semt-pazar-yerleri",
    resource_id="3e63e16e-74a9-40f6-8ad3-043ad4fa4a16",
)
WIFI = Source(
    name="WizmirNET ücretsiz kablosuz internet noktaları",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com/dataset/kablosuz-internet-baglanti-noktalari",
    scope="static_service_locations",
    dataset_id="kablosuz-internet-baglanti-noktalari",
    resource_id="60ca8451-d6d2-419f-b533-ab92bd5955b2",
)
IZMIRIM_CARD = Source(
    name="İzmirim Kart dolum noktaları",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com/dataset/izmirim-kart-dolum-noktalari",
    scope="static_service_locations",
    dataset_id="izmirim-kart-dolum-noktalari",
    resource_id="7a3efbec-fa4f-4b1e-9f9a-ac28f3608b40",
)
LIBRARY = Source(
    name="İzmir Büyükşehir Belediyesi kütüphaneleri",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com/dataset/izmir-buyuksehir-belediyesi-kutuphaneleri-bilgileri",
    scope="static_service_locations",
    dataset_id="izmir-buyuksehir-belediyesi-kutuphaneleri-bilgileri",
    resource_id="0c1b15b9-3f52-4437-bc16-56d366045ef5",
)
ESHOT_NOTICES = Source(
    name="EShot hat duyuruları",
    publisher="İzmir Büyükşehir Belediyesi / EShot",
    url="https://acikveri.bizizmir.com/dataset/otobus-hattina-ait-duyurular",
    scope="published_line_notices",
    dataset_id="otobus-hattina-ait-duyurular",
)
METRO_NOTICES = Source(
    name="İzmir Metro duyuruları",
    publisher="İzmir Metro A.Ş. / İZTEK",
    url="https://www.izmirmetro.com.tr",
    scope="published_operator_notices",
)
FERRY_NOTICES = Source(
    name="İZDENİZ duyuruları",
    publisher="İZDENİZ A.Ş.",
    url="https://www.izdeniz.com.tr/duyurular",
    scope="published_operator_notices",
)
IZBAN_NOTICES = Source(
    name="İZBAN duyuruları (erişilemiyor)",
    publisher="İZBAN A.Ş.",
    url="https://www.izban.com.tr",
    scope="published_operator_notices",
)


def source_failure_envelope(
    exc: BaseException,
    *,
    summary: str,
    used: list[Source] | None = None,
    limits: list[str] | None = None,
) -> dict:
    """Turn a connector failure into a typed, temporary error envelope.

    Only failures raised by the connector layer are mapped; programming errors
    keep propagating so they are never disguised as a source outage.
    """
    from app.core.envelope import error_envelope

    import httpx

    if isinstance(exc, httpx.TimeoutException):
        code = "source_timeout"
    elif isinstance(exc, (SourceRateLimitedError, SourceRateLimitExceeded)):
        code = "source_rate_limited"
    elif isinstance(exc, SourceTimeoutError):
        code = "source_timeout"
    elif getattr(exc, "code", None) == "schema_drift":
        code = "schema_drift"
    else:
        code = "source_unavailable"
    return error_envelope(
        summary=summary,
        warning=(
            f"Kaynak isteği başarısız oldu: {type(exc).__name__}. "
            "Veri uydurulmadı; boş yanıt 'hiç veri yok' kanıtı değildir."
        ),
        code=code,
        sources=used or [],
        limits=limits,
    )


def is_source_failure(exc: BaseException) -> bool:
    """True for errors raised by ``app.connectors`` for upstream problems."""
    import httpx

    return isinstance(exc, (SourceError, ValueError, OSError, httpx.HTTPError)) and not isinstance(
        exc, (UnicodeError, AssertionError)
    )
NEIGHBORHOOD_POPULATION = Source(
    name="İzmir mahalle nüfusu (cinsiyete göre)",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com/dataset/cinsiyete-gore-mahalle-nufus-bilgileri",
    scope="published_neighborhood_demographics",
    dataset_id="cinsiyete-gore-mahalle-nufus-bilgileri",
    resource_id="7ef10678-8a84-4e43-9122-3ac15c818b51",
)
NEIGHBORHOOD_BUILDINGS = Source(
    name="İzmir mahalle bazlı bina sayıları",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com/dataset/ilcelere-ait-mahalle-bazli-bina-sayilari",
    scope="published_building_stock",
    dataset_id="ilcelere-ait-mahalle-bazli-bina-sayilari",
    resource_id="54af6862-2d36-48d0-838f-a42133e8b943",
)
TAXI_STANDS = Source(
    name="İzmir taksi durakları",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com/dataset/taksi-durak-bilgileri",
    scope="static_service_locations",
    dataset_id="taksi-durak-bilgileri",
    resource_id="64a72577-5f4c-404c-8842-780d88f351df",
)
TRAFFIC = Source(
    name="İzmir ana arter hız ve süre verileri",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com/dataset/ana-arterler-gunluk-hiz-ve-sure-verileri",
    scope="historical_segment_speed",
    dataset_id="ana-arterler-gunluk-hiz-ve-sure-verileri",
    resource_id="a3bd880f-dfc6-4f65-bbfd-5fcc998268c3",
)
CHARGING = Source(
    name="İzmir engelli şarj istasyonları",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com/dataset/engelli-sarj-istasyonlari-konum-verisi",
    scope="static_service_locations",
    dataset_id="engelli-sarj-istasyonlari-konum-verisi",
    resource_id="028f2692-d930-481f-ab27-17a321bd1283",
)
TRANSIT_TRAM = Source(
    name="İzmir Tramvay hatları, istasyonları ve sefer sıklığı",
    publisher="İzmir Metro A.Ş.",
    url="https://openapi.izmir.bel.tr",
    scope="published_timetable",
)
ESHOT_LINE_POSITIONS = Source(
    name="EShot hat otobüs konumları",
    publisher="İzmir İnovasyon ve Teknoloji A.Ş. (İZTEK)",
    url="https://openapi.izmir.bel.tr",
    scope="live_vehicle_positions",
)
CBS_LAYERS = Source(
    name="İzmir Büyükşehir CBS önemli yer katmanları",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://openapi.izmir.bel.tr",
    scope="static_service_locations",
)
EVENTS = Source(
    name="İzmir Büyükşehir kültür sanat etkinlikleri",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://kultursanat.izmir.bel.tr",
    scope="published_events",
)
HAL_PRICES = Source(
    name="İzmir hal fiyatları (sebze-meyve ve balık)",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com/dataset/sebze-ve-meyve-hal-fiyatlari",
    scope="wholesale_price_bulletin",
)
PHARMACY_ALL = Source(
    name="İzmir eczane listesi",
    publisher="İzmir Büyükşehir Belediyesi",
    url="https://acikveri.bizizmir.com/dataset/nobetci-eczaneler-ve-eczane-listesi",
    scope="static_service_locations",
)
