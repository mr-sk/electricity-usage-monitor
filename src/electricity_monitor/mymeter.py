from __future__ import annotations

import argparse
import http.cookiejar
import html.parser
import json
import os
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union


class TokenParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.token: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "input":
            return
        data = dict(attrs)
        if data.get("name") == "__RequestVerificationToken" and data.get("value"):
            self.token = data["value"]


@dataclass(frozen=True)
class ReplayRequest:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    data: Optional[dict[str, str]] = None
    include_request_verification_token: bool = False


def load_replay_request(path: Union[str, Path]) -> ReplayRequest:
    raw = json.loads(Path(path).read_text())
    return ReplayRequest(
        method=str(raw.get("method", "GET")).upper(),
        url=str(raw["url"]),
        headers=dict(raw.get("headers") or {}),
        data=dict(raw["data"]) if raw.get("data") is not None else None,
        include_request_verification_token=bool(raw.get("include_request_verification_token", False)),
    )


def with_overrides(
    replay: ReplayRequest,
    start: Optional[str],
    end: Optional[str],
    use_captured_token: bool = False,
) -> ReplayRequest:
    if not start and not end and not use_captured_token:
        return replay
    data = dict(replay.data or {})
    if start:
        data["Start"] = start
    if end:
        data["End"] = end
    _ensure_usage_columns_selected(data)
    return ReplayRequest(
        method=replay.method,
        url=replay.url,
        headers=dict(replay.headers),
        data=data,
        include_request_verification_token=False if use_captured_token else replay.include_request_verification_token,
    )


def _ensure_usage_columns_selected(data: dict[str, str]) -> None:
    """MyMeter download forms may serialize hidden unchecked column options.

    The useful interval CSV needs at least kWh. kW is also harmless and matches
    the portal's default "Usage.csv" header observed during discovery.
    """
    for index in range(0, 12):
        value_key = f"ColumnOptions[{index}].Value"
        checked_key = f"ColumnOptions[{index}].Checked"
        value = data.get(value_key)
        if value in {"Consumption", "Demand"}:
            data[checked_key] = "true"


def cookie_header_from_playwright_storage(path: Union[str, Path], base_url: str) -> str:
    storage = json.loads(Path(path).read_text())
    host = urllib.parse.urlparse(base_url).hostname or ""
    pairs = []
    for cookie in storage.get("cookies", []):
        domain = str(cookie.get("domain", "")).lstrip(".")
        if domain and not (host == domain or host.endswith("." + domain)):
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if name is not None and value is not None:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _looks_like_login_page(content: str) -> bool:
    lowered = content.lower()
    return 'name="loginpassword"' in lowered or "/home/login" in lowered or "g-recaptcha-response" in lowered


def _looks_like_html(body: bytes) -> bool:
    sample = body[:4096].decode("utf-8", errors="ignore").lstrip().lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html") or "<form" in sample and "/home/login" in sample


def _write_download_body(output: Union[str, Path], body: bytes) -> Path:
    if _looks_like_html(body):
        raise RuntimeError("download returned HTML instead of usage data; authenticated session may have expired")
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    tmp_path.write_bytes(body)
    tmp_path.replace(out_path)
    return out_path


def _browser_fetch_headers(headers: dict[str, str]) -> dict[str, str]:
    forbidden = {
        "authorization",
        "connection",
        "content-length",
        "cookie",
        "host",
        "origin",
        "referer",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "upgrade-insecure-requests",
        "user-agent",
    }
    return {key: value for key, value in headers.items() if key.lower() not in forbidden}


