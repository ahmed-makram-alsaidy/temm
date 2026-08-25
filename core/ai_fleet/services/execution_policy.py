"""Shared execution evidence policy."""

import os


DEFAULT_EXECUTABLE_AVAILABILITY_TTL_SECONDS = 30 * 60


def executable_availability_ttl_seconds() -> int:
    """Return the bounded TTL used for executable route observations."""
    raw = os.environ.get(
        "TEMM_EXECUTABLE_AVAILABILITY_TTL_SECONDS",
        str(DEFAULT_EXECUTABLE_AVAILABILITY_TTL_SECONDS),
    )
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_EXECUTABLE_AVAILABILITY_TTL_SECONDS
    return max(60, min(value, 24 * 60 * 60))
