"""Tests for the synchronous MyFastweb client."""

from __future__ import annotations

from http.cookiejar import Cookie
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from custom_components.fastweb_power_control import api
from custom_components.fastweb_power_control.api import (
    DASHBOARD_URL,
    AuthenticationRequired,
    FastwebClient,
    FastwebError,
    RecaptchaRequired,
    _iso_date,
    _make_cookie,
    _parse_history,
    _parse_latest,
    _parse_notifications,
    _portal_date,
    encode_multipart,
    extract_form_fields,
    extract_security_token,
    parse_cookie_header,
)
from custom_components.fastweb_power_control.const import trapezoid_kwh

TOKEN = "a" * 64


def _host_cookie(name: str, value: str, domain: str) -> Cookie:
    """A cookie as http.cookiejar stores it after a Set-Cookie without Domain."""
    cookie = _make_cookie(name, value)
    cookie.domain = domain
    return cookie


def test_security_token_from_input_and_script() -> None:
    assert extract_security_token(f'<input value="{TOKEN}" name="securityToken">') == TOKEN
    assert extract_security_token(f'<script>securityToken="{TOKEN}";</script>') == TOKEN
    with pytest.raises(FastwebError):
        extract_security_token("<html></html>")


def test_form_fields() -> None:
    fields = extract_form_fields(
        f'<form id="request_form"><input name="securityToken" value="{TOKEN}">'
        '<input name="notify_led_all" value="Y"></form><input name="outside">',
        "request_form",
    )
    assert fields == {"securityToken": TOKEN, "notify_led_all": "Y"}
    with pytest.raises(FastwebError):
        extract_form_fields("<form id='other'></form>", "request_form")


def test_multipart_and_cookie_header() -> None:
    body, content_type = encode_multipart({"action": "consumptionRealtime"})
    assert b"consumptionRealtime" in body and "boundary=" in content_type
    assert parse_cookie_header("a=1; b=2") == {"a": "1", "b": "2"}
    assert parse_cookie_header("Cookie: a=1; b=2") == {"a": "1", "b": "2"}


def test_dates() -> None:
    assert _portal_date("2026-07-13") == "13/07/2026"
    assert _portal_date(None) == ""
    assert _iso_date("13/07/2026") == "2026-07-13"
    assert _iso_date("01/01/2020") is None
    with pytest.raises(FastwebError):
        _portal_date("13/07/2026")


def test_latest_samples_sorted_and_cleaned() -> None:
    latest = _parse_latest(
        {
            "latest": {
                "2026-07-13T10:01:00+02:00": {"power": 200},
                "2026-07-13T10:00:00+02:00": {"power": -5},
                "broken": {"power": "x"},
            }
        }
    )
    assert [sample["power"] for sample in latest] == [0.0, 200.0]
    with pytest.raises(FastwebError):
        _parse_latest({"latest": {}})


def test_notifications_parsed_oldest_first() -> None:
    items = [
        {"id": "b", "type": "provider_disconnection", "title": "T", "message": "M",
         "created_at": "2026-08-17T16:49:54Z", "read": True, "extra": "dropped"},
        {"id": "a", "type": "contracted_power_limit_exceeded", "title": "T", "message": "M",
         "created_at": "2026-07-26T05:06:49Z", "read": False},
        {"id": 3, "created_at": "2026-01-01T00:00:00Z"},
        "broken",
    ]
    parsed = _parse_notifications(items)
    assert [item["id"] for item in parsed] == ["a", "b"]
    assert "extra" not in parsed[1]
    assert _parse_notifications(None) == []


HISTORY_RESPONSE = {
    "medium_o": {
        "account_number": "000",
        "period": "last-seven-days",
        "electricity_data": {
            "index": [0],
            "columns": ["fridge", "washing_machine", "standby"],
            "data": [[1500.0, 2250.0, 7000.0]],
        },
        "total_consumption": {"selected_period": 21000.0, "previous_period": 18500.0},
        "daily_breakdown": {
            "selected_period": {
                "index": ["2026-10-17T00:00:00", "2026-10-18T00:00:00"],
                "columns": ["standby", "fridge", "washing_machine"],
                "data": [[4000.0, 900.0, 450.0], [5000.0, 600.0, 1800.0]],
            }
        },
    },
    "totals": {
        "period": [
            {"label": "17/10", "total": 9000.0, "day": "2026-10-17"},
            {"label": "18/10", "total": 12000.0, "day": "2026-10-18"},
        ],
        "previous": [{"label": "10/10", "total": 9000.0}],
    },
    "type": "day",
}


def test_history_converted_to_kwh() -> None:
    history = _parse_history(HISTORY_RESPONSE)
    assert history["period_energy"] == 21.0
    assert history["previous_period_energy"] == 18.5
    assert history["days"][-1] == {"day": "2026-10-18", "energy": 12.0}
    assert history["categories"] == {"fridge": 1.5, "washing_machine": 2.25, "standby": 7.0}
    # Columns are matched by name: their order differs between the two frames.
    assert history["last_day_categories"] == {
        "standby": 5.0,
        "fridge": 0.6,
        "washing_machine": 1.8,
    }
    assert "account_number" not in str(history)
    with pytest.raises(FastwebError):
        _parse_history({"medium_o": {}, "totals": {"period": []}})
    with pytest.raises(FastwebError):
        _parse_history({})


def test_thirty_day_history_uses_daily_breakdown() -> None:
    month = {
        "medium_o": {
            **HISTORY_RESPONSE["medium_o"],
            "period": "last-thirty-days",
            "total_consumption": {"selected_period": 380000.0, "previous_period": 510000.0},
        },
        # Thirty-day totals are weekly and keyed by week start.
        "totals": {"period": {"2026-10-12": {"total": 21000.0, "start": "2026-10-12"}}},
        "type": "month",
    }
    history = _parse_history(month)
    assert history["period_energy"] == 380.0
    assert history["days"] == [
        {"day": "2026-10-17", "energy": pytest.approx(5.35)},
        {"day": "2026-10-18", "energy": pytest.approx(7.4)},
    ]


