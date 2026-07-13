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
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

DASHBOARD_URL = "https://fastweb.it/myfastweb/abbonamento/consumi-power-control/"
AJAX_URL = DASHBOARD_URL + "ajax/"
USER_AGENT = "Mozilla/5.0 FastwebPowerControlHA/0.1"


class FastwebError(RuntimeError):
    """A readable Fastweb request error."""


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


def _open(request: Request, timeout: float):
    try:
        return build_opener().open(request, timeout=timeout)
    except HTTPError as error:
        raise FastwebError(f"HTTP {error.code} da Fastweb") from error
    except URLError as error:
        raise FastwebError(f"connessione a Fastweb fallita: {error.reason}") from error


def fetch_realtime(cookie: str, timeout: float = 10) -> dict:
    common_headers = {"Cookie": cookie, "User-Agent": USER_AGENT}
    request = Request(DASHBOARD_URL, headers=common_headers)
    with _open(request, timeout) as response:
        final_url = response.geturl()
        page = response.read().decode(response.headers.get_content_charset() or "utf-8")
    if "/accesso/" in final_url or "/contenuti-riservati/" in final_url:
        raise FastwebError("sessione Fastweb scaduta: aggiorna il cookie")

    token = extract_security_token(page)
    body, content_type = encode_multipart(
        {"securityToken": token, "action": "consumptionRealtime"}
    )
    request = Request(
        AJAX_URL,
        data=body,
        method="POST",
        headers={
            **common_headers,
            "Accept": "application/json",
            "Content-Type": content_type,
            "Referer": DASHBOARD_URL,
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    with _open(request, timeout) as response:
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
    return payload


def self_check() -> None:
    token = "a" * 64
    assert extract_security_token(f'<input value="{token}" name="securityToken">') == token
    assert extract_security_token(f'<script>securityToken="{token}";</script>') == token
    body, content_type = encode_multipart({"action": "consumptionRealtime"})
    assert b'consumptionRealtime' in body and "boundary=" in content_type


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cookie-file", help="file contenente il valore dell'header Cookie")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    try:
        if args.self_test:
            self_check()
            print("ok")
            return 0
        print(
            json.dumps(
                fetch_realtime(read_cookie(args.cookie_file), args.timeout),
                separators=(",", ":"),
            )
        )
        return 0
    except (FastwebError, OSError) as error:
        print(f"fastweb-power-control: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
