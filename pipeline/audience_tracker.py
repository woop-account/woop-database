import json, datetime as dt
import pandas as pd

KEYS = ["tab", "country", "macro", "micro", "group", "nano", "metric"]
COLS = KEYS + ["value", "sample_value", "source", "updated_on", "note"]
DB_METRICS = {"unique_moms", "moms_on_file", "data_points"}          # filled by the notebook
MANUAL_METRICS = {"yearly_new_moms", "recruit_share", "geo_share", "spend_ready_women_m"}   # filled by hand

def init_from_data_json(path):
    """Build the first CSV from the page's current data.json. value and updated_on start blank everywhere; the page's current sample numbers go in sample_value for reference."""
    D = json.load(open(path, encoding="utf-8")); rows = []
    def add(tab, country, macro, micro, group, nano, metric, value, note=""):
        src = "manual" if metric in MANUAL_METRICS else "db"
        rows.append([tab, country, macro, micro, group, nano, metric, None, value, src, "", note])
    for c, (m, p) in D["UNIQUE"].items():
        add("totals", c, "", "", "", "", "unique_moms", m); add("totals", c, "", "", "", "", "data_points", p)
    for c, mac, m, p, y in D["MACRO_ROWS"]:
        add("macro", c, mac, "", "", "", "moms_on_file", m); add("macro", c, mac, "", "", "", "data_points", p); add("macro", c, mac, "", "", "", "yearly_new_moms", y)
    for c, mac, mic, m, p, y in D["MICRO_ROWS"]:
        add("micro", c, mac, mic, "", "", "moms_on_file", m); add("micro", c, mac, mic, "", "", "data_points", p); add("micro", c, mac, mic, "", "", "yearly_new_moms", y)
    for c, mac, mic, g, n, m, p, rs in D["NANO_ROWS"]:
        add("nano", c, mac, mic, g, n, "moms_on_file", m); add("nano", c, mac, mic, g, n, "data_points", p)
        if rs is not None: add("nano", c, mac, mic, g, n, "recruit_share", rs)
    for c, v in D["COVER"].items(): add("market", c, "", "", "", "", "spend_ready_women_m", v["spend"])
    for c, views in D["GEO"].items():
        for v, areas in views.items():
            for a, share, covers in areas: add("geography", c, "", v, "", a, "geo_share", share, covers)
    df = pd.DataFrame(rows, columns=COLS); df["value"] = pd.to_numeric(df["value"]); df["sample_value"] = pd.to_numeric(df["sample_value"]); return df

def load(path):
    return pd.read_csv(path, dtype={"updated_on": str, "note": str}).fillna({"updated_on": "", "note": "", "source": ""})

def upsert_db(df, new_rows, today=None):
    """new_rows: list of dicts with the KEYS and 'value' (a DB result). Updates value and stamps updated_on. Manual rows are never touched."""
    today = today or dt.date.today().isoformat()
    idx = {tuple(r): i for i, r in enumerate(df[KEYS].fillna("").astype(str).values.tolist())}
    for r in new_rows:
        k = tuple(str(r.get(c, "")) for c in KEYS)
        if k in idx:
            i = idx[k]
            if df.at[i, "source"] == "manual": continue
            df.at[i, "value"] = r["value"]; df.at[i, "updated_on"] = today
        else:
            df.loc[len(df)] = [*[r.get(c, "") for c in KEYS], r["value"], None, "db", today, ""]
            idx[k] = len(df) - 1
    return df

def stamp_manual(df, today=None):
    """After you type values into the manual rows: any manual row that has a value but no date gets today's date."""
    today = today or dt.date.today().isoformat()
    m = (df["source"] == "manual") & df["value"].notna() & (df["updated_on"] == "")
    df.loc[m, "updated_on"] = today
    return df

def append_history(hist_path, new_rows, today=None):
    today = today or dt.date.today().isoformat()
    h = pd.DataFrame([{**{c: r.get(c, "") for c in KEYS}, "value": r["value"], "run_date": today} for r in new_rows])
    h.to_csv(hist_path, mode="a", header=not __import__("os").path.exists(hist_path), index=False)
