"""Build data.json from audience_data.csv.

    python build_data_json.py                       # writes data.new.json next to this script, changes nothing else
    python build_data_json.py --replace             # backs up data.json, then replaces it with the new file
    python run_audience.py --build                  # the same thing, from the main script

Rules
  * only audiences that have a real value in the CSV are written (blank = left out, nothing is guessed or taken from the sample)
  * counts above 0 and under 1,000 are written as 999 (same rule as the page's upload panel)
  * yearly new moms is the manual value if you typed one, otherwise 0
  * geography and market spend come from the CSV when you have typed values, otherwise from the current data.json (still marked sample)
  * the same checks as the page's Checks tab run first; if any fails nothing is written (use --force to write anyway)
  * "as of" is the newest updated_on of a database value
  * the file is written in the same readable layout the page's "Download data file" button uses
"""
import argparse, datetime as dt, json, os, shutil, sys
import pandas as pd

FOLDER = os.path.dirname(os.path.abspath(__file__))
ORDER = ["India", "Indonesia", "Malaysia", "Philippines", "Other ASEAN"]
MACROS = ["Kids", "Pets", "Women", "Senior & health"]


def mask(n):
    return 999 if 0 < n < 1000 else int(n)


def _i(v):
    return None if pd.isna(v) else int(round(float(v)))


def _val(df, tab, metric):
    d = df[(df["tab"] == tab) & (df["metric"] == metric) & df["value"].notna()]
    return d


