"""
build_catalog.py — genera il catalogo metadati delle serie temporali (passo 1).

Input : file Excel grezzi (uno per anno/strumento) in INPUT_DIR
Output: catalog.json (stazioni, strumenti, serie, file sorgente)
        series.csv   (vista piatta delle serie, editabile in Excel)

RIFERIMENTO TEMPORALE: UTC+1 (ora solare italiana, CET, senza ora legale)
per tutte le misure. I timestamp sono scritti in ISO 8601 con offset "+01:00".

Le informazioni "curate" (stazioni, strumenti, regole di riconoscimento
delle colonne, note di qualità) sono definite qui sotto; periodo, passo,
lacune e statistiche sono calcolati automaticamente dai dati.
"""
import json, re, glob, os, math
from datetime import datetime, timezone, timedelta
import pandas as pd

INPUT_DIR = os.environ.get("INPUT_DIR", ".")
OUT_DIR = os.environ.get("OUT_DIR", ".")
TZ = timezone(timedelta(hours=1))           # UTC+1 fisso
GAP_REPORT_H = 24                           # lacune elencate nel catalogo se > 24 h

def iso(ts):
    return ts.to_pydatetime().replace(tzinfo=TZ).isoformat(timespec="minutes")

# ----------------------------------------------------------------------------
# 1. STAZIONI (siti di monitoraggio)
# ----------------------------------------------------------------------------
STATIONS = {
    "AMF_S3": {
        "name": "Amalfi – Stazione S3",
        "site": "Amalfi", "municipality": "Amalfi (SA)",
        "lat": 40.641976286697705, "lon": 14.59616756640533, "elevation_m": None,
        "owner": "Università di Salerno",
        "notes": "Nodo METER (suolo) e idrometro Arantec sul torrente.",
    },
    "AMF_ARA": {
        "name": "Amalfi – Pluviometro Arantec",
        "site": "Amalfi", "municipality": "Amalfi (SA)",
        "lat": 40.65303852484501, "lon": 14.567404247139883, "elevation_m": None,
        "owner": "Università di Salerno",
        "notes": "Pluviometro dedicato, a circa 2,7 km a ONO della stazione S3.",
    },
}

# Pluviometri della rete del Centro Funzionale Multirischi (Regione Campania)
def _cf(code, name, municipality, lat, lon, elev):
    return {"name": f"{name} (CF {code})", "site": municipality.split(" (")[0], "municipality": municipality,
            "lat": lat, "lon": lon, "elevation_m": elev,
            "owner": "Centro Funzionale Multirischi – Regione Campania", "external_code": code,
            "notes": "Stazione della rete regionale; dati forniti con sola colonna 'Time UTC+1'."}

CF_STATIONS = {   # codice: (nome, comune, lat, lon, quota m s.l.m., pattern file)
    "21753": ("Amalfi",            "Amalfi (SA)",  40.62227778, 14.57958333, 114, r"^AMALFI_PLUVIOMETRO_CF_\d{4}\.xlsx$"),
    "51667": ("Amalfi-Pogerola",   "Amalfi (SA)",  40.63827778, 14.59083333, 372, r"^AMALFI-POGEROLA_PLUVIOMETRO_CF_\d{4}\.xlsx$"),
    "51663": ("Scala-S.Caterina",  "Scala (SA)",   40.66047222, 14.60338889, 453, r"^SCALA-S\.CATERINA_PLUVIOMETRO_CF_\d{4}\.xlsx$"),
    "21767": ("Agerola",           "Agerola (NA)", 40.63825,    14.545,      623, r"^AGEROLA_PLUVIOMETRO_CF_\d{4}\.xlsx$"),
    "36428": ("Agerola METEO",     "Agerola (NA)", 40.64683333, 14.54061111, 848, r"^AGEROLA_METEO_1_PLUVIOMETRO_CF_\d{4}\.xlsx$"),
}
for _code, (_n, _m, _la, _lo, _el, _pat) in CF_STATIONS.items():
    STATIONS[f"CF_{_code}"] = _cf(_code, _n, _m, _la, _lo, _el)

# Stazioni S1, S2, S4, S5 (sensori Aranet di umidità del suolo): nei pressi di S3, stesse coordinate
for _n in (1, 2, 4, 5):
    STATIONS[f"AMF_S{_n}"] = {
        "name": f"Amalfi – Stazione S{_n}",
        "site": "Amalfi", "municipality": "Amalfi (SA)",
        "lat": STATIONS["AMF_S3"]["lat"], "lon": STATIONS["AMF_S3"]["lon"], "elevation_m": None,
        "owner": "Università di Salerno",
        "notes": "Sensori Aranet di umidità del suolo. Coordinate coincidenti con la stazione S3 "
                 "(stazione nei pressi di S3; posizione esatta da definire).",
    }


