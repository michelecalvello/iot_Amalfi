# iot_Amalfi – Portale dei dati di monitoraggio

**Portale:** https://michelecalvello.github.io/iot_Amalfi/

Dati di monitoraggio idrologico (pioggia, contenuto d'acqua e potenziale matriciale nel suolo, livello idrometrico) ad Amalfi (SA). Università di Salerno – Dipartimento di Ingegneria Civile.

Riferimento temporale unico: **UTC+1** (ora solare, senza ora legale).

## Pipeline

```bash
export INPUT_DIR=<cartella con i file Excel>   OUT_DIR=.
python pipeline/build_catalog.py    # catalog.json + series.csv
python pipeline/standardize.py      # data/ + arricchisce catalog.json
python pipeline/derive_cumulative.py  # serie derivate: pioggia cumulata dal 1 gennaio
python pipeline/derive_rolling24h.py  # serie derivate: pioggia cumulata sulle ultime 24 h
```

Modalità incrementale: `build_catalog.py` e `standardize.py` aggiornano solo i file Excel presenti in `INPUT_DIR`
(il resto del catalogo e dei dati resta com'è; `REBUILD=1` per ripartire da zero con tutti i file).
Per aggiungere un anno a una serie esistente servono tutti i suoi file Excel.

Per aggiungere uno strumento: stazione in `STATIONS`, strumento in `INSTRUMENTS`
(con `file_pattern`), regola in `classify()` dentro `pipeline/build_catalog.py`; eventuali
regole QC in `pipeline/qc_rules.json`. Poi rieseguire i due script.

### Pioggia cumulata dal 1 gennaio

`derive_cumulative.py` crea, per ogni pluviometro, la serie `<STAZIONE>_RAINCUM` (variabile `rain_cum`, mm)
con la pioggia cumulata dal 1 gennaio ore 00:00, azzerata a ogni anno. Calcolo sui soli dati con flag < 2.
- Il dato delle 00:00 del 1 gennaio chiude l'anno precedente (ogni dato di pioggia è riferito all'intervallo che termina al suo timestamp).
- Aggregati orari/giornalieri: `value` = cumulata a fine intervallo (etichetta = inizio intervallo); colonne `time,value,n,coverage,flag`.
- `flag` 1 = cumulata sottostimata per dati mancanti (tempo mancante nell'anno > `missing_hours_threshold`, soglie in `qc_rules.json` → `cumulative`); nel portale è tratteggiata.
- Le serie derivate hanno `derived_from` e `cumulative_years` (totali annui e ore mancanti) nel catalogo.
- Va rieseguito dopo ogni modifica ai dati di pioggia o alle regole QC (`build_catalog.py` rigenera il catalogo senza le derivate).

### Pioggia cumulata sulle ultime 24 ore

`derive_rolling24h.py` crea, per ogni pluviometro, la serie `<STAZIONE>_RAIN24H` (variabile `rain_24h`, mm)
con la pioggia caduta nelle 24 ore che terminano al timestamp (finestra mobile, intervallo (t-24 h, t]),
**alla risoluzione originale del pluviometro** (una riga per ogni dato di pioggia valido; passo 5 min per Arantec, 10 min per la rete CF).
Calcolo sui soli dati con flag < 2.
- Aggregati orari/giornalieri: `value` = valore a fine intervallo (etichetta = inizio intervallo), `max` = massimo nell'intervallo; colonne `time,value,max,n,coverage,flag`.
- `flag` 1 = nella finestra mancano più di `missing_minutes_threshold` minuti di dati (lacune, dati errati scartati, prime 24 h della serie): valore sottostimato; nel portale è tratteggiato (soglia in `qc_rules.json` → `rolling_24h`).
- Va rieseguito dopo ogni modifica ai dati di pioggia (dopo `derive_cumulative.py`; i due script non si sovrascrivono a vicenda).

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

- Stazione S3 (sensori METER, idrometro Arantec), stazioni S1, S2, S4, S5 (sensori Aranet di umidità del suolo, 1 minuto)
  e pluviometro Arantec: Università di Salerno. S1, S2, S4, S5 sono nei pressi di S3 e hanno le sue stesse coordinate.
- Pluviometri 21753 (Amalfi), 51667 (Amalfi-Pogerola), 51663 (Scala-S.Caterina), 21767 (Agerola)
  e 36428 (Agerola METEO): Centro Funzionale Multirischi della Protezione Civile – Regione Campania.

## Portale web

`index.html` + `assets/` — pagina statica (GitHub Pages), nessun backend.
- Selezione fino a **20 serie** contemporaneamente per stazione e grandezza, mappa delle stazioni, metadati (ⓘ).
- Grafico Plotly con asse del tempo unico: modalità **Pannelli** (un pannello per grandezza)
  o **Assi multipli** (un solo grafico, un asse Y per grandezza, pioggia come ietogramma rovesciato).
- Opzione *Piogge in pannelli separati*: un pannello per pluviometro, con scala comune.
- Il riquadro del grafico si ridimensiona trascinando l'angolo in basso a destra: i pannelli scalano di conseguenza.
- Risoluzione automatica in base all'intervallo: giornaliera (> 90 giorni), oraria (> 4 giorni),
  dato originale (≤ 4 giorni); oppure scelta manuale.
- Statistiche e esportazione CSV dell'intervallo visibile; lo stato della vista è nell'URL (condivisibile).

Per provarlo in locale: `python -m http.server` nella radice del repo e aprire http://localhost:8000.
