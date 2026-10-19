<p align="center">
  <img src="custom_components/fastweb_power_control/brand/logo.png" alt="Fastweb" width="226">
</p>

# Fastweb Power Control for Home Assistant (HACS Custom Integration)

[Italiano](README.it.md)

An unofficial custom integration for reading and configuring Fastweb Power
Control from Home Assistant. It uses the same private endpoints as the
MyFastweb portal, with no MQTT or external Python dependencies. A manually
copied session cookie is available as a fallback when Fastweb blocks automatic
sign-in.

> This project is not affiliated with or supported by Fastweb. The API is not
> public and may change without notice.

## Available entities

- **Sensors and controls:** realtime power, today's peak power, cumulative
  Energy-dashboard consumption, contracted power, percentage used, and
  available power;
- **History:** consumption of the last day, last 7 and last 30 days, plus the
  portal's per-appliance estimate (fridge, washing machine, standby, …),
  refreshed hourly;
- **Alerts:** a configurable near-power-limit warning and a **Portal
  notification** event fired for every new Fastweb notification (power limit
  exceeded, supply interruption, …) with its title and message;
- **Configuration:** LEDs, buzzer, Fastweb notifications, monthly threshold,
  and holiday-mode dates;
- **Diagnostics:** Plug connectivity, stale data, API response time, last
  update, and unread notifications.

Settings are refreshed periodically and immediately after every command. Plug
status and settings that Fastweb stops returning become unavailable after a few
refresh periods instead of showing stale values. Contractual service
deactivation is deliberately not exposed in Home Assistant.

## Services and blueprint

`fastweb_power_control.set_holiday_period` writes both holiday dates and the
holiday-mode warning in one request, so the portal never sees an invalid
range:

```yaml
action: fastweb_power_control.set_holiday_period
data:
  start: "2026-08-01"
  end: "2026-08-21"
  enable: true
```

The [load shedding blueprint](blueprints/automation/fastweb_power_control/power_limit_load_shedding.yaml)
turns off selected loads when the contracted power usage stays above a
threshold, and can send a notification.

## Install with HACS

The repository must be public on GitHub before HACS can install it.

1. In HACS, open **Integrations → menu → Custom repositories**.
2. Add
   `https://github.com/giuseppe99barchetta/fastweb-power-control-ha` as an
   **Integration** repository.
3. Find and install **Fastweb Power Control**.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration** and select
   **Fastweb Power Control**.
6. Enter your MyFastweb username, password, and update interval. If automatic
   sign-in is blocked after a reCAPTCHA, also enter the optional **Session
   cookie** as described below.

The interval and power warning threshold can later be changed through
**Configure**; credentials and the session cookie through **Reconfigure**. Home Assistant 2026.3 or later is required.

The interval controls how often Home Assistant polls Fastweb, not how often
Fastweb produces a new sample. Fastweb may keep the same value for about one
minute, so two consecutive reads can match with a 30-second interval. Use 60
seconds to avoid redundant requests, or 30 seconds to detect the next sample
sooner.

Download the complete diagnostic report from the integration page using
**⋮ → Download diagnostics**; it is not an entity. Credentials, cookies, and
tokens are not included.

## Authentication and cookie renewal

The setup flow verifies credentials immediately. The integration:

1. keeps a Fastweb session and its cookies in the configuration entry;
2. automatically applies every received `Set-Cookie` header;
3. reuses the persistent `FWB_RM` cookie to renew the session;
4. signs in again after session expiry or a Home Assistant restart;
5. starts Home Assistant’s reauthentication flow when credentials are no
   longer valid.

Normally no cookie is needed. If Fastweb blocks automatic sign-in after a
reCAPTCHA (a repair issue explains it), sign in to MyFastweb in a browser and copy `FWB_RM=...` (or the
complete `Cookie` header) from a request to `fastweb.it` into the **Session
cookie** field. Treat the value as a credential: never publish it or include it
in issue reports. The integration renews it and excludes it from diagnostics.
This project does not attempt to bypass reCAPTCHA or other anti-bot protections.

## Energy in kWh

Cumulative consumption is calculated from Fastweb's timestamped power samples,
restored after restarts, and can be selected directly as grid consumption in
the **Energy** dashboard. Gaps longer than ten minutes are not estimated.

## Manual installation

Copy `custom_components/fastweb_power_control` to Home Assistant’s
`/config/custom_components/` directory, restart Home Assistant, and add the
integration from the UI.

## Diagnostic client

```powershell
python .\tools\fastweb_power_control.py `
  --credentials-file .\fastweb_power_control.credentials
```

`tools/configuration.yaml.example` shows the legacy `command_line` sensor
built on the same client.

The credentials file is excluded from Git and contains:

```json
{"username":"YOUR_USERNAME","password":"YOUR_PASSWORD"}
```

## MQTT and direct Plug access

The tested Plug exposes no common local TCP ports. DNS requests include the
broker `mqtt.prod.smart-power-control.digiwatt.energy`. It accepts TLS on ports
8883 and 443 but rejects anonymous and arbitrary credentials: provisioned
identities, tokens or certificates, and authorized topics are required.

Router captures reveal destinations and timing, while TLS 1.3 protects
payloads and credentials. The MyFastweb API is therefore currently the most
practical and maintainable route. The remaining research alternative is the
Android app provisioning flow during a new Plug pairing.

## Support the project

If this integration is useful to you, you can support its development by
buying me a coffee on Ko-fi.

<p align="center">
  <a href="https://ko-fi.com/ciuse99">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support me on Ko-fi">
  </a>
</p>

## Development

```bash
pip install -r requirements_test.txt
python -m pytest
python -m ruff check .
```

The tests need Python 3.14 and Home Assistant's test harness, which builds on
Linux, macOS, or WSL. The GitHub workflow runs HACS Action, hassfest, Ruff,
and the tests on every push and pull request.