# ----------------------------------------------------------------------------
# 2. STRUMENTI (logger / sensori fisici) e riconoscimento file
# ----------------------------------------------------------------------------
INSTRUMENTS = {
    "AMF_S3_METER": {"station_id": "AMF_S3", "manufacturer": "METER Group",
                     "type": "Datalogger con sensori TEROS 10 (contenuto d'acqua) e TEROS 21 (potenziale, temperatura)",
                     "file_pattern": r"^Amalfi_Meter_S3_\d{4}\.xlsx$"},
    "AMF_S3_ARA_STAGE": {"station_id": "AMF_S3", "manufacturer": "Arantec",
                         "type": "Idrometro (livello torrente)",
                         "file_pattern": r"^Amalfi_Arantec_S3stream_water_level_\d{4}\.xlsx$"},
    "AMF_ARA_RAIN": {"station_id": "AMF_ARA", "manufacturer": "Arantec",
                     "type": "Pluviometro",
                     "file_pattern": r"^Amalfi_Arantec_pluvio_\d{4}\.xlsx$"},
}
for _n in (1, 2, 4, 5):
    INSTRUMENTS[f"AMF_S{_n}_ARANET"] = {"station_id": f"AMF_S{_n}", "manufacturer": "Aranet",
                                        "type": "Sensori di umidità del suolo (registrazione a 1 minuto)",
                                        "file_pattern": rf"^Amalfi_Aranet_S{_n}_\d{{4}}\.xlsx$"}
for _code, (_n, _m, _la, _lo, _el, _pat) in CF_STATIONS.items():
    INSTRUMENTS[f"CF_{_code}_RAIN"] = {"station_id": f"CF_{_code}", "manufacturer": "Centro Funzionale Regione Campania",
                                      "type": "Pluviometro", "file_pattern": _pat}


# ----------------------------------------------------------------------------
# 3. GRANDEZZE (vocabolario controllato)
# ----------------------------------------------------------------------------
VARIABLES = {
    "rain":   {"label_it": "Pioggia", "label_en": "Rainfall", "unit": "mm",
               "aggregation": "sum", "plot": "bar",
               "notes": "Altezza di pioggia caduta nell'intervallo che termina al timestamp."},
    "vwc":    {"label_it": "Contenuto d'acqua volumetrico", "label_en": "Volumetric water content",
               "unit": "m3/m3", "aggregation": "mean", "plot": "line"},
    "psi":    {"label_it": "Potenziale matriciale", "label_en": "Matric potential",
               "unit": "kPa", "aggregation": "mean", "plot": "line",
               "notes": "Valori negativi = suzione. TEROS 21: accuratezza dichiarata tra -9 e -100 kPa; "
                        "valori > -9 kPa (prossimi alla saturazione) sono indicativi."},
    "t_soil": {"label_it": "Temperatura del suolo", "label_en": "Soil temperature",
               "unit": "°C", "aggregation": "mean", "plot": "line"},
    "sm":     {"label_it": "Umidità del suolo (Aranet)", "label_en": "Soil moisture (Aranet sensor)",
               "unit": "%", "aggregation": "mean", "plot": "line",
               "notes": "Indice relativo del sensore Aranet (scala circa 0-90), non un contenuto d'acqua "
                        "volumetrico calibrato: non confrontabile in valore assoluto con i TEROS 10 (m3/m3). "
                        "Unità provvisoria."},
    "stage":  {"label_it": "Livello idrometrico", "label_en": "Stream water level",
               "unit": "cm", "aggregation": "mean", "plot": "line"},
}

