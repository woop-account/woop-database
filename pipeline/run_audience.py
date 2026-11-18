"""Fill audience_data.csv from the database (Metabase, database 67).

    export METABASE_API_KEY="your-new-key"        # never type the key into the notebook or a file
    python run_audience.py                        # runs everything
    python run_audience.py --only q3              # just totals, macros and micros
    python run_audience.py --workers 6 --step 500000

What it does
  1. backs up audience_data.csv, and drops the nano audiences that were removed from the page (removed_audiences.csv)
  2. Query 3  -> totals, macros (Kids, Pets, Women) and all micro audiences     (one pass over the database)
  3. Query 5  -> Pets nano audiences                                            (one pass over the database)
  Database rows are stamped with today's date. Manual rows (yearly recruitment, geography, market spend) are never touched.
  The CSV is saved after each pass, so nothing is lost if a later pass fails.
"""
import argparse, datetime as dt, os, shutil, sys
import pandas as pd
import audience_queries as q, audience_tracker as t, audience_runner as rn

URL = "https://woopworld.metabaseapp.com"
FOLDER = os.path.dirname(os.path.abspath(__file__))
CSV, HIST, REMOVED = (os.path.join(FOLDER, n) for n in ("audience_data.csv", "audience_history.csv", "removed_audiences.csv"))


COUNTRIES = {"India", "Indonesia", "Malaysia", "Philippines", "Other ASEAN"}


def clean_removed(df):
    stray = ~df["country"].isin(COUNTRIES)
    if stray.any(): print(f"dropping {int(stray.sum())} rows with a misspelled country, e.g. {sorted(set(df.loc[stray, 'country']))}")
    df = df[~stray].reset_index(drop=True)
    if not os.path.exists(REMOVED): return df
    gone = set(pd.read_csv(REMOVED)["nano_audience"])
    m = (df["tab"] == "nano") & df["nano"].isin(gone)
    if m.any(): print(f"dropping {int(m.sum())} rows of nano audiences removed from the page")
    return df[~m].reset_index(drop=True)


def save(df, rows, label):
    df = t.upsert_db(df, rows)
    t.append_history(HIST, rows)
    df.to_csv(CSV, index=False)
    print(f"{label}: wrote {len(rows)} values to {os.path.basename(CSV)}", flush=True)
    return df


def main(runner, only=None, step=250_000, today=None):
    only = only or {"q3", "q5"}
    shutil.copy(CSV, CSV.replace(".csv", f".backup-{dt.date.today().isoformat()}.csv"))
    df = clean_removed(t.load(CSV))
    max_id = int(runner.sql("SELECT MAX(id) AS m FROM SURVEY_ANYPLACE_LEADS")["m"][0])
    print(f"lead ids go up to {max_id:,}; step {step:,}", flush=True)
    if "q3" in only:
        r3 = runner.run(q.q3, 300_000, max_id, step)
        df = save(df, q.q3_to_totals_and_macros(r3) + q.micros_to_rows(r3), "Query 3 (totals, macros, micros)")
        print(r3[["country", "m_women_all", "m_kids_all", "m_pets_all", "chk_pregnant_by_answer", "chk_kids_without_child_dob"]].to_string(index=False))
    if "q5" in only:
        r5 = runner.run(q.q5, 300_000, max_id, step)
        df = save(df, q.nanos_to_rows(r5), "Query 5 (Pets nanos)")
    filled = df[(df["value"].notna()) & (df["source"] == "db")]
    print(f"done. {len(filled)} database values in the CSV, dated {filled['updated_on'].max()}")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["q3", "q5"], action="append", help="run just this query (can repeat)")
    ap.add_argument("--workers", type=int, default=4); ap.add_argument("--step", type=int, default=250_000)
    ap.add_argument("--build", action="store_true", help="skip the database; just build data.new.json from the CSV (needs data.json next to this script)")
    ap.add_argument("--run-and-build", action="store_true", help="run the queries, then build data.new.json")
    ap.add_argument("--replace", action="store_true", help="with --build: back up data.json and replace it")
    a = ap.parse_args()
    if a.build:
        import build_data_json as b; b.main(replace=a.replace); sys.exit()
    key = os.environ.get("METABASE_API_KEY")
    if not key: sys.exit('Set the key first:  export METABASE_API_KEY="your-new-key"')
    main(rn.Runner(URL, key, workers=a.workers), set(a.only) if a.only else None, a.step)
    if a.run_and_build:
        import build_data_json as b; b.main(replace=a.replace)
