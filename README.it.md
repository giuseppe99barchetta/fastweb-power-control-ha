<p align="center">
  <img src="custom_components/fastweb_power_control/brand/logo.png" alt="Fastweb" width="226">
</p>

# Fastweb Power Control per Home Assistant

[English](README.md)

Integrazione custom non ufficiale per leggere e configurare Fastweb Power
Control da Home Assistant. Usa gli stessi endpoint privati del portale
MyFastweb: non richiede MQTT o dipendenze Python esterne. Un cookie di
sessione copiato manualmente è disponibile come alternativa quando Fastweb
blocca il login automatico.

> Il progetto non è affiliato né supportato da Fastweb. L’API non è pubblica e
> può cambiare senza preavviso.

## Entità disponibili

- **Sensori e controlli:** potenza istantanea, picco di potenza di oggi,
  consumo cumulativo per la dashboard Energia, potenza contrattuale,
  percentuale utilizzata e potenza disponibile;
- **Storico:** consumo dell’ultimo giorno, degli ultimi 7 e 30 giorni, più la
  stima del portale per elettrodomestico (frigorifero, lavatrice, standby, …),
  aggiornati ogni ora;
- **Avvisi:** consumo vicino al limite configurabile ed evento **Notifica del
  portale** per ogni nuova notifica Fastweb (potenza superata, interruzione di
  fornitura, …) con titolo e testo;
- **Configurazione:** LED, buzzer, notifiche Fastweb, soglia mensile e date
  della modalità vacanza;
- **Diagnostica:** connessione Plug, dati non aggiornati, tempo di risposta API,
  ultimo aggiornamento e notifiche non lette.

Le impostazioni sono rilette periodicamente e aggiornate subito dopo ogni
comando. Stato della Plug e impostazioni che Fastweb smette di restituire
diventano non disponibili dopo alcuni cicli, invece di mostrare valori vecchi.
La disattivazione contrattuale del servizio non viene esposta in Home
Assistant.

## Servizi e blueprint

`fastweb_power_control.set_holiday_period` scrive entrambe le date di vacanza e
l’avviso modalità vacanza in un’unica richiesta, così il portale non vede mai un
intervallo non valido:

```yaml
action: fastweb_power_control.set_holiday_period
data:
  start: "2026-08-01"
  end: "2026-08-21"
  enable: true
```

Il [blueprint di distacco carichi](blueprints/automation/fastweb_power_control/power_limit_load_shedding.yaml)
spegne i carichi scelti quando l’uso della potenza contrattuale resta sopra una
soglia, e può inviare una notifica.

## Installazione con HACS

Il repository deve essere pubblico su GitHub prima di poter essere installato.

1. In HACS apri **Integrations → menu → Custom repositories**.
2. Aggiungi
   `https://github.com/giuseppe99barchetta/fastweb-power-control-ha` come
   repository di tipo **Integration**.
3. Cerca e installa **Fastweb Power Control**.
4. Riavvia Home Assistant.
5. Apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione** e
   seleziona **Fastweb Power Control**.
6. Inserisci username, password MyFastweb e intervallo di aggiornamento. Se il
   login automatico è bloccato dopo un reCAPTCHA, inserisci anche il **Cookie
   di sessione** facoltativo come descritto sotto.

L’intervallo e la soglia dell’avviso di potenza possono essere cambiati
successivamente tramite **Configura**; credenziali e cookie di sessione tramite
**Riconfigura**.
Home Assistant 2026.3 o successivo è richiesto.

L’intervallo indica ogni quanto Home Assistant interroga Fastweb, non ogni
quanto Fastweb produce un nuovo campione. Fastweb può mantenere lo stesso
valore per circa un minuto: con un intervallo di 30 secondi due letture
consecutive possono quindi coincidere. Imposta 60 secondi per evitare richieste
ridondanti, oppure 30 secondi per rilevare prima il campione successivo.

Il file diagnostico completo si scarica dalla pagina dell’integrazione tramite
il menu **⋮ → Scarica diagnostica**; non compare come entità. Credenziali,
cookie e token non vengono inclusi.

## Autenticazione e rinnovo cookie

Il flusso di configurazione verifica subito le credenziali. L’integrazione:

1. mantiene una sessione Fastweb e i relativi cookie nella configurazione;
2. applica automaticamente ogni `Set-Cookie` ricevuto;
3. riutilizza il cookie persistente `FWB_RM` per rinnovare la sessione;
4. effettua nuovamente il login quando la sessione scade o Home Assistant si
   riavvia;
5. avvia il flusso di riautenticazione se le credenziali non sono più valide.

Nella norma non serve inserire il cookie. Se Fastweb blocca il login automatico
dopo un reCAPTCHA (lo segnala un avviso in Riparazioni), accedi manualmente a MyFastweb e copia il valore
`FWB_RM=...` (oppure l'intero header `Cookie`) della richiesta verso
`fastweb.it` nel campo **Cookie di sessione**. Il valore equivale a una
credenziale: non pubblicarlo né includerlo in segnalazioni. L'integrazione ne
gestisce il rinnovo e lo esclude dalla diagnostica. Il progetto non tenta di
aggirare reCAPTCHA o altre protezioni anti-bot.

## Energia in kWh

Il consumo cumulativo viene calcolato dai campioni timestamped restituiti da
Fastweb, conservato ai riavvii e può essere selezionato direttamente come
consumo di rete nella dashboard **Energia**. I buchi superiori a dieci minuti
non vengono stimati.

## Installazione manuale

Copia `custom_components/fastweb_power_control` nella directory
`/config/custom_components/` di Home Assistant, riavvia e aggiungi
l’integrazione dalla UI.

## Client diagnostico

```powershell
python .\tools\fastweb_power_control.py `
  --credentials-file .\fastweb_power_control.credentials
```

`tools/configuration.yaml.example` mostra il vecchio sensore `command_line`
basato sullo stesso client.

Il file credenziali, escluso da Git, contiene:

```json
{"username":"IL_TUO_USERNAME","password":"LA_TUA_PASSWORD"}
```

## MQTT e accesso diretto alla Plug

La Plug analizzata non espone porte TCP locali comuni. Le richieste DNS
indicano, tra gli altri, il broker
`mqtt.prod.smart-power-control.digiwatt.energy`. Il broker accetta TLS sulle
porte 8883 e 443, ma rifiuta connessioni anonime o con credenziali arbitrarie:
servono identità, token o certificati provisionati e topic autorizzati.

Il traffico catturato dal router mostra destinazioni e frequenza, ma TLS 1.3
protegge payload e credenziali. Per questo l’API MyFastweb è attualmente la via
più pratica e manutenibile; l’alternativa di ricerca è analizzare il
provisioning dell’app Android durante una nuova associazione della Plug.

## Sostieni il progetto

Se questa integrazione ti è utile, puoi supportarne lo sviluppo offrendo un
caffè su Ko-fi.

<p align="center">
  <a href="https://ko-fi.com/ciuse99">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Supportami su Ko-fi">
  </a>
</p>

## Sviluppo

```bash
pip install -r requirements_test.txt
python -m pytest
python -m ruff check .
```

I test richiedono Python 3.14 e l’ambiente di test di Home Assistant, che si
installa su Linux, macOS o WSL. Il workflow GitHub esegue HACS Action,
hassfest, Ruff e i test a ogni push e pull request.
