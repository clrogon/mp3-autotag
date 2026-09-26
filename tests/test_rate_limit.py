from __future__ import annotations

from mp3_autotag.rate_limit import RateLimiter


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        self.now += delta


def test_first_call_never_sleeps():
    clock = FakeClock()
    sleeps: list[float] = []
    limiter = RateLimiter(1.0, clock=clock, sleep=sleeps.append)

    limiter.acquire()

    assert sleeps == []


def test_rapid_second_call_sleeps_remaining_interval():
    clock = FakeClock()
    sleeps: list[float] = []

    def fake_sleep(duration: float) -> None:
        sleeps.append(duration)
        clock.advance(duration)

    limiter = RateLimiter(1.0, clock=clock, sleep=fake_sleep)

    limiter.acquire()
    clock.advance(0.2)  # only 200ms elapsed, need to wait 800ms more
    limiter.acquire()

    assert sleeps == [0.8]


def test_call_after_interval_elapsed_does_not_sleep():
    clock = FakeClock()
    sleeps: list[float] = []
    limiter = RateLimiter(1.0, clock=clock, sleep=sleeps.append)

    limiter.acquire()
    clock.advance(1.5)  # more than min_interval has passed
    limiter.acquire()

    assert sleeps == []


def test_enforces_spacing_across_many_rapid_calls():
    clock = FakeClock()
    sleeps: list[float] = []

    def fake_sleep(duration: float) -> None:
        sleeps.append(duration)
        clock.advance(duration)

    limiter = RateLimiter(0.5, clock=clock, sleep=fake_sleep)

    for _ in range(5):
        limiter.acquire()  # clock never advances between calls except via sleep

    # First call: no sleep. Remaining 4 calls: each must sleep the full interval.
    assert sleeps == [0.5, 0.5, 0.5, 0.5]
