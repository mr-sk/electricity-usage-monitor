#!/usr/bin/env python3
"""Record a MyMeter export request for later unattended replay.

This is a one-time discovery helper. It opens a real browser so the user can
complete login, MFA, and reCAPTCHA normally. When the user clicks a CSV or Green
Button export, the script records the matching request and saves Playwright
storage state. The daily cron path can then use `electricity-monitor
mymeter-download` with the saved storage state and request JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
from pathlib import Path


KEYWORDS = ("download", "export", "csv", "green", "button", "interval", "usage")


def _filtered_headers(headers: dict[str, str]) -> dict[str, str]:
    drop = {"cookie", "authorization", "content-length", "host", "origin", "referer"}
    return {k: v for k, v in headers.items() if k.lower() not in drop}


def _request_to_replay_dict(request, base_url: str) -> dict:
    url = request.url
    parsed_base = urllib.parse.urlparse(base_url)
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme == parsed_base.scheme and parsed_url.netloc == parsed_base.netloc:
        url_value = urllib.parse.urlunparse(("", "", parsed_url.path, "", parsed_url.query, ""))
    else:
        url_value = url

    data = None
    post_data = request.post_data
    if post_data:
        parsed = urllib.parse.parse_qs(post_data, keep_blank_values=True)
        data = {key: values[-1] if values else "" for key, values in parsed.items()}

    return {
        "method": request.method,
        "url": url_value,
        "headers": _filtered_headers(request.headers),
        "data": data,
        "include_request_verification_token": bool(data and "__RequestVerificationToken" in data),
    }


def looks_like_export(url: str) -> bool:
    lowered = url.lower()
    return any(keyword in lowered for keyword in KEYWORDS)


def load_env_file(path: str | None) -> None:
    if not path:
        return
    env_path = Path(path)
    if not env_path.exists():
        raise SystemExit(f"env file not found: {env_path}")
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def prefill_login(page, username: str | None, password: str | None) -> None:
    if not username or not password:
        return
    try:
        page.locator("#LoginEmail").fill(username, timeout=3000)
        page.locator("#LoginPassword").fill(password, timeout=3000)
        print("[login] prefilled MySmartEnergy username/password; complete captcha/login in browser")
    except Exception:
        print("[login] could not prefill known MySmartEnergy fields; continue manually")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--start-url", help="URL to open for login/navigation; defaults to --base-url")
    parser.add_argument("--env-file", help="Optional .env file containing MYMETER_USERNAME and MYMETER_PASSWORD")
    parser.add_argument("--username-env", default="MYMETER_USERNAME")
    parser.add_argument("--password-env", default="MYMETER_PASSWORD")
    parser.add_argument("--user-data-dir", required=True)
    parser.add_argument("--storage-state", required=True)
    parser.add_argument("--request-out", required=True)
    parser.add_argument("--downloads", required=True)
    args = parser.parse_args()
    load_env_file(args.env_file)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("Install optional browser dependencies: python -m pip install -e '.[browser]'")

    downloads = Path(args.downloads)
    downloads.mkdir(parents=True, exist_ok=True)
    request_out = Path(args.request_out)
    request_out.parent.mkdir(parents=True, exist_ok=True)
    storage_state = Path(args.storage_state)
    storage_state.parent.mkdir(parents=True, exist_ok=True)

    candidates = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            args.user_data_dir,
            headless=False,
            accept_downloads=True,
        )
        page = context.pages[0] if context.pages else context.new_page()

        def on_request(request):
            if looks_like_export(request.url):
                candidates.append(request)
                print(f"[candidate] {request.method} {request.url}")

        def on_download(download):
            target = downloads / download.suggested_filename
            download.save_as(target)
            print(f"[download] saved {target}")
            if candidates:
                replay = _request_to_replay_dict(candidates[-1], args.base_url)
                request_out.write_text(json.dumps(replay, indent=2) + "\n")
                print(f"[request] wrote {request_out}")

        page.on("request", on_request)
        page.on("download", on_download)
        page.goto(args.start_url or args.base_url, wait_until="domcontentloaded")
        prefill_login(page, os.getenv(args.username_env), os.getenv(args.password_env))

        print("")
        print("Log in, navigate to MySmartEnergy usage export, and click CSV or Green Button download once.")
        print("Press Enter here after the download/request has been captured.")
        input()

        context.storage_state(path=str(storage_state))
        print(f"[storage] wrote {storage_state}")
        context.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