def build(df, base):
    """df: the CSV as a DataFrame, base: the current data.json (dict). Returns (new data dict, list of problems, list of notes)."""
    df = df.fillna({"macro": "", "micro": "", "group": "", "nano": "", "source": "", "updated_on": ""})
    rank = {c: i for i, c in enumerate(ORDER)}
    notes = []

    # ---- totals
    UNIQUE = {}
    t = df[df["tab"] == "totals"]
    for c in ORDER:
        m = t[(t["country"] == c) & (t["metric"] == "unique_moms")]["value"].dropna()
        p = t[(t["country"] == c) & (t["metric"] == "data_points")]["value"].dropna()
        if len(m) and len(p): UNIQUE[c] = [_i(m.iloc[0]), _i(p.iloc[0])]
        else: notes.append(f"no country total for {c}, left out")

    def pairs(tab, keys):
        """{key tuple: {metric: value}} for rows of a tab that have a value."""
        out = {}
        for r in df[(df["tab"] == tab) & df["value"].notna()].itertuples():
            out.setdefault(tuple(getattr(r, k) for k in keys), {})[r.metric] = r.value
        return out

    # ---- macro, micro, nano (order follows the CSV, which follows the page)
    mac = pairs("macro", ["country", "macro"]); mic = pairs("micro", ["country", "macro", "micro"])
    nan = pairs("nano", ["country", "macro", "micro", "group", "nano"])
    MACRO_ROWS = [[c, m, mask(v["moms_on_file"]), _i(v.get("data_points", 0)), _i(v.get("yearly_new_moms", 0))]
                  for (c, m), v in mac.items() if v.get("moms_on_file", 0) > 0 and c in UNIQUE]
    MICRO_ROWS = [[c, m, mi, mask(v["moms_on_file"]), _i(v.get("data_points", 0)), _i(v.get("yearly_new_moms", 0))]
                  for (c, m, mi), v in mic.items() if v.get("moms_on_file", 0) > 0 and (c, m) in mac]
    micros_ok = {(r[0], r[1], r[2]) for r in MICRO_ROWS}
    NANO_ROWS = [[c, m, mi, g, n, mask(v["moms_on_file"]), _i(v.get("data_points", 0)), None]
                 for (c, m, mi, g, n), v in nan.items() if v.get("moms_on_file", 0) > 0 and (c, m, mi) in micros_ok]
    # a nano a hair above its micro (< 0.5%) is two queries disagreeing by a few moms: cap it at the micro and say so; bigger gaps stay as check failures
    mic_m = {(r[0], r[1], r[2]): r[3] for r in MICRO_ROWS}
    for r in NANO_ROWS:
        cap = mic_m[(r[0], r[1], r[2])]
        if cap < r[5] <= cap * 1.005: notes.append(f'{r[0]}: nano "{r[4]}" under "{r[2]}" was {r[5] - cap} above its micro, capped'); r[5] = cap
    key = lambda r: rank.get(r[0], 99)
    MACRO_ROWS.sort(key=key); MICRO_ROWS.sort(key=key); NANO_ROWS.sort(key=key)   # stable: keeps CSV order inside a country

    # ---- manual parts: geography and market spend. A typed value wins, otherwise the current data.json stays.
    GEO = json.loads(json.dumps(base.get("GEO", {}))); COVER = json.loads(json.dumps(base.get("COVER", {})))
    geo_typed = 0
    for r in df[(df["tab"] == "geography") & df["value"].notna()].itertuples():
        for area in GEO.get(r.country, {}).get(r.micro, []):
            if area[0] == r.nano: area[1] = float(r.value); geo_typed += 1
    spend_typed = 0
    for r in df[(df["tab"] == "market") & df["value"].notna()].itertuples():
        COVER[r.country] = {"spend": float(r.value)}; spend_typed += 1

    # ---- settings
    dates = df[(df["source"] == "db") & df["value"].notna() & (df["updated_on"] != "")]["updated_on"]
    st = json.loads(json.dumps(base.get("settings", {})))
    st["asOf"] = dates.max() if len(dates) else st.get("asOf", "")
    st["hero"] = {"moms": f"{sum(v[0] for v in UNIQUE.values()) // 10**6}M+", "points": f"{sum(v[1] for v in UNIQUE.values()) // 10**6}M+"}
    st["geoSample"] = geo_typed == 0
    missing = [m for m in MACROS if not any(r[1] == m for r in MACRO_ROWS)]
    yearly_blank = not any(r[4] for r in MACRO_ROWS)
    st["sample"] = bool(missing or yearly_blank or st["geoSample"] or not spend_typed)
    st["note"] = ("Counts are from the WOOP database as of " + st["asOf"] + ". "
                  + ("Not yet filled: " + ", ".join(missing) + ". " if missing else "")
                  + ("Yearly new moms, geography and market spend are still sample or blank." if st["sample"] else ""))
    if missing: notes.append("no numbers yet for: " + ", ".join(missing))
    if yearly_blank: notes.append("yearly new moms is blank, written as 0")
    if not geo_typed: notes.append("geography: kept from the current data.json (sample)")
    if not spend_typed: notes.append("market spend: kept from the current data.json (sample)")

    D = {"settings": st, "UNIQUE": UNIQUE, "COVER": COVER, "MACRO_ROWS": MACRO_ROWS, "MICRO_ROWS": MICRO_ROWS, "NANO_ROWS": NANO_ROWS, "GEO": GEO}
    return D, check(D), notes


def check(D):
    """The same checks as the page's Checks tab."""
    w, mac, mic = [], {}, {}
    if not D["settings"].get("asOf"): w.append('No "as of" date.')
    for r in D["MACRO_ROWS"]:
        mac[(r[0], r[1])] = r
        if r[0] not in D["UNIQUE"]: w.append(f'{r[0]}: no country total, so its macro audiences cannot be checked.')
        elif r[2] > D["UNIQUE"][r[0]][0]: w.append(f'{r[0]}: "{r[1]}" has more moms than the country total.')
    for r in D["MICRO_ROWS"]:
        m = mac.get((r[0], r[1]))
        if not m: w.append(f'{r[0]}: micro "{r[2]}" has no macro row for {r[1]}.'); continue
        if r[3] > m[2]: w.append(f'{r[0]}: "{r[2]}" has more moms than its macro {r[1]}.')
        if r[2].startswith("All ") and r[3] != m[2]: w.append(f'{r[0]}: "{r[2]}" should equal its macro {r[1]}.')
        mic[(r[0], r[1], r[2])] = r
    for r in D["NANO_ROWS"]:
        p = mic.get((r[0], r[1], r[2]))
        if not p: w.append(f'{r[0]}: nano "{r[4]}" sits under "{r[2]}", which has no micro row.')
        elif r[5] > p[3]: w.append(f'{r[0]}: nano "{r[4]}" has more moms than its micro "{r[2]}".')
    for c, views in D["GEO"].items():
        for v, areas in views.items():
            s = sum(a[1] for a in areas)
            if abs(s - 100) > 0.6: w.append(f"Geography {c} / {v} adds up to {round(s, 1)}%, not 100%.")
    return w


