"""Synchronous client for the private MyFastweb Power Control API."""

from __future__ import annotations

from datetime import date, datetime
from html.parser import HTMLParser
from http.cookiejar import Cookie, CookieJar
import json
import logging
import math
from pathlib import Path
import re
from threading import RLock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener
import uuid

LOGGER = logging.getLogger(__name__)

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

def _manifest_version() -> str:
    try:
        manifest = json.loads(
            Path(__file__).with_name("manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return "dev"
    return str(manifest.get("version", "dev"))


USER_AGENT = f"Mozilla/5.0 FastwebPowerControlHA/{_manifest_version()}"
# MyFastweb sets cookies on both hosts; the www handshake may issue host-only ones.
COOKIE_DOMAINS = ("fastweb.it", "www.fastweb.it")
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
HISTORY_WEEK = "last-seven-days"
HISTORY_MONTH = "last-thirty-days"
NOTIFICATION_FIELDS = ("id", "type", "title", "message", "created_at", "read")
# The portal fills unset holiday dates with these placeholders.
PORTAL_EMPTY_DATES = frozenset({"01/01/2020", "31/12/2020"})


class FastwebError(RuntimeError):
    """A readable Fastweb request error."""


class AuthenticationRequired(FastwebError):
    """The current Fastweb session is not authenticated."""


class InvalidAuth(FastwebError):
    """The supplied credentials cannot establish a Fastweb session."""


class RecaptchaRequired(InvalidAuth):
    """Fastweb wants a reCAPTCHA, so only a browser session cookie can help."""


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
    if header.lower().startswith("cookie:"):
        header = header.split(":", 1)[1].strip()
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
    if not value or value in PORTAL_EMPTY_DATES:
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y").date().isoformat()
    except ValueError as error:
        raise FastwebError("invalid holiday date returned by Fastweb") from error


def _parse_latest(data: dict) -> list[dict]:
    latest = data.get("latest")
    if not isinstance(latest, dict):
        raise FastwebError("invalid Fastweb recent consumption response")
    samples: dict[str, float] = {}
    for fallback_time, sample in latest.items():
        if not isinstance(sample, dict):
            continue
        timestamp = sample.get("time") or fallback_time
        power = sample.get("power")
        if not isinstance(timestamp, str) or not isinstance(power, (int, float)):
            continue
        try:
            normalized = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        samples[normalized.isoformat()] = max(0.0, float(power))
    if not samples:
        raise FastwebError("Fastweb returned no recent consumption samples")
    return [{"time": key, "power": samples[key]} for key in sorted(samples)]


def _parse_notifications(items: object) -> list[dict]:
    """Keep the portal notification fields, oldest first; skip malformed items."""
    if not isinstance(items, list):
        return []
    notifications = [
        {key: item.get(key) for key in NOTIFICATION_FIELDS}
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("created_at"), str)
    ]
    return sorted(notifications, key=lambda item: item["created_at"])


def _frame_rows(frame: object) -> list[dict[str, float]]:
    """Turn a pandas-style ``{index, columns, data}`` frame into one dict per row."""
    if not isinstance(frame, dict):
        raise FastwebError("invalid Fastweb consumption history response")
    columns, rows = frame.get("columns"), frame.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise FastwebError("invalid Fastweb consumption history response")
    return [
        {
            str(column): max(0.0, float(value)) / 1000
            for column, value in zip(columns, row, strict=False)
            if isinstance(value, (int, float))
        }
        for row in rows
        if isinstance(row, list)
    ]


def _parse_history(data: dict) -> dict:
    """Normalize ``consumptionOwnMedium`` (values in Wh) to kWh."""
    medium = data.get("medium_o")
    totals = data.get("totals")
    if not isinstance(medium, dict) or not isinstance(totals, dict):
        raise FastwebError("invalid Fastweb consumption history response")
    total = medium.get("total_consumption") or {}
    categories = _frame_rows(medium.get("electricity_data"))
    breakdown = (medium.get("daily_breakdown") or {}).get("selected_period")
    daily_categories = _frame_rows(breakdown) if breakdown else []
    period = totals.get("period")
    if isinstance(period, list):
        days = [
            {"day": item["day"], "energy": max(0.0, float(item["total"])) / 1000}
            for item in period
            if isinstance(item, dict)
            and isinstance(item.get("day"), str)
            and isinstance(item.get("total"), (int, float))
        ]
    else:
        # Thirty-day responses total by week; daily values come from the breakdown.
        index = breakdown.get("index") if isinstance(breakdown, dict) else None
        days = [
            {"day": str(day)[:10], "energy": sum(row.values())}
            for day, row in zip(index or [], daily_categories, strict=False)
        ]
    if not days or not isinstance(total.get("selected_period"), (int, float)):
        raise FastwebError("Fastweb returned no consumption history")
    previous = total.get("previous_period")
    return {
        "period_energy": max(0.0, float(total["selected_period"])) / 1000,
        "previous_period_energy": (
            max(0.0, float(previous)) / 1000 if isinstance(previous, (int, float)) else None
        ),
        "days": days,
        "categories": categories[0] if categories else {},
        "last_day_categories": daily_categories[-1] if daily_categories else {},
    }


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
        # ``build_opener`` creates an SSL context and loads system certificates.
        # Keep that blocking work out of Home Assistant's event loop; callers
        # invoke the synchronous request methods in the executor.
        self._opener = None
        for name, value in parse_cookie_header(cookie).items():
            if name in AUTH_COOKIE_NAMES:
                self.jar.set_cookie(_make_cookie(name, value))

    @property
    def cookie_header(self) -> str:
        with self._lock:
            cookies = {
                cookie.name: cookie.value
                for cookie in self.jar
                if cookie.domain.lstrip(".") in COOKIE_DOMAINS
                and cookie.name in AUTH_COOKIE_NAMES
                and not cookie.is_expired()
            }
            return "; ".join(
                f"{name}={cookies[name]}" for name in AUTH_COOKIE_NAMES if name in cookies
            )

    def _open(self, request: Request, timeout: float):
        if self._opener is None:
            self._opener = build_opener(HTTPCookieProcessor(self.jar))
        started = monotonic()
        try:
            response = self._opener.open(request, timeout=timeout)
            LOGGER.debug(
                "Fastweb HTTP %s %s %s completed in %.2fs (status %s)",
                request.get_method(),
                urlsplit(request.full_url).hostname,
                urlsplit(request.full_url).path,
                monotonic() - started,
                response.status,
            )
            return response
        except HTTPError as error:
            LOGGER.warning(
                "Fastweb HTTP %s %s %s returned %s after %.2fs",
                request.get_method(),
                urlsplit(request.full_url).hostname,
                urlsplit(request.full_url).path,
                error.code,
                monotonic() - started,
            )
            if error.code in {401, 403}:
                raise AuthenticationRequired("Fastweb session expired") from error
            if error.code in {301, 302, 303, 307, 308}:
                location = error.headers.get("Location", "")
                source = urlsplit(error.geturl()).path
                destination = urlsplit(urljoin(error.geturl(), location)).path if location else ""
                if any(
                    marker in path
                    for path in (source, destination)
                    for marker in ("/accesso/", "/contenuti-riservati/")
                ):
                    raise AuthenticationRequired("Fastweb redirected to login") from error
                original = urlsplit(request.full_url).path
                raise FastwebError(
                    f"Fastweb returned HTTP {error.code} while requesting "
                    f"{request.get_method()} {original} (redirect {source} to {destination})"
                ) from error
            raise FastwebError(f"Fastweb returned HTTP {error.code}") from error
        except URLError as error:
            LOGGER.warning(
                "Fastweb HTTP %s %s %s failed after %.2fs (%s)",
                request.get_method(),
                urlsplit(request.full_url).hostname,
                urlsplit(request.full_url).path,
                monotonic() - started,
                type(error.reason).__name__,
            )
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
            # Stale portal cookies can override the session established by a
            # successful login and trigger an endless /accesso/ redirect.
            # Start reauthentication with a fresh cookie jar; the opener keeps
            # using this same jar and collects the new Set-Cookie headers.
            self.jar.clear()
            self._login(timeout)
            try:
                return self._load_page(url, timeout)
            except AuthenticationRequired as error:
                # Fastweb sometimes creates the renewable session cookie on
                # www.fastweb.it before its non-www portal recognizes the login.
                # Visiting the same page through www completes that handshake.
                www_url = url.replace("https://fastweb.it/", "https://www.fastweb.it/", 1)
                if www_url != url:
                    try:
                        return self._load_page(www_url, timeout)
                    except AuthenticationRequired:
                        pass
                raise InvalidAuth(
                    "Fastweb did not establish an authenticated session"
                ) from error

    def _login(self, timeout: float) -> None:
        if not self.username or not self.password:
            raise InvalidAuth("missing Fastweb credentials")

        try:
            with self._open(
                Request(LOGIN_URL, headers={"User-Agent": USER_AGENT}), timeout
            ) as response:
                page = response.read().decode(
                    response.headers.get_content_charset() or "utf-8"
                )
        except AuthenticationRequired as error:
            raise InvalidAuth("Fastweb rejected the login page request") from error
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
        try:
            with self._open(request, timeout) as response:
                raw = response.read().decode(
                    response.headers.get_content_charset() or "utf-8"
                )
        except AuthenticationRequired as error:
            raise InvalidAuth("Fastweb rejected the login request") from error
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise InvalidAuth("unexpected Fastweb login response") from error
        if payload.get("errorCode") != 0:
            if payload.get("needRecaptcha"):
                # ponytail: CAPTCHA bypass is not a valid automation path.
                raise RecaptchaRequired(
                    "Fastweb requires reCAPTCHA; automatic login stopped"
                )
            raise InvalidAuth(payload.get("errorMessage") or "Fastweb login failed")

        for enabled, url in ((payload.get("rm"), SET_RM_URL), (payload.get("mt"), SET_MT_URL)):
            if enabled:
                try:
                    with self._open(
                        Request(
                            url,
                            headers={"User-Agent": USER_AGENT, "Referer": LOGIN_URL},
                        ),
                        timeout,
                    ) as response:
                        response.read()
                except AuthenticationRequired as error:
                    raise InvalidAuth("Fastweb rejected a post-login redirect") from error
        if payload.get("redirectURI"):
            url = urljoin(LOGIN_URL, payload["redirectURI"])
            try:
                with self._open(
                    Request(
                        url,
                        headers={"User-Agent": USER_AGENT, "Referer": LOGIN_URL},
                    ),
                    timeout,
                ) as response:
                    response.read()
            except AuthenticationRequired as error:
                raise InvalidAuth("Fastweb rejected the post-login redirect") from error

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

    def _submit_form(
        self, page_url: str, ajax_url: str, fields: dict[str, str], timeout: float
    ) -> dict:
        """Post a settings form, reloading the page token once if the session expired."""
        try:
            return self._post_json(ajax_url, page_url, fields, timeout)
        except AuthenticationRequired:
            self._form(page_url, timeout)
            fields["securityToken"] = self._token or ""
            return self._post_json(ajax_url, page_url, fields, timeout)

    def _dashboard_action(
        self, action: str, extra: dict[str, str] | None = None, timeout: float = 15
    ) -> dict:
        """Call one dashboard action and renew an expired session once."""
        if self._token is None:
            page = self._authenticated_page(DASHBOARD_URL, timeout)
            self._token = extract_security_token(page)
        fields = {"securityToken": self._token, "action": action, **(extra or {})}
        try:
            return self._post_json(AJAX_URL, DASHBOARD_URL, fields, timeout)
        except AuthenticationRequired:
            self._token = None
            page = self._authenticated_page(DASHBOARD_URL, timeout)
            self._token = extract_security_token(page)
            fields["securityToken"] = self._token
            return self._post_json(AJAX_URL, DASHBOARD_URL, fields, timeout)

    def _form(self, url: str, timeout: float) -> dict[str, str]:
        page = self._authenticated_page(url, timeout)
        self._token = extract_security_token(page)
        return extract_form_fields(page, "request_form")

    def get_realtime(self, timeout: float = 15) -> dict:
        """Return realtime consumption, reusing the page token while valid."""
        with self._lock:
            payload = self._dashboard_action("consumptionRealtime", timeout=timeout)
            try:
                realtime = payload["data"]["realtime"]
            except (KeyError, TypeError) as error:
                raise FastwebError("unexpected Fastweb realtime response") from error
            if (
                isinstance(realtime, bool)
                or not isinstance(realtime, (int, float))
                or not math.isfinite(realtime)
                or realtime < 0
            ):
                raise FastwebError("invalid Fastweb realtime response")
            payload["data"].pop("realtime_sin", None)
            return payload

    def get_status(self, timeout: float = 15) -> dict:
        """Return plug connectivity and unread portal notifications."""
        with self._lock:
            status_data = self._dashboard_action("plugStatus", timeout=timeout).get(
                "data", {}
            )
            notify_data = self._dashboard_action(
                "loadNotify", {"notificationId": ""}, timeout
            ).get("data", {})
            status = status_data.get("status")
            unread = notify_data.get("unread")
            if not isinstance(status, str) or not isinstance(unread, int):
                raise FastwebError("invalid Fastweb status response")
            return {
                "plug_status": status,
                "plug_online": status.upper() == "ONLINE",
                "notifications_unread": max(0, unread),
                "notifications": _parse_notifications(notify_data.get("notifications")),
            }

    def get_latest(self, timeout: float = 15) -> list[dict]:
        """Return recent power samples used to backfill cumulative energy."""
        with self._lock:
            payload = self._dashboard_action("consumptionLatest", timeout=timeout)
            return _parse_latest(payload.get("data") or {})

    def _history(self, period: str, timeout: float) -> dict:
        payload = self._dashboard_action(
            "consumptionOwnMedium", {"period": period, "includePrevious": "1"}, timeout
        )
        return _parse_history(payload.get("data") or {})

    def get_history(self, timeout: float = 15) -> dict:
        """Return the last seven days, with the last thirty under ``month``."""
        with self._lock:
            history = self._history(HISTORY_WEEK, timeout)
            try:
                history["month"] = self._history(HISTORY_MONTH, timeout)
            except InvalidAuth:
                raise
            except FastwebError:
                # The weekly data is still useful when the monthly view fails.
                history["month"] = None
            return history

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
            self._submit_form(LED_SETTINGS_URL, LED_AJAX_URL, fields, timeout)
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
                    raise FastwebError(
                        "set a valid holiday date range before enabling holiday mode"
                    )

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
            self._submit_form(NOTIFY_SETTINGS_URL, NOTIFY_AJAX_URL, fields, timeout)
            return current

