<p align="center">
  <img src="custom_components/fastweb_power_control/brand/logo.png" alt="Fastweb" width="226">
</p>

# Fastweb Power Control per Home Assistant

[English](README.md)

Custom integration non ufficiale per leggere il consumo istantaneo di Fastweb
Power Control in Home Assistant. Usa l'endpoint MyFastweb già utilizzato dalla
dashboard Fastweb; non richiede MQTT, pacchetti Python esterni o cookie copiati
manualmente.

> Questo progetto non è affiliato né supportato da Fastweb. L'API usata non è
> pubblica e potrebbe cambiare.

## Installazione con HACS

Il repository deve essere pubblico su GitHub prima di poter essere installato.

1. In HACS apri **Integrations** → menu → **Custom repositories**.
2. Aggiungi
   `https://github.com/giuseppe99barchetta/FastwebPowerControlHas` come
   **Integration**.
3. Cerca **Fastweb Power Control** e installala.
4. Riavvia Home Assistant.
5. Apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione** e
   seleziona **Fastweb Power Control**.
6. Inserisci username, password MyFastweb e l'intervallo di aggiornamento.

L'integrazione crea un sensore di potenza espresso in watt, con
`device_class: power` e `state_class: measurement`. L'ID dell'entità dipende
dalla lingua usata al momento della creazione e può essere modificato in Home
Assistant.

Home Assistant 2026.3 o successivo è richiesto perché le immagini Fastweb sono
incluse localmente nella custom integration.

## Autenticazione e rinnovo cookie

La configurazione UI verifica subito le credenziali. In seguito l'integrazione:

1. mantiene la sessione Fastweb in memoria;
2. applica automaticamente ogni `Set-Cookie` ricevuto;
3. usa il cookie persistente `FWB_RM` per rigenerare la sessione PHP;
4. dopo un riavvio effettua nuovamente il login con le credenziali salvate da
   Home Assistant.

Non è necessario creare o aggiornare un file cookie. Se Fastweb richiede un
reCAPTCHA, accedi una volta dal sito e riprova: il progetto non tenta di
aggirarlo.

## Energia in kWh

Il sensore misura potenza istantanea in W. Per ottenere energia in kWh crea un
helper **Integrale** in Home Assistant usando il sensore come sorgente e `k`
come prefisso metrico.

## Installazione manuale

Copia `custom_components/fastweb_power_control` nella directory
`/config/custom_components/` di Home Assistant, riavvia e aggiungi
l'integrazione dalla UI.

## Client da riga di comando

Il vecchio client resta disponibile per diagnosi:

```powershell
python .\fastweb_power_control.py --self-test
python .\fastweb_power_control.py `
  --credentials-file .\fastweb_power_control.credentials
```

Il file credenziali, escluso da Git, contiene:

```json
{"username":"IL_TUO_USERNAME","password":"LA_TUA_PASSWORD"}
```

## MQTT e accesso diretto alla Plug

La Plug all'indirizzo locale analizzato non espone porte TCP comuni. Dal DNS
del dispositivo risultano:

- `mqtt.prod.smart-power-control.digiwatt.energy`
- `sps-prd.fastweb.sghiot.com`
- `sps-prd.oauth.sghiot.com`
- `sps-prd.iot.sghiot.com`

Il broker MQTT risponde in TLS sulle porte 8883 e 443. Una connessione anonima
o con credenziali arbitrarie viene chiusa prima del `CONNACK`; servono quindi
client ID, certificato/chiave o token provisionati e topic autorizzati. Una
cattura passiva dal router mostra destinazioni e frequenza, ma TLS 1.3 non
permette di leggere payload o credenziali.

Parametri già noti per MQTT Explorer:

```text
Host: mqtt.prod.smart-power-control.digiwatt.energy
Porta: 8883
TLS e verifica certificato: attivi
SNI: mqtt.prod.smart-power-control.digiwatt.energy
Protocollo: MQTT 3.1.1
```

La prossima indagine utile è il provisioning dell'app Android MyFastweb durante
una nuova associazione della Plug. Il traffico del router, da solo, non basta a
recuperare il materiale crittografico.

## Sviluppo

```powershell
python .\fastweb_power_control.py --self-test
python -m py_compile .\fastweb_power_control.py `
  .\custom_components\fastweb_power_control\api.py
```

Il workflow GitHub esegue sia HACS Action sia hassfest a ogni push e pull
request.
