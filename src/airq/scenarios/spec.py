"""Scenario files (spec 9.5, Appendix F): a timed list of Senaryo Kontrol commands + hypotheses.

A scenario is plain YAML. `at_h` counts simulated hours from the scenario's time zero (the end of
the predictor warm-up). Step kinds: a device command (default), `edge`, `fleet`, `network`, and
`mark` (a bookmark that only names a time window for the scorecard). `expected` holds HYPOTHESES:
run_scenarios.py reports what really happened and never edits them to fit the result.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from airq.iot.schemas import Command, EdgeControl, FleetControl, NetControl

METRICS = (
    "mae_next_6h_h1", "mae_next_6h_h6", "warned", "matched", "lead_time_h", "peak_forecast_h6",
    "min_n_neighbors", "delivery_ratio", "latency_p95_ms", "n_forecasts",
)  # fmt: skip
RELATIONS = ("greater_than", "less_than", "true", "false")


@dataclass(frozen=True)
class Mark:
    """A named time window (no message is sent). `target` limits the scorecard to one station."""

    label: str
    target: str = "all"
    duration_h: float | None = None


Message = Command | EdgeControl | FleetControl | NetControl | Mark


def build_message(
    command: dict[str, Any], cmd_id: str | None = None, issued_at: datetime | None = None
) -> Message:
    """Turn a YAML `command` mapping into a validated message (raises ValueError)."""
    c = dict(command)
    kind = c.pop("kind", "device")
    if kind == "edge" and isinstance(c.get("filter"), bool):  # YAML 1.1 reads bare on/off as bool
        c["filter"] = "on" if c["filter"] else "off"
    base = {"cmd_id": cmd_id or str(uuid.uuid4()), "issued_at": issued_at or datetime.now()}
    try:
        if kind == "device":
            return Command(**base, **c)
        if kind == "edge":
            return EdgeControl(**base, **c)
        if kind == "fleet":
            return FleetControl(**base, **c)
        if kind == "network":
            return NetControl(**base, **c)
        if kind == "mark":
            return Mark(**c)
    except (ValidationError, TypeError) as exc:
        raise ValueError(f"invalid {kind} command {command}: {exc}") from exc
    raise ValueError(f"unknown command kind {kind!r}")


def label_of(msg: Message) -> str | None:
    return getattr(msg, "label", None)


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at_h: float = Field(ge=0)
    command: dict[str, Any]


class Expectation(BaseModel):
    """`metric` of the item `label` must be greater/less than `ref` item's metric or `value`."""

    model_config = ConfigDict(extra="forbid")

    label: str
    metric: str
    relation: Literal["greater_than", "less_than", "true", "false"]
    ref: str | None = None
    value: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _bool_relation(cls, data):
        if isinstance(data, dict) and isinstance(data.get("relation"), bool):
            data = {**data, "relation": "true" if data["relation"] else "false"}
        return data

    @model_validator(mode="after")
    def _valid(self) -> Expectation:
        if self.metric not in METRICS:
            raise ValueError(f"unknown metric {self.metric!r}; choose from {METRICS}")
        if self.relation in ("greater_than", "less_than") and (self.ref is None) == (
            self.value is None
        ):
            raise ValueError("greater_than / less_than need exactly one of ref / value")
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    start: str | None = None  # stack start (sim time); None = the demo's current position
    warmup_h: int = 240  # the predictor needs 168 + 72 h of history before it forecasts
    duration_h: float = 48
    steps: list[Step]
    expected: list[Expectation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Scenario:
        labels: set[str] = set()
        for s in self.steps:
            label = label_of(build_message(s.command))
            if label:
                if label in labels:
                    raise ValueError(f"duplicate label {label!r}")
                labels.add(label)
            if s.at_h > self.duration_h:
                raise ValueError(f"step at_h={s.at_h} is after duration_h={self.duration_h}")
        for e in self.expected:
            for ref in (e.label, e.ref):
                if ref is not None and ref not in labels:
                    raise ValueError(f"expected refers to unknown label {ref!r}")
        return self

    def labels(self) -> list[str]:
        return [lab for s in self.steps if (lab := label_of(build_message(s.command)))]


def load_scenario(path: Path | str) -> Scenario:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Scenario.model_validate(data)


def load_all(folder: Path | str) -> dict[str, Scenario]:
    out = {}
    for p in sorted(Path(folder).glob("*.yaml")):
        sc = load_scenario(p)
        if sc.name != p.stem:
            raise ValueError(f"{p.name}: name {sc.name!r} must equal the file name")
        out[sc.name] = sc
    return out


def evaluate_expected(sc: Scenario, scores: dict[str, dict]) -> list[dict]:
    """Compare hypotheses with the measured scorecard rows (label -> metrics). Never edits them."""
    out = []
    for e in sc.expected:
        got = (scores.get(e.label) or {}).get(e.metric)
        other = e.value if e.ref is None else (scores.get(e.ref) or {}).get(e.metric)
        if got is None or (e.relation in ("greater_than", "less_than") and other is None):
            verdict = "undetermined"
        elif e.relation == "true":
            verdict = "confirmed" if bool(got) else "refuted"
        elif e.relation == "false":
            verdict = "confirmed" if not bool(got) else "refuted"
        elif e.relation == "greater_than":
            verdict = "confirmed" if got > other else "refuted"
        else:
            verdict = "confirmed" if got < other else "refuted"
        out.append({**e.model_dump(), "measured": got, "reference": other, "verdict": verdict})
    return out
