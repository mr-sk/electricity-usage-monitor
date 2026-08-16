from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union
from zoneinfo import ZoneInfo

from ..models import IntervalUsage


NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "espi": "http://naesb.org/espi",
}


def _text(node: ET.Element, path: str) -> Optional[str]:
    found = node.find(path, NS)
    return found.text.strip() if found is not None and found.text else None


def read_green_button_xml(path: Union[str, Path], tz: ZoneInfo) -> list[IntervalUsage]:
    """Read Green Button ESPI XML interval readings.

    Values are normalized to kWh when possible. Common electric Green Button
    exports use Wh with a powerOfTenMultiplier of 0, so value / 1000 is kWh.
    """
    root = ET.parse(path).getroot()
    readings: list[IntervalUsage] = []

    for reading in root.findall(".//espi:IntervalReading", NS):
        start_text = _text(reading, "espi:timePeriod/espi:start")
        duration_text = _text(reading, "espi:timePeriod/espi:duration")
        value_text = _text(reading, "espi:value")
        if not start_text or not duration_text or not value_text:
            continue

        start_epoch = int(start_text)
        duration_seconds = int(duration_text)
        value = float(value_text)

        # Default Green Button electric usage is Wh. If a utility emits kWh, it
        # can be converted upstream or handled with a provider-specific importer.
        kwh = value / 1000.0

        start = datetime.fromtimestamp(start_epoch, timezone.utc).astimezone(tz)
        end = datetime.fromtimestamp(start_epoch + duration_seconds, timezone.utc).astimezone(tz)
        readings.append(IntervalUsage(start=start, end=end, kwh=kwh))

    readings.sort(key=lambda item: item.start)
    return readings
