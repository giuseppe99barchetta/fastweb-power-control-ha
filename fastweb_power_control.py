#!/usr/bin/env python3
"""Read the current Fastweb Power Control consumption."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from html.parser import HTMLParser
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

DASHBOARD_URL = "https://fastweb.it/myfastweb/abbonamento/consumi-power-control/"
AJAX_URL = DASHBOARD_URL + "ajax/"
LOGIN_URL = "https://fastweb.it/myfastweb/accesso/login/"
LOGIN_AJAX_URL = LOGIN_URL + "ajax/"
SET_RM_URL = "https://www.fastweb.it/myfastweb/redirect/set-rm/"
SET_MT_URL = "https://fastweb.it/myfastweb/redirect/set-mt/"
USER_AGENT = "Mozilla/5.0 FastwebPowerControlHA/0.1"
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


class _AuthenticationRequired(FastwebError):
    pass


class _TokenParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        values = dict(attrs)
        if values.get("name") == "securityToken" and values.get("value"):
            self.token = values["value"]


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
        if tag == "form" and self.in_login_form:
            self.in_login_form = False


def extract_security_token(page: str) -> str:
    parser = _TokenParser()
    parser.feed(page)
    token = parser.token
    if not token:
        match = re.search(r"securityToken\s*=\s*['\"]([0-9a-fA-F]{64})", page)
        token = match.group(1) if match else None
    if not token:
        raise FastwebError("securityToken non trovato: sessione scaduta o pagina cambiata")
    return token


def extract_login_fields(page: str) -> dict[str, str]:
    parser = _LoginFormParser()
    parser.feed(page)
    if "securityToken" not in parser.fields:
        raise FastwebError("form di login Fastweb non riconosciuto")
    return parser.fields


def encode_multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = "----FastwebPowerControl" + uuid.uuid4().hex
    parts: list[str] = []
    for name, value in fields.items():
        parts.extend(
            (
                f"--{boundary}",
                f'Content-Disposition: form-data; name="{name}"',
                "",
                value,
            )
        )
    parts.extend((f"--{boundary}--", ""))
    return "\r\n".join(parts).encode(), f"multipart/form-data; boundary={boundary}"


def read_cookie(path: str | None) -> str:
    cookie = os.environ.get("FASTWEB_COOKIE", "")
    if path:
        cookie = Path(path).read_text(encoding="utf-8").strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1].strip()
    if not cookie:
        raise FastwebError("cookie mancante: usa --cookie-file o FASTWEB_COOKIE")
    if "\r" in cookie or "\n" in cookie:
        raise FastwebError("il cookie deve stare su una sola riga")
    try:
        cookie.encode("latin-1")
    except UnicodeEncodeError as error:
        if "…" in cookie:
            raise FastwebError(
                "cookie abbreviato con '…': usa Copy value o Copy as cURL in DevTools"
            ) from error
        raise FastwebError("il cookie contiene caratteri non validi per HTTP") from error
    return cookie


def read_credentials(path: str | None) -> tuple[str, str] | None:
    username = os.environ.get("FASTWEB_USERNAME", "")
    password = os.environ.get("FASTWEB_PASSWORD", "")
    if path:
        try:
            values = json.loads(Path(path).read_text(encoding="utf-8"))
            username = values.get("username", "")
            password = values.get("password", "")
        except (json.JSONDecodeError, AttributeError) as error:
            raise FastwebError("file credenziali non valido") from error
    if not username and not password:
        return None
    if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
        raise FastwebError("username o password Fastweb mancanti")
    return username, password


def parse_cookie_header(header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in header.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            cookies[name] = value
    if not cookies:
        raise FastwebError("nessun cookie valido trovato")
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


def cookie_session(header: str):
    cookies = parse_cookie_header(header)
    jar = CookieJar()
    for name in AUTH_COOKIE_NAMES:
        if name in cookies:
            jar.set_cookie(_make_cookie(name, cookies[name]))
    if not any(cookie.name in {"FWB_RM", "PHPSESSID"} for cookie in jar):
        raise FastwebError("mancano FWB_RM e PHPSESSID")
    return build_opener(HTTPCookieProcessor(jar)), jar


def serialize_cookie_jar(jar: CookieJar) -> str:
    cookies = {
        cookie.name: cookie.value
        for cookie in jar
        if cookie.domain.lstrip(".") == "fastweb.it"
        and cookie.name in AUTH_COOKIE_NAMES
        and not cookie.is_expired()
    }
    return "; ".join(
        f"{name}={cookies[name]}" for name in AUTH_COOKIE_NAMES if name in cookies
    )


def save_cookie(path: str, header: str) -> None:
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(header + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def _open(opener, request: Request, timeout: float):
    try:
        return opener.open(request, timeout=timeout)
    except HTTPError as error:
        raise FastwebError(f"HTTP {error.code} da Fastweb") from error
    except URLError as error:
        raise FastwebError(f"connessione a Fastweb fallita: {error.reason}") from error


def load_dashboard(opener, timeout: float) -> str:
    request = Request(DASHBOARD_URL, headers={"User-Agent": USER_AGENT})
    with _open(opener, request, timeout) as response:
        final_url = response.geturl()
        page = response.read().decode(response.headers.get_content_charset() or "utf-8")
    if "/accesso/" in final_url or "/contenuti-riservati/" in final_url:
        raise _AuthenticationRequired("sessione Fastweb scaduta")
    return page


def login(opener, credentials: tuple[str, str], timeout: float) -> None:
    username, password = credentials
    request = Request(LOGIN_URL, headers={"User-Agent": USER_AGENT})
    with _open(opener, request, timeout) as response:
        page = response.read().decode(response.headers.get_content_charset() or "utf-8")

    fields = extract_login_fields(page)
    fields.update(
        {
            "username": username,
            "password": password,
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
    with _open(opener, request, timeout) as response:
        raw = response.read().decode(response.headers.get_content_charset() or "utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise FastwebError("risposta login Fastweb inattesa") from error
    if payload.get("errorCode") != 0:
        if payload.get("needRecaptcha"):
            # ponytail: stop here; bypassing reCAPTCHA is not a valid automation path.
            raise FastwebError("Fastweb richiede reCAPTCHA: login automatico sospeso")
        raise FastwebError(payload.get("errorMessage") or "login Fastweb fallito")

    if payload.get("rm"):
        with _open(opener, Request(SET_RM_URL, headers={"User-Agent": USER_AGENT}), timeout) as response:
            response.read()
    if payload.get("mt"):
        with _open(opener, Request(SET_MT_URL, headers={"User-Agent": USER_AGENT}), timeout) as response:
            response.read()
    if payload.get("redirectURI"):
        redirect_url = urljoin(LOGIN_URL, payload["redirectURI"])
        with _open(opener, Request(redirect_url, headers={"User-Agent": USER_AGENT}), timeout) as response:
            response.read()


def fetch_realtime(
    cookie: str,
    timeout: float = 10,
    credentials: tuple[str, str] | None = None,
) -> tuple[dict, str]:
    opener, jar = cookie_session(cookie)
    try:
        page = load_dashboard(opener, timeout)
    except _AuthenticationRequired:
        if not credentials:
            raise FastwebError(
                "sessione persistente scaduta e credenziali automatiche non configurate"
            ) from None
        login(opener, credentials, timeout)
        page = load_dashboard(opener, timeout)

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
    with _open(opener, request, timeout) as response:
        final_url = response.geturl()
        raw = response.read().decode(response.headers.get_content_charset() or "utf-8")
    if "/accesso/" in final_url or "/contenuti-riservati/" in final_url:
        raise FastwebError("sessione Fastweb scaduta: aggiorna il cookie")

    try:
        payload = json.loads(raw)
        realtime = payload["data"]["realtime"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise FastwebError("risposta Fastweb inattesa") from error
    if payload.get("errorCode") != 0 or not isinstance(realtime, (int, float)):
        raise FastwebError(payload.get("errorMessage") or "risposta Fastweb non valida")
    return payload, serialize_cookie_jar(jar)


def self_check() -> None:
    token = "a" * 64
    assert extract_security_token(f'<input value="{token}" name="securityToken">') == token
    assert extract_security_token(f'<script>securityToken="{token}";</script>') == token
    fields = extract_login_fields(
        f'<form id="formLogin"><input name="securityToken" value="{token}"></form>'
    )
    assert fields["securityToken"] == token
    body, content_type = encode_multipart({"action": "consumptionRealtime"})
    assert b'consumptionRealtime' in body and "boundary=" in content_type
    assert parse_cookie_header("a=1; b=2") == {"a": "1", "b": "2"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cookie-file", help="file contenente il valore dell'header Cookie")
    parser.add_argument("--credentials-file", help="JSON con username e password Fastweb")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    try:
        if args.self_test:
            self_check()
            print("ok")
            return 0
        payload, updated_cookie = fetch_realtime(
            read_cookie(args.cookie_file),
            args.timeout,
            read_credentials(args.credentials_file),
        )
        if args.cookie_file:
            save_cookie(args.cookie_file, updated_cookie)
        print(json.dumps(payload, separators=(",", ":")))
        return 0
    except (FastwebError, OSError) as error:
        print(f"fastweb-power-control: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
