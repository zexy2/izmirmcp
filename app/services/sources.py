from __future__ import annotations

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
