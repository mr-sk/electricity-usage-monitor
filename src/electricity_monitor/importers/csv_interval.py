from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Union
from zoneinfo import ZoneInfo

from ..models import IntervalUsage


def _parse_dt(value: str, tz: ZoneInfo) -> datetime:
    text = value.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def read_interval_csv(path: Union[str, Path], tz: ZoneInfo, interval_minutes: int = 60) -> list[IntervalUsage]:
    """Read interval usage from a generic CSV.

    Accepted columns:
      - start,end,kwh
      - timestamp,kwh
    """
    rows: list[IntervalUsage] = []
    with Path(path).open(newline="") as fh:
        sample = fh.read(4096)
        if "<html" in sample.lower() or "<!doctype html" in sample.lower():
            raise ValueError("download returned HTML instead of interval CSV; authenticated session may have expired")
        fh.seek(0)
        reader = csv.DictReader(line for line in fh if line.strip())
        if not reader.fieldnames:
            raise ValueError("CSV is empty")
        fields = {name.strip().lower(): name for name in reader.fieldnames}
        if "kwh" not in fields:
            raise ValueError("CSV must include a kwh column")
        for raw in reader:
            if not raw:
                continue
            kwh_text = raw[fields["kwh"]].strip()
            if not kwh_text:
                continue
            if "start" in fields and "end" in fields:
                start = _parse_dt(raw[fields["start"]], tz)
                end = _parse_dt(raw[fields["end"]], tz)
            elif "start" in fields:
                start = _parse_dt(raw[fields["start"]], tz)
                end = start + timedelta(minutes=interval_minutes)
            elif "timestamp" in fields:
                start = _parse_dt(raw[fields["timestamp"]], tz)
                end = start + timedelta(minutes=interval_minutes)
            else:
                raise ValueError("CSV must include start/end or timestamp columns")
            rows.append(IntervalUsage(start=start, end=end, kwh=float(kwh_text)))
    rows.sort(key=lambda item: item.start)
    return rows
