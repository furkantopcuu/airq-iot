"""Application-layer network emulation for the virtual devices (spec 8.2, 6.1).

Loss means the message is NEVER published (the sensor -> gateway radio link dropped it), so MQTT's
own retransmission cannot save it; the `seq` counter still advances, which is how the edge sees the
gap. Delay and jitter postpone the publication; reordering adds extra delay to a fraction of the
messages so that they overtake each other. This is NOT OS-level `tc netem` (not available on
Windows); it is stated as a limitation in the paper.
"""

from __future__ import annotations

import contextlib
import heapq
import threading
import time
from dataclasses import dataclass, field


@dataclass
class NetParams:
    loss_rate: float = 0.0
    delay_ms: float = 0.0
    jitter_ms: float = 0.0
    reorder_rate: float = 0.0

    def validate(self) -> NetParams:
        if not 0.0 <= self.loss_rate <= 1.0 or not 0.0 <= self.reorder_rate <= 1.0:
            raise ValueError("loss_rate and reorder_rate must be in [0, 1]")
        if self.delay_ms < 0 or self.jitter_ms < 0:
            raise ValueError("delay_ms and jitter_ms must be >= 0")
        return self

    @classmethod
    def parse(cls, text: str) -> NetParams:
        """'loss=0.1,delay=200,jitter=20,reorder=0.05' (any subset) -> NetParams."""
        keys = {"loss": "loss_rate", "delay": "delay_ms", "jitter": "jitter_ms",
                "reorder": "reorder_rate"}  # fmt: skip
        values = {}
        for part in filter(None, (p.strip() for p in text.split(","))):
            k, _, v = part.partition("=")
            if k not in keys:
                raise ValueError(f"unknown netem key {k!r}")
            values[keys[k]] = float(v)
        return cls(**values).validate()


class NetEm:
    """Fleet-wide parameters with optional per-station overrides; changeable at run time."""

    def __init__(self, params: NetParams | None = None, seed: int = 0):
        import random

        self.default = params or NetParams()
        self.per_station: dict[str, NetParams] = {}
        self._rng = random.Random(seed)  # nosec B311 - network emulation, not cryptography
        self._lock = threading.Lock()

    def set(self, params: NetParams, station: str | None = None) -> None:
        params.validate()
        with self._lock:
            if station is None:
                self.default = params
            else:
                self.per_station[station] = params

    def reset(self) -> None:
        with self._lock:
            self.default = NetParams()
            self.per_station.clear()

    def plan(self, station: str) -> float | None:
        """None = drop the message; otherwise the delay (seconds) before it is published."""
        with self._lock:
            p = self.per_station.get(station, self.default)
            if p.loss_rate > 0 and self._rng.random() < p.loss_rate:
                return None
            delay = p.delay_ms
            if p.jitter_ms > 0:
                delay = max(0.0, self._rng.gauss(p.delay_ms, p.jitter_ms))
            if p.reorder_rate > 0 and self._rng.random() < p.reorder_rate:
                delay += max(2.0 * p.delay_ms, 100.0)  # this message overtakes later ones
        return delay / 1000.0


@dataclass(order=True)
class _Item:
    due: float
    n: int
    fn: object = field(compare=False)


class DelayedRunner:
    """Runs callables after a delay on one background thread (publish-later queue)."""

    def __init__(self) -> None:
        self._heap: list[_Item] = []
        self._cv = threading.Condition()
        self._n = 0
        self._stop = False
        self._thread = threading.Thread(target=self._loop, name="netem-delay", daemon=True)
        self._thread.start()

    def call_later(self, delay_s: float, fn) -> None:
        with self._cv:
            self._n += 1
            heapq.heappush(self._heap, _Item(time.monotonic() + delay_s, self._n, fn))
            self._cv.notify()

    def pending(self) -> int:
        with self._cv:
            return len(self._heap)

    def drain(self, timeout_s: float = 30.0) -> bool:
        """Wait until every delayed call has been executed."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            if self.pending() == 0:
                return True
            time.sleep(0.01)
        return False

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._stop and (not self._heap or self._heap[0].due > time.monotonic()):
                    wait = (
                        None if not self._heap else max(0.0, self._heap[0].due - time.monotonic())
                    )
                    self._cv.wait(timeout=wait)
                if self._stop:
                    return
                item = heapq.heappop(self._heap)
            with contextlib.suppress(Exception):  # a failed publish must not kill the emulator
                item.fn()
