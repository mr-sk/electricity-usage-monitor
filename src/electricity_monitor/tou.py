from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time


@dataclass(frozen=True)
class TimeWindow:
    start: time
    end: time
    period: str

    def contains(self, dt: datetime) -> bool:
        local_t = dt.time()
        if self.start <= self.end:
            return self.start <= local_t < self.end
        return local_t >= self.start or local_t < self.end


@dataclass(frozen=True)
class TimeOfUseSchedule:
    """Classify interval starts into named periods.

    This assumes intervals are small enough that using the interval start is a
    reasonable approximation. For 15-minute and hourly smart-meter data, that is
    the normal billing representation.
    """

    default_period: str
    weekday_windows: dict[int, list[TimeWindow]] = field(default_factory=dict)
    holidays: frozenset[date] = frozenset()

    def classify(self, dt: datetime) -> str:
        if dt.date() in self.holidays:
            return self.default_period
        windows = self.weekday_windows.get(dt.weekday(), [])
        for window in windows:
            if window.contains(dt):
                return window.period
        return self.default_period