class MyMeterSession:
    def __init__(self, base_url: str, storage_state: Union[str, Path]) -> None:
        self.base_url = base_url.rstrip("/")
        self.storage_state = storage_state

    def _absolute_url(self, url: str) -> str:
        return urllib.parse.urljoin(self.base_url + "/", url)

    def _cookie_header_for_url(self, url: str) -> str:
        cookie_header = cookie_header_from_playwright_storage(self.storage_state, url)
        if not cookie_header:
            raise ValueError(f"no matching cookies found in Playwright storage state for {url}")
        return cookie_header

    def fetch_request_verification_token(self, path: str = "/") -> str:
        url = self._absolute_url(path)
        req = urllib.request.Request(
            url,
            headers={"Cookie": self._cookie_header_for_url(url), "User-Agent": "electricity-usage-monitor/0.1"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        parser = TokenParser()
        parser.feed(body)
        if not parser.token:
            raise RuntimeError("could not find __RequestVerificationToken")
        return parser.token

    def download(self, replay: ReplayRequest, output: Union[str, Path]) -> Path:
        url = self._absolute_url(replay.url)
        headers = {
            "Cookie": self._cookie_header_for_url(url),
            "User-Agent": "electricity-usage-monitor/0.1",
            **replay.headers,
        }
        data = dict(replay.data or {})
        if replay.include_request_verification_token:
            data["__RequestVerificationToken"] = self.fetch_request_verification_token(_token_context_path(replay.url))

        encoded = None
        if replay.method != "GET" or data:
            encoded = urllib.parse.urlencode(data).encode("utf-8")
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

        req = urllib.request.Request(
            url,
            data=encoded,
            headers=headers,
            method=replay.method,
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"download HTTP error {exc.code}: {body}") from exc
        return _write_download_body(output, body)


class MyMeterBrowserSession:
    def __init__(self, base_url: str, user_data_dir: Union[str, Path], headless: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_data_dir = str(user_data_dir)
        self.headless = headless

    def _absolute_url(self, url: str) -> str:
        return urllib.parse.urljoin(self.base_url + "/", url)

    def _login_if_needed(self, page, username: Optional[str], password: Optional[str]) -> None:
        content = page.content()
        if not _looks_like_login_page(content):
            return
        if not username or not password:
            raise RuntimeError("browser profile is not authenticated; refresh the MySmartEnergy session")

        try:
            page.locator("#LoginEmail").fill(username, timeout=5000)
            page.locator("#LoginPassword").fill(password, timeout=5000)
        except Exception as exc:
            raise RuntimeError("browser login form changed; refresh the MySmartEnergy session manually") from exc

        clicked = False
        for selector in (
            "#loginButton",
            "button[type=submit]",
            "input[type=submit]",
            "button:has-text('Log In')",
            "button:has-text('Login')",
        ):
            locator = page.locator(selector).first
            try:
                if locator.count():
                    locator.click(timeout=5000)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            page.locator("#LoginPassword").press("Enter", timeout=5000)

        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        if _looks_like_login_page(page.content()):
            raise RuntimeError("browser login did not complete; captcha, MFA, or login form may need manual refresh")

    def download(
        self,
        replay: ReplayRequest,
        output: Union[str, Path],
        context_path: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Path:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("install optional browser dependencies: python -m pip install -e '.[browser]'")

        url = self._absolute_url(replay.url)
        token_url = self._absolute_url(context_path or _token_context_path(replay.url))
        data = dict(replay.data or {})

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                self.user_data_dir,
                headless=self.headless,
                accept_downloads=True,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(token_url, wait_until="domcontentloaded", timeout=60000)
                self._login_if_needed(page, username, password)
                content = page.content()

                if replay.include_request_verification_token:
                    parser = TokenParser()
                    parser.feed(content)
                    if parser.token:
                        data["__RequestVerificationToken"] = parser.token

                result = page.evaluate(
                    """async ({url, method, headers, data}) => {
                        const fetchHeaders = {...headers};
                        let body = undefined;
                        if (data && Object.keys(data).length) {
                            body = new URLSearchParams(data).toString();
                            fetchHeaders["Content-Type"] = fetchHeaders["Content-Type"] || "application/x-www-form-urlencoded";
                        }
                        const response = await fetch(url, {
                            method,
                            headers: fetchHeaders,
                            body,
                            credentials: "include",
                            redirect: "follow",
                        });
                        return {
                            status: response.status,
                            text: await response.text(),
                        };
                    }""",
                    {
                        "url": url,
                        "method": replay.method,
                        "headers": _browser_fetch_headers(replay.headers),
                        "data": data,
                    },
                )
            finally:
                context.close()

        status = int(result.get("status", 0))
        body = str(result.get("text", "")).encode("utf-8")
        if status >= 400:
            preview = body.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"download HTTP error {status}: {preview}")
        return _write_download_body(output, body)


def _token_context_path(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or "/"
    if path.endswith("/Download"):
        return path.rsplit("/", 1)[0] or "/"
    if "/" in path.strip("/"):
        return path.rsplit("/", 1)[0] or "/"
    return path or "/"


class MyMeterCredentialSession:
    """Small HTTP client for MyMeter username/password login.

    This intentionally does not attempt to bypass reCAPTCHA, MFA, or secret
    question challenges. If the portal requires any of those, login returns a
    clear failure so a browser-backed session can be used instead.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def _absolute_url(self, url: str) -> str:
        return urllib.parse.urljoin(self.base_url + "/", url)

    def _request(self, url: str, data: Optional[dict[str, str]] = None, method: str = "GET") -> tuple[int, str]:
        encoded = None
        headers = {"User-Agent": "electricity-usage-monitor/0.1"}
        if data is not None:
            encoded = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            headers["X-Requested-With"] = "XMLHttpRequest"
        req = urllib.request.Request(self._absolute_url(url), data=encoded, headers=headers, method=method)
        with self.opener.open(req, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")

    def fetch_request_verification_token(self, path: str = "/") -> str:
        _status, body = self._request(path)
        parser = TokenParser()
        parser.feed(body)
        if not parser.token:
            raise RuntimeError("could not find __RequestVerificationToken on login page")
        return parser.token

    def login(self, username: str, password: str, remember_me: bool = True) -> None:
        token = self.fetch_request_verification_token()
        status, body = self._request(
            "/Home/Login",
            data={
                "RedirectUrl": "",
                "LoginErrorMessage": "",
                "LoginEmail": username,
                "LoginPassword": password,
                "ExternalLogin": "False",
                "TwoFactorRendered": "False",
                "SecretQuestionRendered": "False",
                "RememberMe": "true" if remember_me else "false",
                "__RequestVerificationToken": token,
            },
            method="POST",
        )
        if status >= 400:
            raise RuntimeError(f"login HTTP error {status}")

        parsed = None
        if body.strip():
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None

        data = parsed.get("Data") if isinstance(parsed, dict) and "Data" in parsed else parsed
        if isinstance(data, dict):
            if data.get("LoginErrorMessage"):
                raise RuntimeError(f"login rejected: {data['LoginErrorMessage']}")
            if data.get("SecretQuestionError") is not None:
                raise RuntimeError("login requires secret-question flow; use browser session capture")
            if data.get("PasswordExpiredModalData") is not None:
                raise RuntimeError("login requires password-change flow; complete it in browser first")
            if data.get("RecaptchaOnLogin"):
                raise RuntimeError("login requires reCAPTCHA; use browser session capture")

        # A successful AJAX login usually sets authenticated cookies and returns
        # callback actions or an empty success payload. Verify by requesting the
        # dashboard and checking that we do not land back on the login form.
        _dash_status, dash_body = self._request("/Dashboard/")
        lowered = dash_body.lower()
        if 'name="loginpassword"' in lowered or "/home/login" in lowered:
            raise RuntimeError("login did not establish an authenticated dashboard session")

    def download(self, replay: ReplayRequest, output: Union[str, Path]) -> Path:
        data = dict(replay.data or {})
        if replay.include_request_verification_token:
            data["__RequestVerificationToken"] = self.fetch_request_verification_token(_token_context_path(replay.url))
        method = replay.method
        encoded = None
        headers = {
            "User-Agent": "electricity-usage-monitor/0.1",
            **replay.headers,
        }
        if method != "GET" or data:
            encoded = urllib.parse.urlencode(data).encode("utf-8")
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        req = urllib.request.Request(self._absolute_url(replay.url), data=encoded, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=120) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"download HTTP error {exc.code}: {body}") from exc
        return _write_download_body(output, body)


def load_env_file(path: Union[str, Path]) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def add_mymeter_download_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--storage-state", required=True, help="Playwright storage_state JSON with authenticated cookies")
    parser.add_argument("--request", required=True, help="JSON replay request describing the export endpoint")
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", help="Override export form Start date, YYYY-MM-DD")
    parser.add_argument("--end", help="Override export form End date, YYYY-MM-DD")
    parser.add_argument("--use-captured-token", action="store_true", help="Do not refresh __RequestVerificationToken before replay")


def add_mymeter_browser_download_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--user-data-dir", required=True, help="Persistent Playwright browser profile directory")
    parser.add_argument("--request", required=True, help="JSON replay request describing the export endpoint")
    parser.add_argument("--output", required=True)
    parser.add_argument("--context-path", help="Authenticated page to load before replaying the export request")
    parser.add_argument("--env-file", help="Optional .env file containing MYMETER_USERNAME and MYMETER_PASSWORD")
    parser.add_argument("--username-env", default="MYMETER_USERNAME")
    parser.add_argument("--password-env", default="MYMETER_PASSWORD")
    parser.add_argument("--start", help="Override export form Start date, YYYY-MM-DD")
    parser.add_argument("--end", help="Override export form End date, YYYY-MM-DD")
    parser.add_argument("--use-captured-token", action="store_true", help="Do not refresh __RequestVerificationToken before replay")
    parser.add_argument("--headed", action="store_true", help="Show the browser while downloading")


def add_mymeter_login_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--env-file", help="Optional .env file containing MYMETER_USERNAME and MYMETER_PASSWORD")
    parser.add_argument("--username-env", default="MYMETER_USERNAME")
    parser.add_argument("--password-env", default="MYMETER_PASSWORD")
