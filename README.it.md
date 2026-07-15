<p align="center">
  <img src="custom_components/fastweb_power_control/brand/logo.png" alt="Fastweb" width="226">
</p>

# Fastweb Power Control per Home Assistant

[English](README.md)

Integrazione custom non ufficiale per leggere e configurare Fastweb Power
Control da Home Assistant. Usa gli stessi endpoint privati del portale
MyFastweb: non richiede MQTT, dipendenze Python esterne o cookie copiati a
mano.

> Il progetto non è affiliato né supportato da Fastweb. L’API non è pubblica e
> può cambiare senza preavviso.

## Entità disponibili

- **Sensori e controlli:** potenza istantanea, consumo cumulativo per la
  dashboard Energia, potenza contrattuale, percentuale utilizzata e potenza
  disponibile;
- **Avvisi:** consumo vicino al limite configurabile;
- **Configurazione:** LED, buzzer, notifiche Fastweb, soglia mensile e date
  della modalità vacanza;
- **Diagnostica:** connessione Plug, dati non aggiornati, tempo di risposta API
  e notifiche non lette.

Le impostazioni sono rilette periodicamente e aggiornate subito dopo ogni
comando. Prima di attivare la modalità vacanza, imposta entrambe le date. La
disattivazione contrattuale del servizio non viene esposta in Home Assistant.

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
6. Inserisci username, password MyFastweb e intervallo di aggiornamento.

L’intervallo e la soglia dell’avviso di potenza possono essere cambiati
successivamente tramite **Configura**.
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

1. mantiene una sessione Fastweb in memoria;
2. applica automaticamente ogni `Set-Cookie` ricevuto;
3. riutilizza il cookie persistente `FWB_RM` per rinnovare la sessione;
4. effettua nuovamente il login quando la sessione scade o Home Assistant si
   riavvia;
5. avvia il flusso di riautenticazione se le credenziali non sono più valide.

Non serve alcun file cookie. Se Fastweb richiede un reCAPTCHA, accedi una volta
dal sito e riprova: il progetto non tenta di aggirarlo.

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
python .\fastweb_power_control.py --self-test
python .\fastweb_power_control.py `
  --credentials-file .\fastweb_power_control.credentials
```

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

```powershell
python .\fastweb_power_control.py --self-test
python -m ruff check .
```

Il workflow GitHub esegue HACS Action e hassfest a ogni push e pull request.