# ----------------------------------------------------------------------------
# 4. REGOLE: (strumento, intestazione colonna) -> serie
#    series_id = <STAZIONE>_<GRANDEZZA>[_<PROFONDITÀ cm, 3 cifre>]
# ----------------------------------------------------------------------------
def classify(instrument_id, col):
    station = INSTRUMENTS[instrument_id]["station_id"]
    none = {"depth_m": None, "sensor_model": None, "logger_port": None}
    if instrument_id == "AMF_S3_METER":
        m = re.match(r"Port(\d)-(T10|T21)-(\d+)cm(?:\((kPa|°C)\))?", col)
        if not m:
            return None
        port, sensor, depth, unit = int(m[1]), m[2], int(m[3]), m[4]
        if sensor == "T10":
            var, model = "vwc", "TEROS 10"
        else:
            var, model = ("psi" if unit == "kPa" else "t_soil"), "TEROS 21"
        code = {"vwc": "VWC", "psi": "PSI", "t_soil": "TSOIL"}[var]
        return f"{station}_{code}_{depth:03d}", {"variable": var, "depth_m": depth / 100,
                                                "sensor_model": model, "logger_port": port}
    if instrument_id.endswith("_ARANET"):
        m = re.match(r"^(\w+) \((\d+) cm\)-S\d+$", col)        # es. "0321A (15 cm)-S1"
        if not m:
            return None
        depth = int(m[2])
        return f"{station}_SM_{depth:03d}", {"variable": "sm", "depth_m": depth / 100,
                                            "sensor_model": "Aranet", "logger_port": None,
                                            "sensor_serial": m[1]}
    if instrument_id.endswith("_RAIN") and col.startswith("Rain"):
        return f"{station}_RAIN", {"variable": "rain", **none}
    if instrument_id == "AMF_S3_ARA_STAGE" and col.startswith("stream level"):
        return f"{station}_STAGE", {"variable": "stage", **none}
    return None

# Note di qualità (interpretazione) emerse dall'analisi dei dati — orari in UTC+1
QC_NOTES = {
    "AMF_S3_PSI_030": ["2023-11-09 12:45–13:10: transitorio di installazione, "
                       "valori fino a -2864 kPa da escludere."],
    "AMF_S3_PSI_060": ["2023-11-09 12:45–13:00: transitorio di installazione."],
    "AMF_S3_STAGE": ["Valore 266.0 cm ricorrente = probabile codice di errore/fondo scala (es. 2024-02-09 11:10).",
                     "2024-05-28 dalle 14:00: valori anomali (~134–209 cm), probabile intervento/manutenzione.",
                     "Passo nominale 15 min ma con registrazioni irregolari (es. 5 min, minuti non allineati)."],
    "AMF_ARA_RAIN": ["Confronto su 563 giorni comuni (apr 2024 – dic 2025): Arantec 2430 mm, in linea con "
                     "Scala-S.Caterina CF 51663 (2386 mm, 453 m) e Agerola METEO CF 36428 (2262 mm, 848 m), "
                     "correlazione giornaliera 0.96–0.97; superiore ad Amalfi CF 21753 (1678 mm, 114 m) in modo "
                     "coerente con l'effetto orografico. Quota del pluviometro da definire.",
                     "Inizio registrazioni 2024-04-02. La lacuna 12–15 apr 2024 coincide con quella dell'idrometro Arantec in S3."],
    "CF_51667_RAIN": ["Alcuni timestamp con millisecondi spuri (es. 23:50:00.004): arrotondati al minuto."],
    "CF_21767_RAIN": ["Dati 2025 disponibili solo dal 2025-02-16: lacuna 1 gen – 16 feb 2025."],
}
for _code in CF_STATIONS:   # nota comune a tutta la rete CF
    QC_NOTES.setdefault(f"CF_{_code}_RAIN", []).insert(0,
        "Lacune 2024 (19–21 mar, 5–9 giu, 10 giu–4 lug, 5–8 lug) comuni a tutte le stazioni CF: "
        "interruzione della rete/fornitura dati, non del sensore.")

# Sensori Aranet (S1, S2, S4, S5): note comuni e transitori di installazione (sensore ancora in aria)
SM_NOTE = ("Indice relativo di umidità del sensore Aranet (scala circa 0-90), non un contenuto d'acqua volumetrico "
           "calibrato: rispetto ai TEROS 10 di S3 alle stesse profondità la correlazione giornaliera è 0.8-0.96 ma la "
           "scala è diversa (circa 150-400 volte il VWC in m3/m3). Unità provvisoria. Registrazione a 1 minuto con "
           "secondi non allineati: arrotondata al minuto, duplicati risultanti rimossi.")
SM_DRY_NOTE = ("Valori ≈ 0.2-0.5 nei periodi estivi/autunnali: suolo molto secco (si ripetono nelle due estati e su "
               "più sensori, con risalita alle prime piogge), non considerati errori.")
