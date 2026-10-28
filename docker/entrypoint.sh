#!/bin/sh
# Eagerly build the GTFS timetable store, then exec the requested command.
#
# The image does not ship .data/, so the store lives in the /data volume and is
# rebuilt from the published archive on first start. A failed rebuild is not
# fatal: pytest-free services (catalog, nearby, water, air, transit, maker data)
# keep working, and izmir_bus_departures rebuilds lazily and reports an honest
# envelope instead of a fabricated timetable. The failure is logged so the
# container log tells the operator why departures may be unavailable.
set -eu

if [ "${IZMIR_MCP_SKIP_GTFS_BUILD:-0}" = "1" ]; then
    echo "gtfs store build skipped (IZMIR_MCP_SKIP_GTFS_BUILD=1)" >&2
else
    python -m app.storage.gtfs_schedule || \
        echo "gtfs store build failed; continuing without a prebuilt store" >&2
fi

exec "$@"
