#!/usr/bin/env bash
# Create a local browser automation environment without touching system Python.
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -e '.[browser]'
.venv/bin/python -m playwright install chromium

echo ""
echo "Ready. Use:"
echo "  .venv/bin/python tools/record_mymeter_export.py --base-url https://mysmartenergy.psegliny.com --start-url https://www.psegliny.com/myaccount --user-data-dir private/mymeter-browser --storage-state private/mymeter-storage.json --request-out private/download-request.json --downloads data/discovery"
