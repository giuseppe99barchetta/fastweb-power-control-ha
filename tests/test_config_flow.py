"""Tests for the Fastweb Power Control config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fastweb_power_control.api import (
    FastwebError,
    InvalidAuth,
    RecaptchaRequired,
)
from custom_components.fastweb_power_control.const import CONF_COOKIE, DOMAIN

from .conftest import USERNAME

VALIDATE = "custom_components.fastweb_power_control.config_flow._validate"
SETUP = "custom_components.fastweb_power_control.async_setup_entry"


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    with (
        patch(VALIDATE, return_value="FWB_RM=abc") as validate,
        patch(SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": USERNAME, "password": "secret", CONF_COOKIE: "FWB_RM=manual"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == USERNAME.lower()
    assert result["data"] == {
        "username": USERNAME,
        "password": "secret",
        "scan_interval": 30,
        CONF_COOKIE: "FWB_RM=abc",
    }
    assert validate.call_count == 1


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (InvalidAuth("no"), "invalid_auth"),
        (RecaptchaRequired("captcha"), "recaptcha_required"),
        (FastwebError("down"), "cannot_connect"),
    ],
)
async def test_user_flow_errors(hass: HomeAssistant, error: Exception, reason: str) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(VALIDATE, side_effect=error):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": USERNAME, "password": "x"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": reason}


async def test_user_flow_duplicate_account(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    # single_config_entry aborts before the form is shown.
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_reauth_updates_credentials(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with patch(VALIDATE, return_value="FWB_RM=new"), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": USERNAME.upper(), "password": "new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["password"] == "new"
    assert config_entry.data[CONF_COOKIE] == "FWB_RM=new"


async def test_reauth_rejects_other_account(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    with patch(VALIDATE, return_value="") as validate:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "someone@else.it", "password": "x"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    validate.assert_not_called()


async def test_reconfigure(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    with patch(VALIDATE, side_effect=RecaptchaRequired("captcha")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": USERNAME, "password": "new"}
        )
    assert result["errors"] == {"base": "recaptcha_required"}
    with patch(VALIDATE, return_value="FWB_RM=browser"), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": USERNAME, "password": "new", CONF_COOKIE: "FWB_RM=browser"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_COOKIE] == "FWB_RM=browser"


async def test_options_flow(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 60, "warning_threshold": 80}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {"scan_interval": 60, "warning_threshold": 80}
