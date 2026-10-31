"""Pydantic input types that keep type errors attributable.

``float`` and ``int`` silently accept ``bool`` because ``True`` is an ``int`` in
Python: ``{"lat": true}`` became latitude 1.0 before any validator could see the
caller's mistake. These aliases add a ``before`` validator that rejects booleans
while keeping the string-to-number coercion the tools already advertise.
"""

from __future__ import annotations

from typing import Annotated, Optional

from pydantic import BeforeValidator


def _no_bool(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("mantıksal değer (boolean) sayı değildir; sayısal bir değer gönderin")
    return value


Number = Annotated[float, BeforeValidator(_no_bool)]
"""A float that refuses booleans but still accepts numeric strings."""

Count = Annotated[int, BeforeValidator(_no_bool)]
"""An int that refuses booleans."""

OptionalNumber = Optional[Number]
OptionalCount = Optional[Count]
