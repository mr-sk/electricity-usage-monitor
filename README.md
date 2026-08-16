# electricity-usage-monitor

Open-sourceable tools for computing electricity usage, time-of-use charges, and
billing-cycle projections from interval meter data.

The core package is utility-agnostic. Provider-specific details live in small
provider modules, with PSEG Long Island Rate 194 included as the first example.

## Quick checks

Reproduce a bill from aggregate peak/off-peak usage:

```sh
python -m electricity_monitor bill \
  --provider psegliny-rate194 \
  --days 33 \
  --peak-kwh 335 \
  --offpeak-kwh 2084
```

Generate a cycle report from interval CSV:

```sh
python -m electricity_monitor report \
  --provider psegliny-rate194 \
  --csv data/intervals.csv \
  --cycle-start 2026-06-26 \
  --cycle-end 2026-07-29 \
  --tz America/New_York
```

For automation or chat notifications, use the stable summary format and pass
optional last-cycle comparison values:

```sh
python -m electricity_monitor report \
  --provider psegliny-rate194 \
  --csv data/intervals.csv \
  --cycle-start 2026-07-29 \
  --cycle-end 2026-08-27 \
  --tz America/New_York \
  --format summary \
  --last-cycle-bill 671.29 \
  --last-cycle-usage-kwh 2419 \
  --last-cycle-peak-kwh 335 \
  --last-cycle-offpeak-kwh 2084 \
  --pricing-changed no
```

Supported CSV shapes:

- `start,end,kwh`
- `timestamp,kwh` where each row is an interval start and `--interval-minutes`
  supplies the duration

Green Button XML imports are also supported:

```sh
python -m electricity_monitor report \
  --provider psegliny-rate194 \
  --green-button data/usage.xml \
  --cycle-start 2026-06-26 \
  --cycle-end 2026-07-29
```

## Automated downloads

The package intentionally keeps credentials and browser state outside the repo.
For MyMeter-style portals, first try direct username/password login:

```sh
MYMETER_USERNAME='you@example.com' MYMETER_PASSWORD='your_password_here' \
python -m electricity_monitor mymeter-login-check \
  --base-url https://mysmartenergy.psegliny.com
```

If that succeeds, daily automation can log in and replay a known export request:

```sh
python -m electricity_monitor mymeter-login-download \
  --base-url https://mysmartenergy.psegliny.com \
  --env-file ../agent_tools/electricity/.env \
  --request private/download-request.json \
  --output data/latest.csv
```

If direct login is blocked by reCAPTCHA, MFA, or a secret question, use a saved
authenticated browser session plus a replayable download request. This avoids
committing personal constants or forcing daily manual exports.

First, capture the export endpoint once in a browser session:

```sh
scripts/setup-browser-env.sh
.venv/bin/python tools/record_mymeter_export.py \
  --base-url https://mysmartenergy.psegliny.com \
  --start-url https://www.psegliny.com/myaccount \
  --user-data-dir private/mymeter-browser \
  --storage-state private/mymeter-storage.json \
  --request-out private/download-request.json \
  --downloads data/discovery
```

In the browser that opens, log in normally and click the portal's CSV or Green
Button export once. The recorder saves the authenticated browser state and a
candidate replay request. Daily automation can then run headlessly without a
manual download:

```sh
python -m electricity_monitor mymeter-download \
  --base-url https://mysmartenergy.psegliny.com \
  --storage-state private/mymeter-storage.json \
  --request private/download-request.json \
  --output data/latest.csv
```

`download-request.json` describes the authenticated request to replay:

```json
{
  "method": "GET",
  "url": "/path/to/export.csv",
  "headers": {
    "Accept": "text/csv,*/*"
  }
}
```

If the portal requires a request-verification token, set
`"include_request_verification_token": true`; the downloader will fetch the base
page, extract the first `__RequestVerificationToken`, and include it in form
data for POST requests.

The one-time recorder is deliberately outside the package API because browser
automation is optional and portal-specific. The daily path is the replayable
request plus stored authenticated session.

## Privacy

Do not commit utility account numbers, customer IDs, service addresses,
passwords, cookies, browser storage state, or downloaded bills.
