"""Synchronous client for the private MyFastweb Power Control API."""

from __future__ import annotations

from datetime import date, datetime
import json
import re
from threading import RLock
import uuid
from html.parser import HTMLParser
from http.cookiejar import Cookie, CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

DASHBOARD_URL = "https://fastweb.it/myfastweb/abbonamento/consumi-power-control/"
AJAX_URL = DASHBOARD_URL + "ajax/"
LED_SETTINGS_URL = (
    "https://fastweb.it/myfastweb/abbonamento/gestione-led-e-avvisi-power-control/"
)
LED_AJAX_URL = LED_SETTINGS_URL + "ajax/"
NOTIFY_SETTINGS_URL = DASHBOARD_URL + "impostazioni/notifiche/"
NOTIFY_AJAX_URL = DASHBOARD_URL + "impostazioni/ajax/"
LOGIN_URL = "https://fastweb.it/myfastweb/accesso/login/"
LOGIN_AJAX_URL = LOGIN_URL + "ajax/"
SET_RM_URL = "https://www.fastweb.it/myfastweb/redirect/set-rm/"
SET_MT_URL = "https://fastweb.it/myfastweb/redirect/set-mt/"
USER_AGENT = "Mozilla/5.0 FastwebPowerControlHA/0.2"
AUTH_COOKIE_NAMES = (
    "FWB_RM",
    "PHPSESSID",
    "fastwebit_cp",
    "FW_TAN",
    "FW_TRK_MYFP_CTYPE",
    "wasin",
    "CF2fe8fec1",
    "CF2f3420af",
)
LED_FIELDS = {
    "led_all": "notify_led_all",
    "led_meter": "notify_led_1",
    "led_internet": "notify_led_2",
    "buzzer": "notify_buzz",
}
NOTIFY_BOOL_FIELDS = {
    "power_limit": "contracted_power_limit_exceeded",
    "provider_disconnection": "provider_disconnection",
    "monthly_budget": "monthly_energy_budget",
    "holiday_mode": "holiday_mode",
}


class FastwebError(RuntimeError):
    """A readable Fastweb request error."""


class AuthenticationRequired(FastwebError):
    """The current Fastweb session is not authenticated."""


class InvalidAuth(FastwebError):
    """The supplied credentials cannot establish a Fastweb session."""


class _TokenParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and values.get("name") == "securityToken":
            self.token = values.get("value") or self.token


class _FormParser(HTMLParser):
    def __init__(self, form_id: str) -> None:
        super().__init__()
        self.form_id = form_id
        self.in_form = False
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and values.get("id") == self.form_id:
            self.in_form = True
        elif tag == "input" and self.in_form and values.get("name"):
            self.fields[values["name"]] = values.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self.in_form:
            self.in_form = False


def extract_security_token(page: str) -> str:
    parser = _TokenParser()
    parser.feed(page)
    token = parser.token
    if not token:
        match = re.search(r"securityToken\s*=\s*['\"]([0-9a-fA-F]{64})", page)
        token = match.group(1) if match else None
    if not token:
        raise FastwebError("securityToken not found: the Fastweb page has changed")
    return token


def extract_form_fields(page: str, form_id: str) -> dict[str, str]:
    parser = _FormParser(form_id)
    parser.feed(page)
    if "securityToken" not in parser.fields:
        raise FastwebError(f"unrecognized Fastweb form: {form_id}")
    return parser.fields


def encode_multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = "----FastwebPowerControl" + uuid.uuid4().hex
    parts: list[str] = []
    for name, value in fields.items():
        parts.extend(
            (f"--{boundary}", f'Content-Disposition: form-data; name="{name}"', "", value)
        )
    parts.extend((f"--{boundary}--", ""))
    return "\r\n".join(parts).encode(), f"multipart/form-data; boundary={boundary}"


