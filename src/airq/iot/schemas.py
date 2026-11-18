"""MQTT payload schemas (Pydantic v2, schema_version = 1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

SCHEMA_VERSION = 1
MEASUREMENTS = ["pm25", "pm10", "so2", "no2", "co", "o3", "temp", "pres", "dewp", "rain", "wspm"]
WIND_DIRECTIONS = {
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
}  # fmt: skip


class Telemetry(BaseModel):
    """One hourly reading from one station. Missing measurements are sent as null."""

    model_config = ConfigDict(extra="forbid")

    device_id: str
    station: str
    seq: int
    ts: datetime  # simulated time, naive Asia/Shanghai local time
    sent_at: datetime  # wall clock (ms), used for end-to-end latency
    schema_version: Literal[1] = 1
    pm25: float | None = None
    pm10: float | None = None
    so2: float | None = None
    no2: float | None = None
    co: float | None = None
    o3: float | None = None
    temp: float | None = None
    pres: float | None = None
    dewp: float | None = None
    rain: float | None = None
    wd: str | None = None
    wspm: float | None = None
    quality_flags: list[str] | None = None  # set by the edge gateway only

    @field_validator("seq")
    @classmethod
    def _seq_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("seq must be >= 0")
        return v

    @field_validator(*MEASUREMENTS)
    @classmethod
    def _finite(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            raise ValueError("measurement must be finite (send null for missing)")
        return v

    @field_validator("wd")
    @classmethod
    def _wind_dir(cls, v: str | None) -> str | None:
        if v is not None and v not in WIND_DIRECTIONS:
            raise ValueError(f"unknown wind direction {v!r}")
        return v

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=False)

    @classmethod
    def from_json(cls, payload: str | bytes) -> Telemetry:
        return cls.model_validate_json(payload)


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    station: str
    seq: int  # last telemetry seq sent
    ts: datetime  # simulated time
    sent_at: datetime
    schema_version: Literal[1] = 1

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, payload: str | bytes) -> Heartbeat:
        return cls.model_validate_json(payload)
