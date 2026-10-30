"""Live check for İZSU dam status (opt-in, IZMIR_LIVE=1).

Allowed exception: the data may come from the CSV fallback, but it must still be non-empty.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.settings import get_settings
from app.services.water import WaterService
from tests.live._assertions import assert_ok


@pytest.mark.asyncio
async def test_live_dam_status_yesterday():
    day = (date.today() - timedelta(days=1)).isoformat()
    envelope = await WaterService(settings=get_settings()).dam_status(date=day, dam_name="tahtalı")
    rows = assert_ok(envelope, keys=("name", "occupancy_percent", "observed_at"))
    assert all("Tahtal" in row["name"] for row in rows)
