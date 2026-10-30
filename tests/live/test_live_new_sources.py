"""Live checks for the tram, live bus, CBS, events, hal and pharmacy sources.

These call the services directly. Every call must return a success envelope with
non-empty data. Allowed exception: live bus positions may legitimately be 0 vehicles.
"""

from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.services.bus import BusService
from app.services.cbs import CbsService
from app.services.transit import TransitService
from tests.live._assertions import assert_ok


@pytest.mark.asyncio
async def test_live_tram():
    service = TransitService(settings=get_settings())
    assert_ok(await service.tram_lines(), keys=("line_id", "name"))
    assert_ok(await service.tram_schedule(line_id=1), keys=("line_id", "stations"))


@pytest.mark.asyncio
async def test_live_bus_positions():
    # Explicit exception: no buses may be on the road right now.
    envelope = await BusService(settings=get_settings()).line_live_positions(line="5")
    assert_ok(envelope, allow_empty=True)


@pytest.mark.asyncio
async def test_live_cbs_events_hal_pharmacies():
    service = CbsService(settings=get_settings())
    assert_ok(await service.layer(layer="muzeler", limit=3), keys=("name", "lat", "lon"))
    assert_ok(await service.events(limit=3), keys=("id", "name", "starts_at"))
    assert_ok(await service.market_prices(kind="sebzemeyve", limit=3), keys=("product", "avg_price"))
    assert_ok(await service.pharmacies_all(area="Karşıyaka", limit=3), keys=("name", "address"))
