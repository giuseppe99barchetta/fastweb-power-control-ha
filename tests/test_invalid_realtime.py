"""Regression tests for invalid realtime power readings."""

from threading import RLock
from unittest.mock import Mock

import pytest

from custom_components.fastweb_power_control.api import FastwebClient, FastwebError


@pytest.mark.parametrize("invalid", [False, True, None, "False", "1500", -1, float("nan"), float("inf"), -float("inf")])
def test_realtime_rejects_invalid_power(invalid):
    client = object.__new__(FastwebClient)
    client._lock = RLock()
    client._dashboard_action = Mock(return_value={"data": {"realtime": invalid}})
    with pytest.raises(FastwebError, match="invalid Fastweb realtime response"):
        client.get_realtime()


@pytest.mark.parametrize("valid", [0, 0.0, 1500, 1500.5])
def test_realtime_accepts_finite_nonnegative_power(valid):
    client = object.__new__(FastwebClient)
    client._lock = RLock()
    client._dashboard_action = Mock(return_value={"data": {"realtime": valid, "realtime_sin": 1}})
    result = client.get_realtime()
    assert result["data"]["realtime"] == valid
    assert "realtime_sin" not in result["data"]
