from __future__ import annotations

from datetime import datetime


def pacific_now() -> datetime:
    """Return timezone-aware Pacific time or fail loudly if timezone data is unavailable.

    Silent fallback to the machine's local timezone can corrupt draw-cutoff decisions on
    computers configured outside British Columbia. ``tzdata`` is a runtime dependency,
    so an unavailable America/Vancouver zone is treated as a configuration error.
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Vancouver"))
    except Exception as exc:  # pragma: no cover - platform/configuration failure
        raise RuntimeError(
            "Pacific timezone data is unavailable. Install/repair the 'tzdata' package "
            "before running Lottery AI."
        ) from exc
