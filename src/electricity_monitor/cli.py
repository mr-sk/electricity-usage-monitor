from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Optional
from zoneinfo import ZoneInfo

from .billing import bill_period_usage, project_cycle
from .importers import read_green_button_xml, read_interval_csv
import os

from .mymeter import (
    MyMeterBrowserSession,
    MyMeterCredentialSession,
    MyMeterSession,
    add_mymeter_browser_download_args,
    add_mymeter_download_args,
    add_mymeter_login_args,
    load_env_file,
    load_replay_request,
    with_overrides,
)
from .providers import get_provider


def money(value: float) -> str:
    return f"${value:,.2f}"


def yes_no_unknown(value: Optional[str]) -> str:
    if value is None:
        return "unknown"
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return "yes"
    if normalized in {"0", "false", "no", "n"}:
        return "no"
    return value.strip() or "unknown"


def period_kwh(result, period: str) -> float:
    return result.by_period.get(period, 0.0)


def period_amount(result, period: str) -> float:
    return sum(line.amount for line in result.lines if line.period == period)


def charge_group_amount(result, names: set[str]) -> float:
    normalized = {name.lower() for name in names}
    return sum(line.amount for line in result.lines if line.name.lower() in normalized)


def non_period_usage_fee_amount(result) -> float:
    return sum(line.amount for line in result.lines if line.kwh is not None and line.period is None)


def fixed_adjustment_amount(result) -> float:
    return sum(line.amount for line in result.lines if line.kwh is None and line.name.lower() != "basic service")


def describe_anomalies(projection) -> str:
    total = projection.observed_bill.total_kwh
    if total <= 0:
        return "No usage data observed yet."

    peak_pct = (period_kwh(projection.observed_bill, "peak") / total) * 100.0
    if peak_pct >= 25.0:
        return f"Peak usage is high at {peak_pct:.1f}% of observed usage."
    return f"None detected; peak is {peak_pct:.1f}% of observed usage."


def format_summary_report(args: argparse.Namespace, projection, cycle_start: date, cycle_end: date) -> str:
    observed = projection.observed_bill
    projected = projection.projected_bill
    observed_peak_amount = period_amount(observed, "peak")
    observed_off_peak_amount = period_amount(observed, "off_peak")
    observed_basic = charge_group_amount(observed, {"Basic service"})
    observed_usage_fees = non_period_usage_fee_amount(observed)
    observed_fixed_adjustments = fixed_adjustment_amount(observed)
    observed_other = observed_basic + observed_usage_fees + observed_fixed_adjustments

    last_usage_parts: list[str] = []
    if args.last_cycle_usage_kwh is not None:
        last_usage_parts.append(f"{args.last_cycle_usage_kwh:,.1f} kWh total")
    if args.last_cycle_peak_kwh is not None or args.last_cycle_offpeak_kwh is not None:
        peak = args.last_cycle_peak_kwh if args.last_cycle_peak_kwh is not None else 0.0
        off_peak = args.last_cycle_offpeak_kwh if args.last_cycle_offpeak_kwh is not None else 0.0
        last_usage_parts.append(f"{peak:,.1f} peak / {off_peak:,.1f} off-peak")

    last_price = money(args.last_cycle_bill) if args.last_cycle_bill is not None else "unknown"
    last_usage = "; ".join(last_usage_parts) if last_usage_parts else "unknown"

    lines = [
        f"Current date range: {cycle_start.isoformat()} - {projection.as_of.isoformat()}",
        f"Days left in billing cycle: {projection.remaining_days}",
        f"Current bill: {money(observed.total)} estimated all-in to date",
        f"Peak: {period_kwh(observed, 'peak'):,.1f} kWh, {money(observed_peak_amount)} delivery+supply",
        f"Off-Peak: {period_kwh(observed, 'off_peak'):,.1f} kWh, {money(observed_off_peak_amount)} delivery+supply",
        f"Other charges/fees: {money(observed_other)} basic service + per-kWh fees + taxes/adjustments",
        "",
        f"Projected full-cycle bill: {money(projected.total)}",
        f"Projected full-cycle usage: {projection.projected_kwh:,.1f} kWh",
        "",
        f"Last billing cycle price: {last_price}",
        f"Last billing cycle usage: {last_usage}",
        "",
        f"Any anomalies: {args.anomalies or describe_anomalies(projection)}",
        f"Did pricing of electricity change: {yes_no_unknown(args.pricing_changed)}",
        f"Cost basis: {args.cost_basis or 'configured tariff rates and fixed adjustments'}",
    ]
    return "\n".join(lines)


