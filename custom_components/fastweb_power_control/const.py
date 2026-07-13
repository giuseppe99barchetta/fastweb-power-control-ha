"""Constants for Fastweb Power Control."""

DOMAIN = "fastweb_power_control"
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 30


def trapezoid_kwh(previous_w: float, current_w: float, elapsed_seconds: float) -> float:
    """Convert two power samples and their interval to consumed kWh."""
    average_w = max(0.0, (previous_w + current_w) / 2)
    return average_w * max(0.0, elapsed_seconds) / 3_600_000


if __name__ == "__main__":
    assert trapezoid_kwh(1000, 1000, 3600) == 1
    assert trapezoid_kwh(-100, -100, 3600) == 0