def parse_cookie_header(header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in header.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            cookies[name] = value
    return cookies


def _portal_date(value: date | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError as error:
        raise FastwebError("invalid holiday date") from error


def _iso_date(value: str) -> str | None:
    if not value or value in {"01/01/2020", "31/12/2020"}:
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y").date().isoformat()
    except ValueError as error:
        raise FastwebError("invalid holiday date returned by Fastweb") from error


def _make_cookie(name: str, value: str) -> Cookie:
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain="fastweb.it",
        domain_specified=False,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
    )


class FastwebClient:
    """Keep one authenticated, thread-safe Fastweb session."""

    def __init__(self, username: str = "", password: str = "", cookie: str = "") -> None:
        self.username = username
        self.password = password
        self.jar = CookieJar()
        self._lock = RLock()
        self._token: str | None = None
        for name, value in parse_cookie_header(cookie).items():
            if name in AUTH_COOKIE_NAMES:
                self.jar.set_cookie(_make_cookie(name, value))
        self.opener = build_opener(HTTPCookieProcessor(self.jar))

    @property
    def cookie_header(self) -> str:
        with self._lock:
            cookies = {
                cookie.name: cookie.value
                for cookie in self.jar
                if cookie.domain.lstrip(".") == "fastweb.it"
                and cookie.name in AUTH_COOKIE_NAMES
                and not cookie.is_expired()
            }
            return "; ".join(
                f"{name}={cookies[name]}" for name in AUTH_COOKIE_NAMES if name in cookies
            )

    def _open(self, request: Request, timeout: float):
        try:
            return self.opener.open(request, timeout=timeout)
        except HTTPError as error:
            if error.code in {401, 403}:
                raise AuthenticationRequired("Fastweb session expired") from error
            raise FastwebError(f"Fastweb returned HTTP {error.code}") from error
        except URLError as error:
            raise FastwebError(f"Fastweb connection failed: {error.reason}") from error

    def _load_page(self, url: str, timeout: float) -> str:
        with self._open(Request(url, headers={"User-Agent": USER_AGENT}), timeout) as response:
            final_url = response.geturl()
            page = response.read().decode(response.headers.get_content_charset() or "utf-8")
        if "/accesso/" in final_url or "/contenuti-riservati/" in final_url:
            raise AuthenticationRequired("Fastweb session expired")
        return page

    def _authenticated_page(self, url: str, timeout: float) -> str:
        try:
            return self._load_page(url, timeout)
        except AuthenticationRequired:
            self._token = None
            self._login(timeout)
            return self._load_page(url, timeout)

    def _login(self, timeout: float) -> None:
        if not self.username or not self.password:
            raise InvalidAuth("missing Fastweb credentials")

        with self._open(Request(LOGIN_URL, headers={"User-Agent": USER_AGENT}), timeout) as response:
            page = response.read().decode(response.headers.get_content_charset() or "utf-8")
        fields = extract_form_fields(page, "formLogin")
        fields.update(
            {
                "username": self.username,
                "password": self.password,
                "PersistentLogin": "true",
                "g-recaptcha-response-unified": "",
            }
        )
        request = Request(
            LOGIN_AJAX_URL,
            data=urlencode(fields).encode(),
            method="POST",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://fastweb.it",
                "Referer": LOGIN_URL,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        with self._open(request, timeout) as response:
            raw = response.read().decode(response.headers.get_content_charset() or "utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise InvalidAuth("unexpected Fastweb login response") from error
        if payload.get("errorCode") != 0:
            if payload.get("needRecaptcha"):
                # ponytail: CAPTCHA bypass is not a valid automation path.
                raise InvalidAuth("Fastweb requires reCAPTCHA; automatic login stopped")
            raise InvalidAuth(payload.get("errorMessage") or "Fastweb login failed")

        for enabled, url in ((payload.get("rm"), SET_RM_URL), (payload.get("mt"), SET_MT_URL)):
            if enabled:
                with self._open(Request(url, headers={"User-Agent": USER_AGENT}), timeout) as response:
                    response.read()
        if payload.get("redirectURI"):
            url = urljoin(LOGIN_URL, payload["redirectURI"])
            with self._open(Request(url, headers={"User-Agent": USER_AGENT}), timeout) as response:
                response.read()

    def _post_json(
        self, url: str, referer: str, fields: dict[str, str], timeout: float
    ) -> dict:
        body, content_type = encode_multipart(fields)
        request = Request(
            url,
            data=body,
            method="POST",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": content_type,
                "Referer": referer,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        with self._open(request, timeout) as response:
            final_url = response.geturl()
            raw = response.read().decode(response.headers.get_content_charset() or "utf-8")
        if "/accesso/" in final_url or "/contenuti-riservati/" in final_url:
            raise AuthenticationRequired("Fastweb session expired while writing data")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise FastwebError("unexpected Fastweb response") from error
        if payload.get("errorCode") != 0:
            raise FastwebError(payload.get("errorMessage") or "Fastweb rejected the request")
        return payload

    def _form(self, url: str, timeout: float) -> dict[str, str]:
        page = self._authenticated_page(url, timeout)
        self._token = extract_security_token(page)
        return extract_form_fields(page, "request_form")

    def get_realtime(self, timeout: float = 15) -> dict:
        """Return realtime consumption, reusing the page token while valid."""
        with self._lock:
            if self._token is None:
                page = self._authenticated_page(DASHBOARD_URL, timeout)
                self._token = extract_security_token(page)
            try:
                payload = self._post_json(
                    AJAX_URL,
                    DASHBOARD_URL,
                    {"securityToken": self._token, "action": "consumptionRealtime"},
                    timeout,
                )
            except AuthenticationRequired:
                self._token = None
                self._login(timeout)
                page = self._load_page(DASHBOARD_URL, timeout)
                self._token = extract_security_token(page)
                payload = self._post_json(
                    AJAX_URL,
                    DASHBOARD_URL,
                    {"securityToken": self._token, "action": "consumptionRealtime"},
                    timeout,
                )
            try:
                realtime = payload["data"]["realtime"]
            except (KeyError, TypeError) as error:
                raise FastwebError("unexpected Fastweb realtime response") from error
            if not isinstance(realtime, (int, float)):
                raise FastwebError("invalid Fastweb realtime response")
            payload["data"].pop("realtime_sin", None)
            return payload

    def _led_settings(self, fields: dict[str, str]) -> dict[str, bool]:
        return {key: fields.get(field) == "Y" for key, field in LED_FIELDS.items()}

    def _notification_settings(self, fields: dict[str, str]) -> dict:
        return {
            **{
                key: fields.get(field) == "Y"
                for key, field in NOTIFY_BOOL_FIELDS.items()
            },
            "monthly_threshold": float(fields.get("monthly_energy_threshold") or 0),
            "holiday_from": _iso_date(fields.get("holiday_mode_from", "")),
            "holiday_to": _iso_date(fields.get("holiday_mode_to", "")),
        }

    def get_settings(self, timeout: float = 15) -> dict:
        """Read all settings exposed by the Fastweb portal."""
        with self._lock:
            led = self._led_settings(self._form(LED_SETTINGS_URL, timeout))
            notifications = self._notification_settings(
                self._form(NOTIFY_SETTINGS_URL, timeout)
            )
            return {"led": led, "notifications": notifications}

    def update_led_settings(self, changes: dict, timeout: float = 15) -> dict:
        """Update LED/buzzer values while preserving the other portal settings."""
        with self._lock:
            current = self._led_settings(self._form(LED_SETTINGS_URL, timeout))
            for key, value in changes.items():
                if key not in LED_FIELDS or not isinstance(value, bool):
                    raise FastwebError(f"invalid LED setting: {key}")
                current[key] = value
            if "led_all" in changes:
                current["led_meter"] = current["led_all"]
                current["led_internet"] = current["led_all"]
            elif "led_meter" in changes or "led_internet" in changes:
                current["led_all"] = current["led_meter"] and current["led_internet"]

            fields = {"securityToken": self._token or "", "action": "settings_led"}
            fields.update(
                {field: "Y" if current[key] else "N" for key, field in LED_FIELDS.items()}
            )
            self._post_json(LED_AJAX_URL, LED_SETTINGS_URL, fields, timeout)
            return current

    def update_notification_settings(self, changes: dict, timeout: float = 15) -> dict:
        """Update notification values while preserving the rest of the form."""
        with self._lock:
            current = self._notification_settings(
                self._form(NOTIFY_SETTINGS_URL, timeout)
            )
            for key, value in changes.items():
                if key in NOTIFY_BOOL_FIELDS and isinstance(value, bool):
                    current[key] = value
                elif key == "monthly_threshold" and isinstance(value, (int, float)):
                    if value <= 0:
                        raise FastwebError("monthly threshold must be greater than zero")
                    current[key] = value
                elif key in {"holiday_from", "holiday_to"}:
                    current[key] = value.isoformat() if isinstance(value, date) else value
                    _portal_date(current[key])
                else:
                    raise FastwebError(f"invalid notification setting: {key}")

            if changes.get("holiday_mode") is False:
                current["holiday_from"] = current["holiday_to"] = None
            if current["monthly_budget"] and current["monthly_threshold"] <= 0:
                raise FastwebError("monthly threshold must be greater than zero")
            if current["holiday_mode"]:
                start = current["holiday_from"]
                end = current["holiday_to"]
                if not start or not end or date.fromisoformat(start) > date.fromisoformat(end):
                    raise FastwebError("set a valid holiday date range before enabling holiday mode")

            enabled = [current[key] for key in NOTIFY_BOOL_FIELDS]
            fields = {
                "securityToken": self._token or "",
                "action": "settings_notify",
                "all": "Y" if all(enabled) else "N",
                **{
                    field: "Y" if current[key] else "N"
                    for key, field in NOTIFY_BOOL_FIELDS.items()
                },
                "monthly_energy_threshold": f"{current['monthly_threshold']:g}",
                "holiday_mode_from": _portal_date(current["holiday_from"]),
                "holiday_mode_to": _portal_date(current["holiday_to"]),
            }
            self._post_json(NOTIFY_AJAX_URL, NOTIFY_SETTINGS_URL, fields, timeout)
            return current


def self_check() -> None:
    token = "a" * 64
    assert extract_security_token(f'<input value="{token}" name="securityToken">') == token
    assert extract_security_token(f'<script>securityToken="{token}";</script>') == token
    fields = extract_form_fields(
        f'<form id="request_form"><input name="securityToken" value="{token}">'
        '<input name="notify_led_all" value="Y"></form>',
        "request_form",
    )
    assert fields["notify_led_all"] == "Y"
    body, content_type = encode_multipart({"action": "consumptionRealtime"})
    assert b"consumptionRealtime" in body and "boundary=" in content_type
    assert parse_cookie_header("a=1; b=2") == {"a": "1", "b": "2"}
    assert _portal_date("2026-07-13") == "13/07/2026"
    assert _iso_date("13/07/2026") == "2026-07-13"