SM_INSTALL = {   # transitorio di installazione (UTC+1): sensore in aria, valori 1-6, esclusi (flag 2)
    "AMF_S1_SM_015": ("2023-10-12 11:14", "2023-10-12 11:38"),
    "AMF_S1_SM_030": ("2023-10-12 10:17", "2023-10-12 11:35"),
    "AMF_S2_SM_015": ("2023-10-12 14:17", "2023-10-12 14:19"),
    "AMF_S2_SM_030": ("2023-10-12 14:16", "2023-10-12 14:18"),
    "AMF_S4_SM_015": ("2024-05-24 09:28", "2024-05-24 12:16"),
    "AMF_S4_SM_030": ("2024-05-24 08:59", "2024-05-24 12:12"),
    "AMF_S5_SM_015": ("2025-02-21 14:06", "2025-02-21 15:06"),
    "AMF_S5_SM_030": ("2025-02-21 13:55", "2025-02-21 15:01"),
    "AMF_S5_SM_045": ("2025-02-21 14:07", "2025-02-21 14:47"),
    "AMF_S5_SM_060": ("2025-02-21 14:05", "2025-02-21 14:25"),
}
for _sid, (_a, _b) in SM_INSTALL.items():
    QC_NOTES[_sid] = [SM_NOTE, f"{_a}–{_b[11:]}: transitorio di installazione (sensore in aria, valori 1-6), escluso."]
for _sid in ("AMF_S1_SM_015", "AMF_S5_SM_015", "AMF_S5_SM_045"):
    QC_NOTES[_sid].append(SM_DRY_NOTE)
QC_NOTES["AMF_S1_SM_015"].append("Registrazioni terminate il 2025-03-28.")
QC_NOTES["AMF_S2_SM_015"].append("Registrazioni terminate il 2024-11-06 (nel file 2025 è presente solo il sensore a 30 cm).")

# ----------------------------------------------------------------------------
# 5. SCANSIONE FILE
# ----------------------------------------------------------------------------
def match_instrument(fname):
    for iid, inst in INSTRUMENTS.items():
        if re.search(inst["file_pattern"], fname, re.I):
            return iid
    return None

series, files, gaps = {}, [], {}
for path in sorted(glob.glob(os.path.join(INPUT_DIR, "*.xlsx"))):
    fname = os.path.basename(path)
    clean = re.sub(r"^[0-9a-f]{8}-", "", fname)          # rimuove prefisso di upload
    iid = match_instrument(clean)
    if iid is None:
        print("!! file non riconosciuto:", fname); continue
    year = int(re.search(r"(\d{4})\.xlsx$", clean)[1])
    for sheet, df in pd.read_excel(path, sheet_name=None, engine="openpyxl").items():
        # Colonna B = 'Time UTC+1' -> riferimento temporale unico (arrotondato al minuto)
        t = pd.to_datetime(df.iloc[:, 1], errors="coerce").dt.round("min")
        has_local = bool(df.iloc[:, 0].notna().any())
        for col in df.columns[2:]:
            if not isinstance(col, str) or col.startswith("Unnamed"):
                continue                                  # colonne di servizio (calcolo offset)
            cl = classify(iid, col)
            if cl is None:
                continue
            sid, attrs = cl
            v = pd.to_numeric(df[col], errors="coerce")
            ok = v.notna() & t.notna()
            tt, vv = t[ok].reset_index(drop=True), v[ok]
            step = tt.diff().dt.total_seconds().div(60)
            for i in step.index[step > GAP_REPORT_H * 60]:
                gaps.setdefault(sid, []).append({"from": iso(tt[i - 1]), "to": iso(tt[i]),
                                                 "hours": round(step[i] / 60, 1)})
            files.append({"series_id": sid, "file": clean, "year": year, "sheet": sheet,
                          "column": col, "time_column": "Time UTC+1",
                          "local_time_column": "Time" if has_local else None,
                          "start": iso(tt.min()), "end": iso(tt.max()),
                          "n_values": int(ok.sum()), "n_rows": int(len(df)),
                          "step_min": float(step.median()),
                          "gaps_over_1h": int((step > 60).sum()),
                          "max_gap_h": round(float(step.max()) / 60, 1),
                          "min": float(vv.min()), "max": float(vv.max()),
                          "mean": round(float(vv.mean()), 4)})
            series.setdefault(sid, {"series_id": sid, "instrument_id": iid,
                                    "station_id": INSTRUMENTS[iid]["station_id"], **attrs})

# Modalità incrementale: i file Excel già elaborati possono non essere presenti in INPUT_DIR.
# Si parte dal catalogo esistente e si aggiornano solo i file/le serie scansionati (REBUILD=1: da zero).
# Per aggiungere un anno a una serie esistente servono comunque tutti i suoi file Excel (li rielabora standardize.py).
prev = {}
_prev_path = os.path.join(OUT_DIR, "catalog.json")
if os.path.exists(_prev_path) and os.environ.get("REBUILD") != "1":
    prev = json.load(open(_prev_path, encoding="utf-8"))
