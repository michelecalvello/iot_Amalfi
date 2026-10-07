"""
derive_rolling24h.py — passo 4: serie derivate di pioggia cumulata sulle ultime 24 ore.

Legge   : OUT_DIR/catalog.json (dopo standardize.py), qc_rules.json (blocco "rolling_24h"),
          OUT_DIR/data/raw/<pluviometro>/<anno>.csv
Scrive  : OUT_DIR/data/raw/<STAZIONE>_RAIN24H/<anno>.csv     time,value,flag
          OUT_DIR/data/agg/<STAZIONE>_RAIN24H_1h.csv / _1d.csv   time,value,max,n,coverage,flag
Aggiorna: OUT_DIR/catalog.json e OUT_DIR/series.csv (le serie derivate hanno "derived_from").
Lo script è idempotente: a ogni esecuzione rigenera tutte le serie RAIN24H (non tocca RAINCUM).

DEFINIZIONE
- Risoluzione originale: una riga per ogni dato di pioggia valido del pluviometro (stesso passo
  e stessi timestamp della serie di origine).
- value = pioggia caduta nelle 24 h che terminano al timestamp, cioè somma dei dati con
  timestamp in (t - 24 h, t], sui soli dati con flag < 2. Ogni dato di pioggia è riferito
  all'intervallo che termina al suo timestamp, quindi la finestra copre esattamente 24 h di pioggia.
- flag = 1 quando nella finestra mancano più di missing_minutes_threshold minuti di dati
  (lacune, dati errati scartati, prime 24 h della serie): il valore è probabilmente sottostimato.

AGGREGATI (etichetta = inizio intervallo, come per la pioggia)
- value = ultimo valore (cumulata 24 h a fine intervallo); max = massimo nell'intervallo
- n = numero di dati nell'intervallo; coverage = n / attesi; flag = massimo flag
"""
import json, os
import numpy as np
import pandas as pd

OUT_DIR = os.environ.get("OUT_DIR", ".")
CATALOG = os.path.join(OUT_DIR, "catalog.json")
RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qc_rules.json")
TFMT = "%Y-%m-%d %H:%M"
ISO = "%Y-%m-%dT%H:%M+01:00"
SUFFIX = "RAIN24H"
WINDOW_MIN = 24 * 60

VARIABLE = {
    "label_it": "Pioggia cumulata 24 h",
    "label_en": "24-hour rolling rainfall",
    "unit": "mm", "aggregation": "last", "plot": "line",
    "notes": "Pioggia caduta nelle 24 ore che terminano al timestamp (finestra mobile), alla risoluzione "
             "originale del pluviometro. Tratteggiata dove i dati mancanti rendono il valore sottostimato.",
}

catalog = json.load(open(CATALOG, encoding="utf-8"))
rules = json.load(open(RULES, encoding="utf-8"))["rolling_24h"]
MISS_THR = rules["missing_minutes_threshold"]
stations = {s["station_id"]: s for s in catalog["stations"]}

# idempotenza: via le serie RAIN24H precedenti
catalog["series"] = [s for s in catalog["series"] if s.get("variable") != "rain_24h"]
rain_series = [s for s in catalog["series"] if s["variable"] == "rain"]


def load_rain(s):
    parts = [pd.read_csv(os.path.join(OUT_DIR, s["data"]["raw"].replace("{year}", str(y))))
             for y in s["data"]["years"]]
    d = pd.concat(parts, ignore_index=True)
    d["time"] = pd.to_datetime(d["time"])
    d = d[d["flag"] < 2].sort_values("time").drop_duplicates("time").reset_index(drop=True)
    return d[["time", "value"]]


def rolling24(d, step_min):
    t = (d["time"].values.astype("datetime64[m]").astype("int64"))      # minuti
    v = d["value"].to_numpy(dtype="float64")
    cs = np.concatenate([[0.0], np.cumsum(v)])
    # j = primo indice con t > t_i - 24 h  (finestra (t-24h, t])
    j = np.searchsorted(t, t - WINDOW_MIN, side="right")
    i = np.arange(len(t))
    d = d.copy()
    d["r24"] = np.round(cs[i + 1] - cs[j], 2).clip(min=0)
    d["n_win"] = i - j + 1
    d["missing_min"] = (WINDOW_MIN - d["n_win"] * step_min).clip(lower=0)
    d["flag"] = (d["missing_min"] > MISS_THR).astype(np.int8)
    return d


def aggregate(d, step_min, rule):
    expected = {"1h": 60 / step_min, "1d": 1440 / step_min}[rule]
    freq = {"1h": "1h", "1d": "1D"}[rule]
    g = d.set_index("time")
    rs = g.resample(freq, closed="right", label="left")
    out = pd.DataFrame({"value": rs["r24"].last(), "max": rs["r24"].max(),
                        "n": rs["r24"].count(), "flag": rs["flag"].max()})
    out = out[out["n"] > 0].copy()
    out["coverage"] = (out["n"] / expected).clip(upper=1).round(3)
    out["n"] = out["n"].astype(int)
    out["flag"] = out["flag"].astype(int)
    out[["value", "max"]] = out[["value", "max"]].round(2)
    out = out[["value", "max", "n", "coverage", "flag"]]
    out.index = out.index.strftime(TFMT)
    out.index.name = "time"
    return out