def test_monthly_history_failure_keeps_weekly(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FastwebClient()
    calls: list[str] = []

    def fake_history(period: str, timeout: float) -> dict:
        calls.append(period)
        if period == "last-thirty-days":
            raise FastwebError("monthly view down")
        return {"period_energy": 1.0}

    monkeypatch.setattr(client, "_history", fake_history)
    assert client.get_history() == {"period_energy": 1.0, "month": None}
    assert calls == ["last-seven-days", "last-thirty-days"]


def test_trapezoid() -> None:
    assert trapezoid_kwh(1000, 1000, 3600) == 1
    assert trapezoid_kwh(-100, -100, 3600) == 0


def test_cookie_header_keeps_www_cookies() -> None:
    """Cookies issued host-only by www.fastweb.it must be persisted too."""
    client = FastwebClient()
    client.jar.set_cookie(_host_cookie("FWB_RM", "remember", "www.fastweb.it"))
    client.jar.set_cookie(_host_cookie("PHPSESSID", "session", ".fastweb.it"))
    client.jar.set_cookie(_host_cookie("FWB_RM", "foreign", "example.com"))
    client.jar.set_cookie(_host_cookie("tracking", "ignored", "fastweb.it"))
    assert client.cookie_header == "FWB_RM=remember; PHPSESSID=session"


def test_restored_cookies_are_sent_to_both_hosts() -> None:
    client = FastwebClient(cookie="FWB_RM=abc; unknown=1")
    for url in (DASHBOARD_URL, DASHBOARD_URL.replace("://", "://www.")):
        request = Request(url)
        client.jar.add_cookie_header(request)
        assert request.get_header("Cookie") == "FWB_RM=abc"


def test_expired_cookie_does_not_poison_login() -> None:
    client = FastwebClient("user", "password", "FWB_RM=old; PHPSESSID=old")
    visited: list[str] = []

    def fake_page(url: str, timeout: float) -> str:
        visited.append(url)
        if len(visited) < 3:
            raise AuthenticationRequired("session expired")
        return "authenticated"

    def fake_login(timeout: float) -> None:
        assert not list(client.jar), "Expired cookies leaked into the new login"
        client.jar.set_cookie(_make_cookie("FWB_RM", "fresh"))

    client._load_page = fake_page
    client._login = fake_login
    assert client._authenticated_page(DASHBOARD_URL, 2) == "authenticated"
    assert visited == [
        DASHBOARD_URL,
        DASHBOARD_URL,
        DASHBOARD_URL.replace("https://fastweb.it/", "https://www.fastweb.it/"),
    ]
    assert client.cookie_header == "FWB_RM=fresh"


class _Opener:
    def __init__(self, error: HTTPError) -> None:
        self.error = error

    def open(self, request: Request, timeout: float):
        raise self.error


def _redirect(location: str, url: str = "https://fastweb.it/myfastweb/x/") -> HTTPError:
    return HTTPError(url, 302, "redirect loop", {"Location": location}, None)


def test_login_redirect_loop_requires_auth() -> None:
    client = FastwebClient()
    client._opener = _Opener(_redirect("/myfastweb/accesso/login/"))
    with pytest.raises(AuthenticationRequired):
        client._open(Request(DASHBOARD_URL), 2)


def test_other_redirect_loop_is_described() -> None:
    client = FastwebClient()
    client._opener = _Opener(_redirect("/myfastweb/y/"))
    with pytest.raises(FastwebError, match=r"GET .* \(redirect /myfastweb/x/ to /myfastweb/y/\)"):
        client._open(Request(DASHBOARD_URL), 2)


def test_login_requires_recaptcha(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FastwebClient("user", "password")

    class _Response:
        def __init__(self, body: str) -> None:
            self.body = body.encode()
            self.headers = self

        def get_content_charset(self):
            return "utf-8"

        def read(self) -> bytes:
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    pages = iter(
        [
            f'<form id="formLogin"><input name="securityToken" value="{TOKEN}"></form>',
            '{"errorCode": 1, "needRecaptcha": true}',
        ]
    )
    monkeypatch.setattr(client, "_open", lambda request, timeout: _Response(next(pages)))
    with pytest.raises(RecaptchaRequired):
        client._login(2)


def test_settings_write_retries_after_expired_session() -> None:
    client = FastwebClient("user", "password")
    form = {
        "securityToken": TOKEN,
        "notify_led_all": "Y",
        "notify_led_1": "Y",
        "notify_led_2": "Y",
        "notify_buzz": "N",
    }
    forms: list[str] = []
    posts: list[str] = []

    def fake_form(url: str, timeout: float) -> dict[str, str]:
        forms.append(url)
        client._token = f"token{len(forms)}"
        return form

    def fake_post(url: str, referer: str, fields: dict[str, str], timeout: float):
        posts.append(fields["securityToken"])
        if len(posts) == 1:
            raise AuthenticationRequired("expired")
        return {"errorCode": 0}

    client._form = fake_form
    client._post_json = fake_post
    result = client.update_led_settings({"buzzer": True})
    assert result["buzzer"] is True
    assert posts == ["token1", "token2"]
    assert forms == [api.LED_SETTINGS_URL, api.LED_SETTINGS_URL]


def test_user_agent_uses_manifest_version() -> None:
    assert api.USER_AGENT.endswith("/" + api._manifest_version())
    assert api._manifest_version() != "dev"
