from __future__ import annotations

import unittest
from argparse import Namespace
from datetime import date
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from electricity_monitor.billing import Projection, bill_period_usage, split_intervals_by_period
from electricity_monitor.cli import format_summary_report
from electricity_monitor.importers.csv_interval import read_interval_csv
from electricity_monitor.models import IntervalUsage
from electricity_monitor.providers import get_provider


class PsegLiRate194Tests(unittest.TestCase):
    def test_rate194_reproduces_bill_without_personal_identifiers(self):
        tariff = get_provider("psegliny-rate194")
        result = bill_period_usage(tariff, {"peak": 335, "off_peak": 2084}, days=33)

        self.assertEqual(round(result.total, 2), 671.29)
        self.assertEqual(round(result.by_period["peak"], 1), 335.0)
        self.assertEqual(round(result.by_period["off_peak"], 1), 2084.0)

    def test_rate194_tou_classifies_weekday_peak_and_weekend_offpeak(self):
        tariff = get_provider("psegliny-rate194")
        tz = ZoneInfo("America/New_York")
        intervals = [
            IntervalUsage(
                start=datetime(2026, 7, 27, 15, 0, tzinfo=tz),
                end=datetime(2026, 7, 27, 16, 0, tzinfo=tz),
                kwh=2.0,
            ),
            IntervalUsage(
                start=datetime(2026, 7, 26, 15, 0, tzinfo=tz),
                end=datetime(2026, 7, 26, 16, 0, tzinfo=tz),
                kwh=3.0,
            ),
        ]

        usage = split_intervals_by_period(intervals, tariff)

        self.assertEqual(usage["peak"], 2.0)
        self.assertEqual(usage["off_peak"], 3.0)

    def test_rate194_treats_observed_holidays_as_offpeak(self):
        tariff = get_provider("psegliny-rate194")
        tz = ZoneInfo("America/New_York")
        usage = split_intervals_by_period([
            IntervalUsage(
                start=datetime(2026, 7, 3, 15, 0, tzinfo=tz),
                end=datetime(2026, 7, 3, 16, 0, tzinfo=tz),
                kwh=4.0,
            )
        ], tariff)

        self.assertEqual(usage["off_peak"], 4.0)
        self.assertNotIn("peak", usage)

    def test_summary_report_uses_stable_field_labels(self):
        tariff = get_provider("psegliny-rate194")
        observed_bill = bill_period_usage(tariff, {"peak": 211.2, "off_peak": 1286.6}, days=19)
        projected_bill = bill_period_usage(tariff, {"peak": 322.3, "off_peak": 1963.8}, days=29)
        projection = Projection(
            as_of=date(2026, 8, 16),
            elapsed_days=19,
            remaining_days=8,
            observed_kwh=1497.8,
            projected_kwh=2286.1,
            observed_bill=observed_bill,
            projected_bill=projected_bill,
        )
        args = Namespace(
            last_cycle_bill=671.29,
            last_cycle_usage_kwh=2419,
            last_cycle_peak_kwh=335,
            last_cycle_offpeak_kwh=2084,
            pricing_changed="no",
            anomalies=None,
            cost_basis=None,
        )

        output = format_summary_report(args, projection, date(2026, 7, 29), date(2026, 8, 27))

        self.assertIn("Current date range: 2026-07-29 - 2026-08-16", output)
        self.assertIn("Days left in billing cycle: 8", output)
        self.assertIn("Current bill: $418.65 estimated all-in to date", output)
        self.assertIn("Other charges/fees: $29.63 basic service + per-kWh fees + taxes/adjustments", output)
        self.assertIn("Last billing cycle price: $671.29", output)
        self.assertIn("Last billing cycle usage: 2,419.0 kWh total; 335.0 peak / 2,084.0 off-peak", output)
        self.assertIn("Did pricing of electricity change: no", output)

    def test_csv_import_rejects_html_downloads(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.csv"
            path.write_text("\n\n<!doctype html><html><body>login</body></html>\n")

            with self.assertRaisesRegex(ValueError, "download returned HTML"):
                read_interval_csv(path, ZoneInfo("America/New_York"))


if __name__ == "__main__":
    unittest.main()
