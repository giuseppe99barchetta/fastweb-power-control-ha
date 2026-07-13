"""Small synchronous client for the private MyFastweb Power Control API."""

from __future__ import annotations

import json
import re
import uuid
from html.parser import HTMLParser
from http.cookiejar import Cookie, CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

DASHBOARD_URL = "https://fastweb.it/myfastweb/abbonamento/consumi-power-control/"
AJAX_URL = DASHBOARD_URL + "ajax/"
LOGIN_URL = "https://fastweb.it/myfastweb/accesso/login/"
LOGIN_AJAX_URL = LOGIN_URL + "ajax/"
SET_RM_URL = "https://www.fastweb.it/myfastweb/redirect/set-rm/"
SET_MT_URL = "https://fastweb.it/myfastweb/redirect/set-mt/"
USER_AGENT = "Mozilla/5.0 FastwebPowerControlHA/1.0"
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


class FastwebError(RuntimeError):
    """A readable Fastweb request error."""


class AuthenticationRequired(FastwebError):
    """The current Fastweb session is not authenticated."""


class _TokenParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and values.get("name") == "securityToken":
            self.token = values.get("value") or self.token


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_login_form = False
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and values.get("id") == "formLogin":
            self.in_login_form = True
        elif tag == "input" and self.in_login_form and values.get("name"):
            self.fields[values["name"]] = values.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.in_login_form = False


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


def extract_login_fields(page: str) -> dict[str, str]:
    parser = _LoginFormParser()
    parser.feed(page)
    if "securityToken" not in parser.fields:
        raise FastwebError("unrecognized Fastweb login form")
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
    """Keep one authenticated Fastweb session and renew its cookies."""

    def __init__(self, username: str = "", password: str = "", cookie: str = "") -> None:
        self.username = username
        self.password = password
        self.jar = CookieJar()
        for name, value in parse_cookie_header(cookie).items():
            if name in AUTH_COOKIE_NAMES:
                self.jar.set_cookie(_make_cookie(name, value))
        self.opener = build_opener(HTTPCookieProcessor(self.jar))

    @property
    def cookie_header(self) -> str:
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
            raise FastwebError(f"Fastweb returned HTTP {error.code}") from error
        except URLError as error:
            raise FastwebError(f"Fastweb connection failed: {error.reason}") from error

    def _load_dashboard(self, timeout: float) -> str:
        with self._open(Request(DASHBOARD_URL, headers={"User-Agent": USER_AGENT}), timeout) as response:
            final_url = response.geturl()
            page = response.read().decode(response.headers.get_content_charset() or "utf-8")
        if "/accesso/" in final_url or "/contenuti-riservati/" in final_url:
            raise AuthenticationRequired("Fastweb session expired")
        return page

    def _login(self, timeout: float) -> None:
        if not self.username or not self.password:
            raise AuthenticationRequired("missing Fastweb credentials")

        with self._open(Request(LOGIN_URL, headers={"User-Agent": USER_AGENT}), timeout) as response:
            page = response.read().decode(response.headers.get_content_charset() or "utf-8")
        fields = extract_login_fields(page)
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
            raise FastwebError("unexpected Fastweb login response") from error
        if payload.get("errorCode") != 0:
            if payload.get("needRecaptcha"):
                # ponytail: CAPTCHA bypass is not a valid automation path.
                raise FastwebError("Fastweb requires reCAPTCHA; automatic login stopped")
            raise FastwebError(payload.get("errorMessage") or "Fastweb login failed")

        for enabled, url in ((payload.get("rm"), SET_RM_URL), (payload.get("mt"), SET_MT_URL)):
            if enabled:
                with self._open(Request(url, headers={"User-Agent": USER_AGENT}), timeout) as response:
                    response.read()
        if payload.get("redirectURI"):
            url = urljoin(LOGIN_URL, payload["redirectURI"])
            with self._open(Request(url, headers={"User-Agent": USER_AGENT}), timeout) as response:
                response.read()

    def get_realtime(self, timeout: float = 15) -> dict:
        """Return the complete Fastweb realtime response."""
        try:
            page = self._load_dashboard(timeout)
        except AuthenticationRequired:
            self._login(timeout)
            page = self._load_dashboard(timeout)

        token = extract_security_token(page)
        body, content_type = encode_multipart(
            {"securityToken": token, "action": "consumptionRealtime"}
        )
        request = Request(
            AJAX_URL,
            data=body,
            method="POST",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": content_type,
                "Referer": DASHBOARD_URL,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        with self._open(request, timeout) as response:
            final_url = response.geturl()
            raw = response.read().decode(response.headers.get_content_charset() or "utf-8")
        if "/accesso/" in final_url or "/contenuti-riservati/" in final_url:
            raise AuthenticationRequired("Fastweb session expired while reading data")
        try:
            payload = json.loads(raw)
            realtime = payload["data"]["realtime"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise FastwebError("unexpected Fastweb response") from error
        if payload.get("errorCode") != 0 or not isinstance(realtime, (int, float)):
            raise FastwebError(payload.get("errorMessage") or "invalid Fastweb response")
        payload["data"].pop("realtime_sin", None)  # Account data is unrelated and sensitive.
        return payload


def self_check() -> None:
    token = "a" * 64
    assert extract_security_token(f'<input value="{token}" name="securityToken">') == token
    assert extract_security_token(f'<script>securityToken="{token}";</script>') == token
    assert extract_login_fields(
        f'<form id="formLogin"><input name="securityToken" value="{token}"></form>'
    )["securityToken"] == token
    body, content_type = encode_multipart({"action": "consumptionRealtime"})
    assert b"consumptionRealtime" in body and "boundary=" in content_type
    assert parse_cookie_header("a=1; b=2") == {"a": "1", "b": "2"}
