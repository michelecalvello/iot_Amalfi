# iot_Amalfi – Portale dei dati di monitoraggio

Dati di monitoraggio idrologico (pioggia, contenuto d'acqua e potenziale matriciale nel suolo, livello idrometrico) ad Amalfi (SA). Università di Salerno – Dipartimento di Ingegneria Civile.

Riferimento temporale unico: **UTC+1** (ora solare, senza ora legale).

## Pipeline

```bash
export INPUT_DIR=<cartella con i file Excel>   OUT_DIR=.
python pipeline/build_catalog.py    # catalog.json + series.csv
python pipeline/standardize.py      # data/ + arricchisce catalog.json
```

Per aggiungere uno strumento: stazione in `STATIONS`, strumento in `INSTRUMENTS`
(con `file_pattern`), regola in `classify()` dentro `pipeline/build_catalog.py`; eventuali
regole QC in `pipeline/qc_rules.json`. Poi rieseguire i due script.

## Struttura

```
catalog.json            metadati: stazioni, strumenti, serie, percorsi dei file, riepilogo QC
series.csv              vista piatta del catalogo (Excel)
pipeline/               script di generazione e regole QC (qc_rules.json)
data/raw/<serie>/<anno>.csv   time,value,flag          dato originale
data/agg/<serie>_1h.csv       time,value,[min],max,n,coverage   aggregato orario
data/agg/<serie>_1d.csv       idem, giornaliero
data/qc_log.csv         elenco dei valori segnalati e regola applicata
```

- `time`: `YYYY-MM-DD HH:MM` in UTC+1
- `flag`: 0 valido · 1 sospetto · 2 errato (escluso dagli aggregati)
- Aggregati: media per grandezze istantanee (etichetta = inizio intervallo);
  somma per la pioggia (dato riferito all'intervallo che termina al timestamp;
  l'etichetta indica l'inizio del periodo di cumulo).
- `coverage`: frazione di dati presenti rispetto al passo nominale (1 = completo).

## Fonti dei dati

- Stazione S3 (sensori METER, idrometro Arantec) e pluviometro Arantec: Università di Salerno.
- Pluviometri 21753 (Amalfi) e 51667 (Amalfi-Pogerola): Centro Funzionale Multirischi
  della Protezione Civile – Regione Campania.
