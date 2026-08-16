from __future__ import annotations

from datetime import date, timedelta, time

from ..billing import FixedCharge, PerKwhCharge, Tariff
from ..tou import TimeOfUseSchedule, TimeWindow


def _weekday_peak_windows() -> dict[int, list[TimeWindow]]:
    peak = TimeWindow(start=time(15, 0), end=time(19, 0), period="peak")
    return {weekday: [peak] for weekday in range(0, 5)}


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _us_observed_holidays(start_year: int = 2020, end_year: int = 2035) -> frozenset[date]:
    holidays: set[date] = set()
    for year in range(start_year, end_year + 1):
        holidays.update({
            _observed(date(year, 1, 1)),             # New Year's Day
            _nth_weekday(year, 1, 0, 3),             # Martin Luther King Jr. Day
            _nth_weekday(year, 2, 0, 3),             # Presidents' Day
            _last_weekday(year, 5, 0),               # Memorial Day
            _observed(date(year, 6, 19)),            # Juneteenth
            _observed(date(year, 7, 4)),             # Independence Day
            _nth_weekday(year, 9, 0, 1),             # Labor Day
            _nth_weekday(year, 10, 0, 2),            # Columbus/Indigenous Peoples' Day
            _observed(date(year, 11, 11)),           # Veterans Day
            _nth_weekday(year, 11, 3, 4),            # Thanksgiving
            _observed(date(year, 12, 25)),           # Christmas
        })
    return frozenset(holidays)


# PSEG Long Island Rate 194 - Residential, Time-Of-Day, Standard, 2 period.
# Rates below are from a 2026-07-31 bill for service 2026-06-26 to 2026-07-29.
# Fixed adjustments vary by bill and should be treated as configurable.
PSEGLI_RATE_194 = Tariff(
    name="PSEG Long Island Rate 194 Residential TOD Standard 2-period",
    tou=TimeOfUseSchedule(
        default_period="off_peak",
        weekday_windows=_weekday_peak_windows(),
        holidays=_us_observed_holidays(),
    ),
    daily_basic=0.5600,
    per_kwh=(
        PerKwhCharge("Delivery peak", 0.2217, "peak"),
        PerKwhCharge("Delivery off-peak", 0.1093, "off_peak"),
        PerKwhCharge("Power supply peak", 0.265970, "peak"),
        PerKwhCharge("Power supply off-peak", 0.113004, "off_peak"),
        PerKwhCharge("Merchant function charge", 0.001765, None),
        PerKwhCharge("DER charge", 0.006015, None),
    ),
    fixed_adjustments=(
        FixedCharge("Delivery service adjustment", -2.89),
        FixedCharge("Revenue decoupling adjustment", -0.59),
        FixedCharge("NY State assessment", 1.85),
        FixedCharge("Revenue-based PILOTs", 8.97),
    ),
    metadata={
        "utility": "PSEG Long Island",
        "rate": "194",
        "peak_window": "Weekdays 15:00-19:00; weekends and configured holidays off-peak",
    },
)
