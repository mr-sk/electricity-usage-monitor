from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .models import BillingResult, ChargeLine, IntervalUsage
from .tou import TimeOfUseSchedule


@dataclass(frozen=True)
class PerKwhCharge:
    name: str
    rate: float
    period: Optional[str] = None


@dataclass(frozen=True)
class FixedCharge:
    name: str
    amount: float


@dataclass(frozen=True)
class Tariff:
    name: str
    tou: TimeOfUseSchedule
    daily_basic: float = 0.0
    per_kwh: tuple[PerKwhCharge, ...] = ()
    fixed_adjustments: tuple[FixedCharge, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


def bill_period_usage(tariff: Tariff, by_period: dict[str, float], days: int) -> BillingResult:
    if days <= 0:
        raise ValueError("days must be positive")

    total_kwh = sum(by_period.values())
    lines: list[ChargeLine] = []

    if tariff.daily_basic:
        lines.append(ChargeLine("Basic service", tariff.daily_basic * days, rate=tariff.daily_basic))

    for charge in tariff.per_kwh:
        kwh = total_kwh if charge.period is None else by_period.get(charge.period, 0.0)
        if not kwh:
            continue
        lines.append(ChargeLine(charge.name, kwh * charge.rate, kwh=kwh, rate=charge.rate, period=charge.period))

    for fixed in tariff.fixed_adjustments:
        if fixed.amount:
            lines.append(ChargeLine(fixed.name, fixed.amount))

    return BillingResult(days=days, total_kwh=total_kwh, by_period=dict(by_period), lines=lines)


def split_intervals_by_period(intervals: list[IntervalUsage], tariff: Tariff) -> dict[str, float]:
    usage: dict[str, float] = defaultdict(float)
    for interval in intervals:
        usage[tariff.tou.classify(interval.start)] += interval.kwh
    return dict(usage)


def bill_intervals(tariff: Tariff, intervals: list[IntervalUsage], cycle_start: date, cycle_end: date) -> BillingResult:
    if cycle_end <= cycle_start:
        raise ValueError("cycle_end must be after cycle_start")
    days = (cycle_end - cycle_start).days
    return bill_period_usage(tariff, split_intervals_by_period(intervals, tariff), days)


def filter_cycle(intervals: list[IntervalUsage], cycle_start: date, cycle_end: date, tz: ZoneInfo) -> list[IntervalUsage]:
    selected = []
    for interval in intervals:
        local_start = interval.start.astimezone(tz).date()
        if cycle_start <= local_start < cycle_end:
            selected.append(interval)
    return selected


def daily_totals(intervals: list[IntervalUsage], tz: ZoneInfo) -> dict[date, float]:
    totals: dict[date, float] = defaultdict(float)
    for interval in intervals:
        totals[interval.start.astimezone(tz).date()] += interval.kwh
    return dict(totals)


@dataclass(frozen=True)
class Projection:
    as_of: date
    elapsed_days: int
    remaining_days: int
    observed_kwh: float
    projected_kwh: float
    observed_bill: BillingResult
    projected_bill: BillingResult


def project_cycle(
    tariff: Tariff,
    intervals: list[IntervalUsage],
    cycle_start: date,
    cycle_end: date,
    tz: ZoneInfo,
    as_of: Optional[date] = None,
) -> Projection:
    if as_of is None:
        as_of = datetime.now(tz).date()
    if not (cycle_start <= as_of <= cycle_end):
        raise ValueError("as_of must fall within the billing cycle")

    observed = filter_cycle(intervals, cycle_start, min(as_of + timedelta(days=1), cycle_end), tz)
    observed_days = max(1, (min(as_of + timedelta(days=1), cycle_end) - cycle_start).days)
    total_days = (cycle_end - cycle_start).days
    remaining_days = max(0, total_days - observed_days)

    observed_by_period = split_intervals_by_period(observed, tariff)
    observed_bill = bill_period_usage(tariff, observed_by_period, observed_days)

    if observed_days:
        factor = total_days / observed_days
    else:
        factor = 1.0
    projected_by_period = {period: kwh * factor for period, kwh in observed_by_period.items()}
    projected_bill = bill_period_usage(tariff, projected_by_period, total_days)

    return Projection(
        as_of=as_of,
        elapsed_days=observed_days,
        remaining_days=remaining_days,
        observed_kwh=sum(observed_by_period.values()),
        projected_kwh=sum(projected_by_period.values()),
        observed_bill=observed_bill,
        projected_bill=projected_bill,
    )
