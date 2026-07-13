# Fastweb Power Control per Home Assistant

Prova minima: usa la sessione MyFastweb esistente, ricava automaticamente il
`securityToken` dalla dashboard e legge `consumptionRealtime` con il multipart
usato dal sito. Non richiede pacchetti Python esterni.

## Prova locale

1. Esporta da DevTools **solo il valore** dell'header `Cookie` di una richiesta
   funzionante e salvalo, su una sola riga, in `fastweb_power_control.cookie`.
   Usa **Copy value** oppure **Copy as cURL**: il testo mostrato a video può
   essere abbreviato con `…`. Non incollarlo in chat e non aggiungerlo al
   repository.
2. Esegui:

   ```powershell
   python .\fastweb_power_control.py --self-test
   python .\fastweb_power_control.py --cookie-file .\fastweb_power_control.cookie
   ```

Una risposta valida contiene `data.realtime` in watt. Se la sessione scade lo
script termina con codice non zero e chiede di aggiornare il cookie.

## Home Assistant

1. Copia `fastweb_power_control.py` e `fastweb_power_control.cookie` in
   `/config/`.
2. Proteggi il cookie (`chmod 600 /config/fastweb_power_control.cookie` se hai
   accesso al terminale).
3. Copia il contenuto di `configuration.yaml.example` nel tuo
   `configuration.yaml`, verifica la configurazione e riavvia Home Assistant.

Il polling è impostato a 30 secondi. Il sito interroga il realtime ogni 10
secondi, ma questa prova esegue una GET della dashboard e una POST a ogni ciclo:
abbassa l'intervallo solo dopo aver verificato stabilità e durata della sessione.

Per ottenere i kWh dal sensore in W, crea in Home Assistant un helper
**Integrale** usando `sensor.fastweb_power_control` come sorgente e il prefisso
metrico `k`.

## Accesso diretto alla Plug

La Power Control Plug riceve i dati del contatore 2G tramite Chain 2/PLC e usa
il Wi-Fi 2,4 GHz per la connettività remota. La variante domestica Plug non
documenta API locali; Sinapsi pubblicizza Modbus locale per la variante DIN.

Vale comunque un test breve e mirato:

1. ricavare IP e MAC della Plug dal router;
2. controllare solo quell'host per porte HTTP, MQTT, CoAP, mDNS o SSDP;
3. catturare solo il traffico di quell'IP per vedere DNS, destinazioni e TLS.

Se espone un protocollo locale, si abbandona il cloud. Se apre solo connessioni
TLS verso Internet, intercettare i payload richiederebbe MITM o reverse
engineering del firmware e non conviene rispetto all'endpoint MyFastweb.

### Verifica sulla rete locale

La Plug non espone porte TCP comuni. Dal Query Log DNS del solo dispositivo
risultano questi servizi:

- `mqtt.prod.smart-power-control.digiwatt.energy`
- `sps-prd.fastweb.sghiot.com`
- `sps-prd.oauth.sghiot.com`
- `sps-prd.iot.sghiot.com`
- `connectivitycheck.gstatic.com`
- `pool.ntp.org`

Il broker MQTT risponde sulle porte 443 e 8883 usando TLS 1.3 e un certificato
Amazon. Il traffico locale è quindi un collegamento cloud cifrato: senza le
credenziali MQTT provisionate nel dispositivo, sniffarlo non espone i dati di
consumo. L'endpoint MyFastweb resta il percorso più piccolo e stabile da usare.