os.makedirs(os.path.join(OUT_DIR, "data", "agg"), exist_ok=True)
new_series = []
for s in rain_series:
    sid = f"{s['station_id']}_{SUFFIX}"
    d = rolling24(load_rain(s), s["step_min"])

    raw_dir = os.path.join(OUT_DIR, "data", "raw", sid)
    os.makedirs(raw_dir, exist_ok=True)
    years = sorted(d["time"].dt.year.unique().tolist())
    for y in years:
        dy = d[d["time"].dt.year == y]
        pd.DataFrame({"time": dy["time"].dt.strftime(TFMT), "value": dy["r24"], "flag": dy["flag"]}) \
            .to_csv(os.path.join(raw_dir, f"{y}.csv"), index=False)
    for rule in ("1h", "1d"):
        aggregate(d, s["step_min"], rule).to_csv(os.path.join(OUT_DIR, "data", "agg", f"{sid}_{rule}.csv"))

    st = stations[s["station_id"]]
    imax = int(d["r24"].idxmax())
    counts = d["flag"].value_counts().to_dict()
    notes = [f"Serie derivata da {s['series_id']}: pioggia caduta nelle 24 h che terminano al timestamp "
             f"(finestra mobile, intervallo (t-24 h, t]), alla risoluzione originale ({s['step_min']:g} min), "
             f"calcolata sui dati con flag < 2.",
             f"Massimo 24 h: {d['r24'].iloc[imax]:.1f} mm, in data {d['time'].iloc[imax].strftime(TFMT)}.",
             f"flag 1 (tratteggio nel portale) = nella finestra mancano più di {MISS_THR} min di dati "
             f"(lacune, dati errati scartati, prime 24 h della serie): valore probabilmente sottostimato. "
             f"{counts.get(1, 0)} dati su {len(d)} segnalati."]
    new_series.append({
        "series_id": sid, "instrument_id": s["instrument_id"], "station_id": s["station_id"],
        "variable": "rain_24h", "depth_m": None, "sensor_model": None, "logger_port": None,
        "label": f"{VARIABLE['label_it']} – {st['name']}",
        "unit": "mm", "aggregation": "last", "step_min": s["step_min"],
        "start": d["time"].iloc[0].strftime(ISO), "end": d["time"].iloc[-1].strftime(ISO),
        "n_values": int(len(d)), "min": 0.0, "max": round(float(d["r24"].max()), 2),
        "status": "active",
        "gaps_over_24h": s["gaps_over_24h"],
        "qc_notes": notes, "sources": [],
        "derived_from": s["series_id"],
        "data": {"format": "csv: time,value,flag", "raw": f"data/raw/{sid}/{{year}}.csv", "years": years,
                 "agg_1h": f"data/agg/{sid}_1h.csv", "agg_1d": f"data/agg/{sid}_1d.csv"},
        "qc_summary": {"n_total": int(len(d)), "n_valid": int(counts.get(0, 0)),
                       "n_suspect": int(counts.get(1, 0)), "n_bad": 0, "duplicates_removed": 0},
    })
    print(f"{sid:20s} righe={len(d):7d}  flag1={counts.get(1, 0):7d}  max24h={d['r24'].max():6.1f} mm")

catalog["series"] = sorted(catalog["series"] + new_series, key=lambda x: x["series_id"])
catalog["variables"]["rain_24h"] = VARIABLE
catalog["conventions"]["derived_series"] = (
    catalog["conventions"].get("derived_series", "").split(" Pioggia cumulata 24 h")[0]
    + " Pioggia cumulata 24 h (variabile rain_24h, pipeline/derive_rolling24h.py): pioggia caduta nelle 24 h "
      "che terminano al timestamp, alla risoluzione originale del pluviometro; aggregati (data/agg): "
      "value = valore a fine intervallo, max = massimo nell'intervallo, etichetta = inizio intervallo; "
      "flag 1 = valore sottostimato per dati mancanti nella finestra (soglia in qc_rules.json -> rolling_24h).")
catalog["catalog_version"] = "0.5"
catalog["generated"] = pd.Timestamp.now(tz="Etc/GMT-1").strftime("%Y-%m-%dT%H:%M:%S+01:00")
with open(CATALOG, "w", encoding="utf-8") as fh:
    json.dump(catalog, fh, ensure_ascii=False, indent=2)

# series.csv: vista piatta (righe delle derivate rigenerate)
flat_path = os.path.join(OUT_DIR, "series.csv")
if os.path.exists(flat_path):
    flat = pd.read_csv(flat_path, encoding="utf-8-sig")
    flat = flat[~flat["series_id"].isin([x["series_id"] for x in new_series])]
    rows = [{**{k: x[k] for k in ("series_id", "station_id", "instrument_id", "variable", "label", "unit",
                                  "depth_m", "sensor_model", "logger_port", "aggregation", "step_min",
                                  "start", "end", "n_values", "min", "max", "status")},
             "lat": stations[x["station_id"]]["lat"], "lon": stations[x["station_id"]]["lon"],
             "n_gaps_over_24h": len(x["gaps_over_24h"]),
             "qc_notes": " | ".join(x["qc_notes"]), "source_files": ""} for x in new_series]
    flat = pd.concat([flat, pd.DataFrame(rows)], ignore_index=True)[flat.columns]
    flat.sort_values("series_id").to_csv(flat_path, index=False, encoding="utf-8-sig")