_scanned = {(f["file"], f["sheet"], f["column"]) for f in files}
files += [f for f in prev.get("source_files", []) if (f["file"], f["sheet"], f["column"]) not in _scanned]

# ----------------------------------------------------------------------------
# 6. ASSEMBLAGGIO
# ----------------------------------------------------------------------------
def label(s):
    v = VARIABLES[s["variable"]]
    d = f" {int(s['depth_m']*100)} cm" if s.get("depth_m") is not None else ""
    return f"{v['label_it']}{d} – {STATIONS[s['station_id']]['name']}"

out_series = []
for sid, s in sorted(series.items()):
    fs = sorted((f for f in files if f["series_id"] == sid), key=lambda f: f["start"])
    v = VARIABLES[s["variable"]]
    out_series.append({
        **s,
        "label": label(s),
        "unit": v["unit"],
        "aggregation": v["aggregation"],
        "step_min": min(f["step_min"] for f in fs),
        "start": fs[0]["start"],
        "end": max(f["end"] for f in fs),
        "n_values": sum(f["n_values"] for f in fs),
        "min": min(f["min"] for f in fs),
        "max": max(f["max"] for f in fs),
        "status": "active",
        "gaps_over_24h": gaps.get(sid, []),
        "qc_notes": QC_NOTES.get(sid, []),
        "sources": [{k: f[k] for k in ("file", "year", "sheet", "column")} for f in fs],
    })

_new_ids = {s["series_id"] for s in out_series}
out_series += [s for s in prev.get("series", []) if s["series_id"] not in _new_ids]   # serie non riscansionate
out_series.sort(key=lambda s: s["series_id"])

def dist_km(a, b):
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(h)), 2)

stations_out = []
for k, st in STATIONS.items():
    near = {o: dist_km(st, ost) for o, ost in STATIONS.items()
            if o != k and st["lat"] is not None and ost["lat"] is not None}
    stations_out.append({"station_id": k, **st, "distance_km": near or None})

catalog = {
    "catalog_version": prev.get("catalog_version", "0.2"),
    "generated": datetime.now(TZ).isoformat(timespec="seconds"),
    "conventions": {**prev.get("conventions", {}),
        "time_reference": "UTC+1 (ora solare italiana / CET, senza ora legale) per tutte le misure. "
                          "Timestamp in ISO 8601 con offset '+01:00'. Sorgente: colonna 'Time UTC+1' "
                          "dei file Excel, arrotondata al minuto. La colonna 'Time' (ora locale con "
                          "ora legale) non è usata.",
        "series_id": "<STAZIONE>_<GRANDEZZA>[_<PROFONDITÀ cm, 3 cifre>]",
        "depth_m": "Profondità sotto il piano campagna, positiva verso il basso, in metri.",
        "coordinates": "WGS84 (EPSG:4326), gradi decimali.",
    },
    "variables": {**prev.get("variables", {}), **VARIABLES},
    "stations": stations_out,
    "instruments": [{"instrument_id": k, **{kk: vv for kk, vv in v.items() if kk != "file_pattern"}}
                    for k, v in INSTRUMENTS.items()],
    "series": out_series,
    "source_files": files,
}

if "qc_rules" in prev:
    catalog["qc_rules"] = prev["qc_rules"]
os.makedirs(OUT_DIR, exist_ok=True)
with open(os.path.join(OUT_DIR, "catalog.json"), "w", encoding="utf-8") as fh:
    json.dump(catalog, fh, ensure_ascii=False, indent=2)

st_lookup = {s["station_id"]: s for s in stations_out}
flat = pd.DataFrame([{k: s[k] for k in ("series_id", "station_id", "instrument_id", "variable",
                       "label", "unit", "depth_m", "sensor_model", "logger_port", "aggregation",
                       "step_min", "start", "end", "n_values", "min", "max", "status")}
                     | {"lat": st_lookup[s["station_id"]]["lat"],
                        "lon": st_lookup[s["station_id"]]["lon"],
                        "n_gaps_over_24h": len(s["gaps_over_24h"]),
                        "qc_notes": " | ".join(s["qc_notes"]),
                        "source_files": "; ".join(x["file"] for x in s["sources"])}
                     for s in out_series])
flat.to_csv(os.path.join(OUT_DIR, "series.csv"), index=False, encoding="utf-8-sig")
print(flat[["series_id", "variable", "unit", "step_min", "start", "end", "n_values", "n_gaps_over_24h"]].to_string())