def print_bill(result) -> None:
    print(f"Total usage: {result.total_kwh:,.1f} kWh over {result.days} day(s)")
    for period, kwh in sorted(result.by_period.items()):
        print(f"  {period}: {kwh:,.1f} kWh")
    print("")
    for line in result.lines:
        if line.kwh is None:
            print(f"{line.name}: {money(line.amount)}")
        elif line.period:
            print(f"{line.name}: {line.kwh:,.1f} kWh @ ${line.rate:.6f} = {money(line.amount)}")
        else:
            print(f"{line.name}: {line.kwh:,.1f} kWh @ ${line.rate:.6f} = {money(line.amount)}")
    print(f"TOTAL: {money(result.total)}")


def cmd_bill(args: argparse.Namespace) -> int:
    tariff = get_provider(args.provider)
    result = bill_period_usage(
        tariff,
        {"peak": args.peak_kwh, "off_peak": args.offpeak_kwh},
        args.days,
    )
    print_bill(result)
    return 0


def _load_intervals(args: argparse.Namespace, tz: ZoneInfo):
    if args.csv:
        return read_interval_csv(args.csv, tz, args.interval_minutes)
    if args.green_button:
        return read_green_button_xml(args.green_button, tz)
    raise ValueError("provide --csv or --green-button")


def cmd_report(args: argparse.Namespace) -> int:
    tariff = get_provider(args.provider)
    tz = ZoneInfo(args.tz)
    intervals = _load_intervals(args, tz)
    cycle_start = date.fromisoformat(args.cycle_start)
    cycle_end = date.fromisoformat(args.cycle_end)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    projection = project_cycle(tariff, intervals, cycle_start, cycle_end, tz, as_of)

    if args.format == "summary":
        print(format_summary_report(args, projection, cycle_start, cycle_end))
        return 0

    print(f"Electricity Report - cycle {cycle_start.isoformat()} to {cycle_end.isoformat()}")
    print(f"As of: {projection.as_of.isoformat()}")
    print("")
    print(f"Observed: {projection.observed_kwh:,.1f} kWh over {projection.elapsed_days} day(s)")
    for period, kwh in sorted(projection.observed_bill.by_period.items()):
        print(f"  {period}: {kwh:,.1f} kWh")
    print(f"Observed bill estimate: {money(projection.observed_bill.total)}")
    print("")
    print(f"Projected full-cycle usage: {projection.projected_kwh:,.1f} kWh")
    for period, kwh in sorted(projection.projected_bill.by_period.items()):
        print(f"  {period}: {kwh:,.1f} kWh")
    print(f"PROJECTED FULL-CYCLE BILL: {money(projection.projected_bill.total)}")
    return 0


def cmd_mymeter_download(args: argparse.Namespace) -> int:
    session = MyMeterSession(args.base_url, args.storage_state)
    replay = with_overrides(load_replay_request(args.request), args.start, args.end, args.use_captured_token)
    out = session.download(replay, args.output)
    print(f"Downloaded {out}")
    return 0


def cmd_mymeter_browser_download(args: argparse.Namespace) -> int:
    if args.env_file:
        load_env_file(args.env_file)
    username = os.getenv(args.username_env)
    password = os.getenv(args.password_env)
    if bool(username) != bool(password):
        raise ValueError(f"set both {args.username_env} and {args.password_env}, or neither")
    session = MyMeterBrowserSession(args.base_url, args.user_data_dir, headless=not args.headed)
    replay = with_overrides(load_replay_request(args.request), args.start, args.end, args.use_captured_token)
    out = session.download(
        replay,
        args.output,
        context_path=args.context_path,
        username=username,
        password=password,
    )
    print(f"Downloaded {out}")
    return 0


