from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class IntervalUsage:
    """Metered usage over a half-open interval [start, end)."""

    start: datetime
    end: datetime
    kwh: float

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("interval end must be after start")
        if self.kwh < 0:
            raise ValueError("interval kWh cannot be negative")


@dataclass(frozen=True)
class PeriodUsage:
    period: str
    kwh: float


@dataclass(frozen=True)
class ChargeLine:
    name: str
    amount: float
    kwh: Optional[float] = None
    rate: Optional[float] = None
    period: Optional[str] = None


@dataclass(frozen=True)
class BillingResult:
    days: int
    total_kwh: float
    by_period: dict[str, float]
    lines: list[ChargeLine]

    @property
    def total(self) -> float:
        return sum(line.amount for line in self.lines)
