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

Una risposta valida contiene `data.realtime` in watt.

### Rinnovo automatico della sessione

Il cookie esportato serve soltanto per l'avvio iniziale. A ogni esecuzione lo
script:

1. carica i cookie in una sessione HTTP;
2. applica tutti i `Set-Cookie` restituiti da Fastweb;
3. riscrive atomicamente il file con i soli cookie necessari.

È stato verificato che il solo `FWB_RM` (il cookie **Ricordami**) rigenera
automaticamente `PHPSESSID` e gli altri cookie di sessione. Non è quindi
necessario copiarli di nuovo quando scade la sessione PHP.

Quando scade anche `FWB_RM`, lo script può tentare il login completo. Crea un
file `fastweb_power_control.credentials` protetto e non versionato:

```json
{"username":"LA_TUA_USERNAME","password":"LA_TUA_PASSWORD"}
```

Poi aggiungi `--credentials-file /percorso/del/file` al comando. Il login usa
lo stesso endpoint AJAX del sito e abilita nuovamente **Ricordami**. Se Fastweb
risponde con `needRecaptcha`, l'automazione si ferma: il reCAPTCHA non può e non
deve essere aggirato. Mantenendo attivo e aggiornato `FWB_RM`, questo fallback
dovrebbe essere raro.

## Home Assistant

1. Copia `fastweb_power_control.py`, `fastweb_power_control.cookie` e, se vuoi
   il login completo, `fastweb_power_control.credentials` in `/config/`.
2. Proteggi i file (`chmod 600 /config/fastweb_power_control.*` se hai accesso
   al terminale).
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

### Prova con MQTT Explorer

Parametri confermati:

- host: `mqtt.prod.smart-power-control.digiwatt.energy`
- porta MQTT TLS: `8883`
- TLS/SNI: abilitati
- certificato server: valido, emesso da Amazon

Un `CONNECT` anonimo e un `CONNECT` con username/password fittizi vengono
entrambi chiusi dal broker prima del `CONNACK`. MQTT Explorer supporta
certificato client, chiave privata e SNI, ma per collegarsi servono ancora:

- client ID corretto;
- certificato client e relativa chiave privata, oppure il token previsto dal
  broker;
- topic consentiti dalla policy del dispositivo.

MQTT Explorer non può scoprire questi valori dal solo hostname. Le vie per
ottenerli, in ordine di utilità, sono:

1. analizzare il provisioning Bluetooth e HTTPS durante una nuova associazione;
2. analizzare l'app MyFastweb e le sue chiamate OAuth/IoT;
3. estrarre firmware o flash della Plug tramite UART/programmatore;
4. catturare il traffico sul Flint per confermare IP, porta e frequenza.

La quarta via non recupera credenziali o payload: TLS 1.3 impedisce la
decodifica passiva. Le prime tre richiedono una nuova fase di ricerca e, per il
provisioning o l'hardware, possono interrompere temporaneamente il servizio.

## Confronto delle vie

| Via | Stato | Limite principale |
|---|---|---|
| AJAX MyFastweb | Funzionante | Dipende dalla sessione Fastweb |
| AJAX + rinnovo cookie | Implementato | reCAPTCHA quando scade anche `FWB_RM` |
| API OAuth/IoT Sinapsi | Da reverse engineerizzare | Flusso e credenziali non documentati |
| MQTT cloud | Broker trovato | Mancano identità, certificato/chiave e topic |
| API locale Plug | Non rilevata | Nessuna porta locale esposta |
| Chain 2/PLC diretto | Hardware avanzato | Protocollo e chiavi provisionate |
