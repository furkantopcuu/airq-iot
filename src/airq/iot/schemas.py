"""MQTT payload schemas (Pydantic v2, schema_version = 1)."""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class WarningMsg(BaseModel):
    """Early warning published on airq/warnings/{station}."""

    model_config = ConfigDict(extra="forbid")

    station: str
    made_at_ts: datetime  # simulated time the forecast was issued
    horizon: int
    threshold: float
    yhat: float
    delta: float  # safety margin: the warning fired because yhat > threshold - delta
    basis: str = "point"  # "point" forecast (q90-based warnings are RQ4)
    sent_at: datetime
    schema_version: Literal[1] = 1

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, payload: str | bytes) -> WarningMsg:
        return cls.model_validate_json(payload)


# --- command channel (spec 9.3): API -> MQTT airq/cmd/* -> devices -> airq/cmd/ack/* -------------
MODES = ("replay", "manual", "offset", "scale", "ramp", "perturb", "offline")
PERTURB_TYPES = ("spike", "stuck", "dropout")
ALL_TARGET = "all"  # a device command for every station (published on airq/cmd/fleet)


class Command(BaseModel):
    """Intervention on one station (topic airq/cmd/{station}) or on all (airq/cmd/fleet)."""

    model_config = ConfigDict(extra="forbid")

    cmd_id: str
    issued_at: datetime
    target: str  # station name or "all"
    variables: list[str] = Field(default_factory=lambda: ["pm25"])
    mode: Literal["replay", "manual", "offset", "scale", "ramp", "perturb", "offline"]
    params: dict[str, Any] = Field(default_factory=dict)
    duration_h: float | None = None  # None = until `reset` (ramp: the length of the ramp)
    coupled: bool = False  # a PM2.5 change also moves PM10 (train-median PM10/PM2.5 ratio)
    allow_invalid: bool = False  # "faulty input test": values outside the physical range pass
    label: str | None = None
    schema_version: Literal[1] = 1

    @field_validator("variables")
    @classmethod
    def _known_variables(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("variables must not be empty")
        bad = [x for x in v if x not in MEASUREMENTS]
        if bad:
            raise ValueError(f"unknown variables {bad}")
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def _mode_params(self) -> Command:
        p, m = self.params, self.mode
        need = {"manual": ["value"], "offset": ["delta"], "scale": ["factor"],
                "perturb": ["type"]}  # fmt: skip
        for key in need.get(m, []):
            if key not in p:
                raise ValueError(f"mode {m!r} needs params.{key}")
        if m == "ramp":
            if ("target" in p) == ("delta" in p):
                raise ValueError("mode 'ramp' needs exactly one of params.target / params.delta")
            if not self.duration_h or self.duration_h <= 0:
                raise ValueError("mode 'ramp' needs duration_h > 0 (the length of the ramp)")
        if m == "perturb":
            if p["type"] not in PERTURB_TYPES:
                raise ValueError(f"params.type must be one of {PERTURB_TYPES}")
            if p["type"] == "spike" and "severity" not in p:
                raise ValueError("a spike needs params.severity (k, in sigma units)")
            if not self.duration_h or self.duration_h <= 0:
                raise ValueError("mode 'perturb' needs duration_h > 0")
        if self.duration_h is not None and self.duration_h <= 0:
            raise ValueError("duration_h must be > 0")
        for key in ("value", "delta", "factor", "target", "severity"):
            ok = isinstance(p.get(key, 0), (int, float)) and math.isfinite(p.get(key, 0))
            if key in p and not ok:
                raise ValueError(f"params.{key} must be a finite number")
        return self

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, payload: str | bytes) -> Command:
        return cls.model_validate_json(payload)


class FleetControl(BaseModel):
    """Control of the shared simulation clock (airq/cmd/fleet)."""

    model_config = ConfigDict(extra="forbid")

    cmd_id: str
    issued_at: datetime
    action: Literal["pause", "resume", "speedup", "jump", "reset"]
    value: float | str | None = None  # speedup: x; jump: ISO timestamp
    label: str | None = None
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def _value(self) -> FleetControl:
        if self.action == "speedup" and not (
            isinstance(self.value, (int, float)) and self.value > 0
        ):
            raise ValueError("speedup needs a positive number in `value`")
        if self.action == "jump":
            try:
                datetime.fromisoformat(str(self.value))
            except ValueError as exc:
                raise ValueError("jump needs an ISO timestamp in `value`") from exc
        return self

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, payload: str | bytes) -> FleetControl:
        return cls.model_validate_json(payload)


class NetControl(BaseModel):
    """Network emulation parameters (airq/cmd/net); `reset` clears all emulation."""

    model_config = ConfigDict(extra="forbid")

    cmd_id: str
    issued_at: datetime
    target: str = ALL_TARGET  # station name or "all"
    loss_rate: float = 0.0
    delay_ms: float = 0.0
    jitter_ms: float = 0.0
    reorder_rate: float = 0.0
    reset: bool = False
    label: str | None = None
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def _ranges(self) -> NetControl:
        if not 0.0 <= self.loss_rate <= 1.0 or not 0.0 <= self.reorder_rate <= 1.0:
            raise ValueError("loss_rate and reorder_rate must be in [0, 1]")
        if self.delay_ms < 0 or self.jitter_ms < 0:
            raise ValueError("delay_ms and jitter_ms must be >= 0")
        return self

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, payload: str | bytes) -> NetControl:
        return cls.model_validate_json(payload)


class EdgeControl(BaseModel):
    """Edge validation filter on/off (airq/cmd/edge)."""

    model_config = ConfigDict(extra="forbid")

    cmd_id: str
    issued_at: datetime
    filter: Literal["on", "off"]
    label: str | None = None
    schema_version: Literal[1] = 1

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, payload: str | bytes) -> EdgeControl:
        return cls.model_validate_json(payload)


class Ack(BaseModel):
    """Answer to a command, on airq/cmd/ack/{station|fleet|net|edge}."""

    model_config = ConfigDict(extra="forbid")

    cmd_id: str
    source: str  # who answers: station name, "fleet", "net" or "edge"
    ok: bool
    error: str | None = None
    applied_at_ts: datetime | None = None  # simulated time the command took effect
    schema_version: Literal[1] = 1

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, payload: str | bytes) -> Ack:
        return cls.model_validate_json(payload)


def parse_command(payload: str | bytes) -> Command | FleetControl | NetControl | EdgeControl:
    """Dispatch a cmd payload to its model by its distinguishing field (raises ValueError)."""
    try:
        d = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not JSON: {exc}") from exc
    if not isinstance(d, dict):
        raise ValueError("command must be a JSON object")
    if "mode" in d:
        return Command.model_validate(d)
    if "action" in d:
        return FleetControl.model_validate(d)
    if "filter" in d:
        return EdgeControl.model_validate(d)
    if any(k in d for k in ("loss_rate", "delay_ms", "jitter_ms", "reorder_rate", "reset")):
        return NetControl.model_validate(d)
    raise ValueError("unrecognised command (needs mode / action / filter / net fields)")