def _read_login_env(args: argparse.Namespace) -> tuple[str, str]:
    if args.env_file:
        load_env_file(args.env_file)
    username = os.getenv(args.username_env)
    password = os.getenv(args.password_env)
    if not username or not password:
        raise ValueError(f"set {args.username_env} and {args.password_env}")
    return username, password


def cmd_mymeter_login_check(args: argparse.Namespace) -> int:
    username, password = _read_login_env(args)
    session = MyMeterCredentialSession(args.base_url)
    session.login(username, password)
    print("Login succeeded and dashboard was reachable.")
    return 0


def cmd_mymeter_login_download(args: argparse.Namespace) -> int:
    username, password = _read_login_env(args)
    session = MyMeterCredentialSession(args.base_url)
    session.login(username, password)
    replay = with_overrides(load_replay_request(args.request), args.start, args.end, args.use_captured_token)
    out = session.download(replay, args.output)
    print(f"Downloaded {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="electricity-monitor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    bill = sub.add_parser("bill", help="Compute a bill from aggregate peak/off-peak kWh")
    bill.add_argument("--provider", default="psegliny-rate194")
    bill.add_argument("--days", type=int, required=True)
    bill.add_argument("--peak-kwh", type=float, required=True)
    bill.add_argument("--offpeak-kwh", type=float, required=True)
    bill.set_defaults(func=cmd_bill)

    report = sub.add_parser("report", help="Compute observed and projected bill from interval data")
    report.add_argument("--provider", default="psegliny-rate194")
    report.add_argument("--csv")
    report.add_argument("--green-button")
    report.add_argument("--interval-minutes", type=int, default=60)
    report.add_argument("--cycle-start", required=True)
    report.add_argument("--cycle-end", required=True)
    report.add_argument("--as-of")
    report.add_argument("--tz", default="America/New_York")
    report.add_argument("--format", choices=("detail", "summary"), default="detail")
    report.add_argument("--last-cycle-bill", type=float)
    report.add_argument("--last-cycle-usage-kwh", type=float)
    report.add_argument("--last-cycle-peak-kwh", type=float)
    report.add_argument("--last-cycle-offpeak-kwh", type=float)
    report.add_argument("--pricing-changed")
    report.add_argument("--anomalies")
    report.add_argument("--cost-basis")
    report.set_defaults(func=cmd_report)

    mymeter = sub.add_parser("mymeter-download", help="Replay an authenticated MyMeter export request")
    add_mymeter_download_args(mymeter)
    mymeter.set_defaults(func=cmd_mymeter_download)

    browser_download = sub.add_parser(
        "mymeter-browser-download",
        help="Replay a MyMeter export request from inside a persistent browser profile",
    )
    add_mymeter_browser_download_args(browser_download)
    browser_download.set_defaults(func=cmd_mymeter_browser_download)

    login_check = sub.add_parser("mymeter-login-check", help="Try direct MyMeter username/password login")
    add_mymeter_login_args(login_check)
    login_check.set_defaults(func=cmd_mymeter_login_check)

    login_download = sub.add_parser("mymeter-login-download", help="Login with username/password, then replay an export request")
    add_mymeter_login_args(login_download)
    login_download.add_argument("--request", required=True, help="JSON replay request describing the export endpoint")
    login_download.add_argument("--output", required=True)
    login_download.add_argument("--start", help="Override export form Start date, YYYY-MM-DD")
    login_download.add_argument("--end", help="Override export form End date, YYYY-MM-DD")
    login_download.add_argument("--use-captured-token", action="store_true", help="Do not refresh __RequestVerificationToken before replay")
    login_download.set_defaults(func=cmd_mymeter_login_download)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
