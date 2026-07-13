#!/usr/bin/env python3
"""Standalone compatibility CLI for the Home Assistant integration client."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

_API_PATH = Path(__file__).parent / "custom_components/fastweb_power_control/api.py"
_SPEC = importlib.util.spec_from_file_location("fastweb_power_control_api", _API_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Fastweb client not found")
_API = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_API)
FastwebClient = _API.FastwebClient
FastwebError = _API.FastwebError
self_check = _API.self_check


def read_cookie(path: str | None) -> str:
    cookie = (
        Path(path).read_text(encoding="utf-8").strip()
        if path
        else os.getenv("FASTWEB_COOKIE", "")
    )
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1].strip()
    if "\r" in cookie or "\n" in cookie:
        raise FastwebError("the cookie must be stored on one line")
    return cookie


def read_credentials(path: str | None) -> tuple[str, str]:
    username = os.getenv("FASTWEB_USERNAME", "")
    password = os.getenv("FASTWEB_PASSWORD", "")
    if path:
        try:
            values = json.loads(Path(path).read_text(encoding="utf-8"))
            username, password = values.get("username", ""), values.get("password", "")
        except (json.JSONDecodeError, AttributeError) as error:
            raise FastwebError("invalid credentials file") from error
    if (username or password) and not (
        isinstance(username, str)
        and isinstance(password, str)
        and username
        and password
    ):
        raise FastwebError("missing Fastweb username or password")
    return username, password


def save_cookie(path: str, header: str) -> None:
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(header + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cookie-file")
    parser.add_argument("--credentials-file")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_check()
            print("ok")
            return 0
        username, password = read_credentials(args.credentials_file)
        client = FastwebClient(username, password, read_cookie(args.cookie_file))
        payload = client.get_realtime(args.timeout)
        if args.cookie_file:
            save_cookie(args.cookie_file, client.cookie_header)
        print(json.dumps(payload, separators=(",", ":")))
        return 0
    except (FastwebError, OSError) as error:
        print(f"fastweb-power-control: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
