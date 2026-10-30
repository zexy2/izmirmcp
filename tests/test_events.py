from __future__ import annotations

import pytest

from app.connectors.http import SourceError
from app.connectors.ibb_cbs import parse_event_rows
from app.core.settings import get_settings
from app.services.cbs import CbsService
from tests.conftest import fresh

RAW = [
    {"Tur": "SERGİ", "Id": 6583, "Adi": "İzmir Fotoğrafhanesi", "EtkinlikBitisTarihi": "2026-12-13T18:00:00",
     "EtkinlikMerkezi": "Kent Arşivi", "KisaAciklama": "Sergi", "BiletSatisLinki": None,
     "UcretsizMi": True, "EtkinlikUrl": "sergi-izmir", "EtkinlikBaslamaTarihi": "2025-12-11T18:00:00"},
    {"Tur": "KONSER", "Id": 7, "Adi": "Senfoni", "EtkinlikMerkezi": "AASSM", "UcretsizMi": False,
     "EtkinlikBaslamaTarihi": "2026-11-01T20:00:00"},
    "junk",
]


def test_event_parse():
    rows = parse_event_rows(RAW)
    assert len(rows) == 2
    assert rows[0]["url"].endswith("/sergi-izmir")
    assert rows[1]["url"] is None and rows[1]["free"] is False


class FakeApi:
    def __init__(self, fail=False):
        self.fail = fail

    async def events(self):
        if self.fail:
            raise SourceError("down")
        return parse_event_rows(RAW), fresh()


@pytest.mark.asyncio
async def test_events_filters():
    service = CbsService(settings=get_settings(), api=FakeApi())
    free = await service.events(free_only=True)
    assert [row["id"] for row in free["data"]] == [6583]
    query = await service.events(query="konser")
    assert [row["id"] for row in query["data"]] == [7]


@pytest.mark.asyncio
async def test_events_failure():
    envelope = await CbsService(settings=get_settings(), api=FakeApi(fail=True)).events()
    assert envelope["ok"] is False