def dumps(D):
    """Same layout as the page's Download button: settings indented, one row per line."""
    J = lambda x: json.dumps(x, ensure_ascii=False)
    row = lambda x: "[" + ", ".join(row(i) for i in x) + "]" if isinstance(x, list) else J(x)
    obj = lambda o, ind, fn: "{\n" + ",\n".join(f"{ind}  {J(k)}: {fn(o[k])}" for k in o) + f"\n{ind}}}"
    rows = lambda a: "[\n" + ",\n".join("    " + row(r) for r in a) + "\n  ]"
    geo = obj(D["GEO"], "  ", lambda views: obj(views, "    ", lambda areas: "[\n" + ",\n".join("        " + row(r) for r in areas) + "\n      ]").replace("\n    ", "\n      "))
    return ("{\n  \"settings\": " + json.dumps(D["settings"], ensure_ascii=False, indent=2).replace("\n", "\n  ")
            + ",\n  \"UNIQUE\": " + obj(D["UNIQUE"], "  ", row) + ",\n  \"COVER\": " + obj(D["COVER"], "  ", row)
            + ",\n  \"MACRO_ROWS\": " + rows(D["MACRO_ROWS"]) + ",\n  \"MICRO_ROWS\": " + rows(D["MICRO_ROWS"])
            + ",\n  \"NANO_ROWS\": " + rows(D["NANO_ROWS"]) + ",\n  \"GEO\": " + geo + "\n}\n")


def main(csv=None, base_path=None, out=None, replace=False, force=False):
    csv = csv or os.path.join(FOLDER, "audience_data.csv")
    base_path = base_path or os.path.join(FOLDER, "data.json")
    out = out or os.path.join(FOLDER, "data.new.json")
    if not os.path.exists(base_path): sys.exit(f"Put the current data.json next to this script (or pass --base). Not found: {base_path}")
    base = json.load(open(base_path, encoding="utf-8"))
    D, problems, notes = build(pd.read_csv(csv, dtype={"updated_on": str}), base)
    for n in notes: print("note:", n)
    print(f"countries {len(D['UNIQUE'])}, macro {len(D['MACRO_ROWS'])}, micro {len(D['MICRO_ROWS'])}, nano {len(D['NANO_ROWS'])}, as of {D['settings']['asOf']}")
    if problems:
        print(f"\n{len(problems)} check(s) failed:")
        for p in problems[:40]: print("  -", p)
        if len(problems) > 40: print(f"  ... and {len(problems) - 40} more")
        if not force: sys.exit("Nothing written. Fix the numbers (or run with --force to write anyway).")
    else: print("all checks passed")
    text = dumps(D); json.loads(text)   # must stay valid JSON
    open(out, "w", encoding="utf-8").write(text); print("wrote", out)
    if replace:
        bak = base_path.replace(".json", f".backup-{dt.date.today().isoformat()}.json")
        shutil.copy(base_path, bak); shutil.copy(out, base_path); print(f"replaced {base_path} (old one saved as {bak})")
    return D


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv"); ap.add_argument("--base", help="current data.json (default: next to this script)"); ap.add_argument("--out")
    ap.add_argument("--replace", action="store_true"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args(); main(a.csv, a.base, a.out, a.replace, a.force)
