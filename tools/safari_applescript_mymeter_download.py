#!/usr/bin/env python3
"""Download MyMeter usage from the current Safari session.

This helper runs JavaScript in Safari via Apple Events. It assumes the user has
already logged into the portal in a normal Safari window.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.parse
from pathlib import Path

from electricity_monitor.mymeter import _write_download_body, load_replay_request, with_overrides


def absolute_url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path)


def safari_javascript(script: str) -> str:
    completed = subprocess.run(
        [
            "osascript",
            "-e",
            f'tell application "Safari" to do JavaScript {json.dumps(script)} in current tab of front window',
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Safari JavaScript failed: {detail}")
    return completed.stdout


def safari_open(url: str) -> None:
    completed = subprocess.run(
        ["osascript", "-e", f'tell application "Safari" to open location {json.dumps(url)}'],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Safari navigation failed: {detail}")


def current_page_status() -> dict:
    raw = safari_javascript(
        """
        JSON.stringify({
          url: location.href,
          title: document.title,
          hasLoginEmail: !!document.querySelector('#LoginEmail'),
          hasToken: !!document.querySelector('input[name="__RequestVerificationToken"]'),
          text: document.body.innerText.slice(0, 500)
        })
        """
    )
    return json.loads(raw)


def wait_for_mysmartenergy_page(seconds: int = 30) -> dict:
    deadline = time.time() + seconds
    latest: dict = {}
    while time.time() < deadline:
        latest = current_page_status()
        if "mysmartenergy.psegliny.com" in str(latest.get("url", "")):
            if latest.get("hasLoginEmail") or latest.get("hasToken"):
                return latest
        time.sleep(1)
    return latest


def download_csv(base_url: str, replay_url: str, data: dict[str, str]) -> bytes:
    script = f"""
    (() => {{
      const url = {json.dumps(absolute_url(base_url, replay_url))};
      const form = {json.dumps(data)};
      const token = document.querySelector('input[name="__RequestVerificationToken"]')?.value;
      if (token) {{
        form.__RequestVerificationToken = token;
      }}
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url, false);
      xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
      xhr.send(new URLSearchParams(form).toString());
      return JSON.stringify({{
        status: xhr.status,
        contentType: xhr.getResponseHeader('content-type') || '',
        text: xhr.responseText
      }});
    }})()
    """
    raw = safari_javascript(script)
    if not raw.strip():
        raise RuntimeError("Safari returned an empty response from the download script")
    result = json.loads(raw)
    status = int(result.get("status", 0))
    text = str(result.get("text", ""))
    if status >= 400 or status == 0:
        raise RuntimeError(f"download HTTP error {status}: {text[:500]}")
    return text.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--context-path", default="/Dashboard/")
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()

    safari_open(absolute_url(args.base_url, args.context_path))
    status = wait_for_mysmartenergy_page()
    if status.get("hasLoginEmail"):
        raise RuntimeError("Safari is on the MySmartEnergy login page; log in normally first")
    if "mysmartenergy.psegliny.com" not in str(status.get("url", "")):
        raise RuntimeError(f"front Safari tab is not MySmartEnergy: {status.get('url')}")

    replay = with_overrides(load_replay_request(args.request), args.start, args.end)
    if replay.method != "POST":
        raise RuntimeError("Safari AppleScript helper currently supports POST replay requests")
    body = download_csv(args.base_url, replay.url, dict(replay.data or {}))
    out = _write_download_body(Path(args.output), body)
    print(f"Downloaded {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
