<p align="center">
  <img src="custom_components/fastweb_power_control/brand/logo.png" alt="Fastweb" width="226">
</p>

# Fastweb Power Control for Home Assistant

[Italiano](README.it.md)

An unofficial custom integration for reading and configuring Fastweb Power
Control from Home Assistant. It uses the same private endpoints as the
MyFastweb portal, with no MQTT, external Python dependencies, or manually
copied cookies.

> This project is not affiliated with or supported by Fastweb. The API is not
> public and may change without notice.

## Available entities

- one real-time power sensor in W;
- one cumulative kWh sensor compatible with the Energy dashboard;
- switches for the master LED, meter LED, Internet LED, and buzzer;
- switches for power-limit, provider-disconnection, monthly-budget, and
  holiday-mode notifications;
- a number entity for the monthly threshold in kWh;
- start and end date entities for holiday mode.

Settings are refreshed periodically and immediately after every command. Set
both holiday dates before enabling holiday mode. Contractual service
deactivation is deliberately not exposed in Home Assistant.

## Install with HACS

The repository must be public on GitHub before HACS can install it.

1. In HACS, open **Integrations → menu → Custom repositories**.
2. Add
   `https://github.com/giuseppe99barchetta/FastwebPowerControlHas` as an
   **Integration** repository.
3. Find and install **Fastweb Power Control**.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration** and select
   **Fastweb Power Control**.
6. Enter your MyFastweb username, password, and update interval.

The interval can later be changed through **Configure**. Home Assistant 2026.3
or later is required.

## Authentication and cookie renewal

The setup flow verifies credentials immediately. The integration:

1. keeps a Fastweb session in memory;
2. automatically applies every received `Set-Cookie` header;
3. reuses the persistent `FWB_RM` cookie to renew the session;
4. signs in again after session expiry or a Home Assistant restart;
5. starts Home Assistant’s reauthentication flow when credentials are no
   longer valid.

No cookie file is needed. If Fastweb requires a reCAPTCHA, sign in once on the
website and retry. This project does not attempt to bypass it.

## Energy in kWh

Cumulative consumption is calculated from power samples, restored after
restarts, and can be selected directly as grid consumption in the **Energy**
dashboard. Periods without samples from Fastweb or Home Assistant are not
estimated.

## Manual installation

Copy `custom_components/fastweb_power_control` to Home Assistant’s
`/config/custom_components/` directory, restart Home Assistant, and add the
integration from the UI.

## Diagnostic client

```powershell
python .\fastweb_power_control.py --self-test
python .\fastweb_power_control.py `
  --credentials-file .\fastweb_power_control.credentials
```

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

## Development

```powershell
python .\fastweb_power_control.py --self-test
python -m ruff check .
```

The GitHub workflow runs HACS Action and hassfest on every push and pull
request.
