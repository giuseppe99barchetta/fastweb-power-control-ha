<p align="center">
  <img src="custom_components/fastweb_power_control/brand/logo.png" alt="Fastweb" width="226">
</p>

# Fastweb Power Control for Home Assistant

[Italiano](README.it.md)

An unofficial custom integration that reads real-time Fastweb Power Control
consumption in Home Assistant. It uses the same private MyFastweb endpoint as
the Fastweb dashboard, with no MQTT, external Python packages, or manually
copied cookies.

> This project is not affiliated with or supported by Fastweb. The API is not
> public and may change without notice.

## Install with HACS

The repository must be public on GitHub before HACS can install it.

1. In HACS, open **Integrations** → menu → **Custom repositories**.
2. Add
   `https://github.com/giuseppe99barchetta/FastwebPowerControlHas` as an
   **Integration** repository.
3. Find and install **Fastweb Power Control**.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration** and select
   **Fastweb Power Control**.
6. Enter your MyFastweb username, password, and preferred update interval.

The integration creates a power sensor in watts with `device_class: power` and
`state_class: measurement`. Its entity ID depends on the language used when the
entity is created and can be changed in Home Assistant.

Home Assistant 2026.3 or later is required because the Fastweb branding is
bundled with the custom integration.

## Authentication and cookie renewal

The setup flow verifies the credentials immediately. The integration then:

1. keeps the Fastweb session in memory;
2. applies every received `Set-Cookie` header automatically;
3. uses the persistent `FWB_RM` cookie to renew the PHP session;
4. signs in again after a restart using the credentials stored by Home
   Assistant.

No cookie file is needed. If Fastweb requests a reCAPTCHA, sign in once on the
website and try again. This project does not attempt to bypass reCAPTCHA.

## Energy in kWh

The sensor reports instantaneous power in W. To obtain energy in kWh, create an
**Integral** helper in Home Assistant, select the sensor as its input, and use
`k` as the metric prefix.

## Manual installation

Copy `custom_components/fastweb_power_control` to Home Assistant's
`/config/custom_components/` directory, restart Home Assistant, and add the
integration from the UI.

## Command-line client

The legacy client remains available for diagnostics:

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

The Plug tested on the local network exposes no common TCP ports. Its DNS
requests include:

- `mqtt.prod.smart-power-control.digiwatt.energy`
- `sps-prd.fastweb.sghiot.com`
- `sps-prd.oauth.sghiot.com`
- `sps-prd.iot.sghiot.com`

The MQTT broker accepts TLS connections on ports 8883 and 443. It closes
anonymous connections and connections with arbitrary credentials before
`CONNACK`, so a provisioned client ID, certificate and key or token, and
authorized topics are required. Passive router captures reveal destinations
and timing, but TLS 1.3 protects payloads and credentials.

Known MQTT Explorer settings:

```text
Host: mqtt.prod.smart-power-control.digiwatt.energy
Port: 8883
TLS and certificate verification: enabled
SNI: mqtt.prod.smart-power-control.digiwatt.energy
Protocol: MQTT 3.1.1
```

The next useful research path is the MyFastweb Android app provisioning flow
during a new Plug pairing. Router traffic alone cannot recover the required
cryptographic material.

## Development

```powershell
python .\fastweb_power_control.py --self-test
python -m py_compile .\fastweb_power_control.py `
  .\custom_components\fastweb_power_control\api.py
```

The GitHub workflow runs both HACS Action and hassfest on every push and pull
request.
