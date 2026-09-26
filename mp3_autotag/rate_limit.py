"""Minimum-interval rate limiter, shared by the MusicBrainz and AcoustID
clients (spec §7.7: MusicBrainz 1 req/s, AcoustID 3 req/s).

Clock and sleep are injectable so tests can verify enforced spacing without
real delays.
"""

from __future__ import annotations

import time
from typing import Callable


class RateLimiter:
    def __init__(
        self,
        min_interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last_call: float | None = None

    def acquire(self) -> None:
        now = self._clock()
        if self._last_call is not None:
            wait = self._min_interval - (now - self._last_call)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_call = now
