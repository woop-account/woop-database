"""Runs a Metabase query over slices of lead IDs, in parallel, and adds the slices up.

    import audience_runner as rn
    runner = rn.Runner("https://woopworld.metabaseapp.com", os.environ["METABASE_API_KEY"], workers=4)
    r3 = runner.run(q.q3, start=300_000, end=max_id, step=250_000)

- Shows the real error (HTTP status and the first part of the reply) instead of a bare JSON error.
- If a slice fails because it ran too long (empty / HTML reply, timeout, 5xx), it is split in half and retried,
  so a big step is safe: slices that are too big shrink by themselves.
- A real SQL error (wrong column, syntax) stops straight away, it is not retried.
"""
import time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import requests


CANON = {"india": "India", "indonesia": "Indonesia", "malaysia": "Malaysia", "philippines": "Philippines", "other asean": "Other ASEAN"}


class QueryError(Exception):
    def __init__(self, msg, retryable):
        super().__init__(msg); self.retryable = retryable


class Runner:
    def __init__(self, url, api_key, database=67, workers=4, timeout=600, min_span=20_000, retries=3, post=None, quiet=False):
        self.db, self.workers, self.min_span, self.retries, self.quiet = database, workers, min_span, retries, quiet
        self.timeout = timeout
        self._lock = threading.Lock()
        self.splits = 0
        if post is None:
            session = requests.Session(); headers = {"x-api-key": api_key}; endpoint = f"{url.rstrip('/')}/api/dataset"
            post = lambda body: session.post(endpoint, headers=headers, json=body, timeout=self.timeout)
        self._post = post

    def _say(self, *a):
        if not self.quiet:
            with self._lock: print(*a, flush=True)

    def sql(self, sql):
        """Run one query and return a DataFrame."""
        try:
            r = self._post({"database": self.db, "type": "native", "native": {"query": sql}})
        except (requests.Timeout, requests.ConnectionError) as e:
            raise QueryError(f"{type(e).__name__}: {e}", retryable=True)
        try:
            j = r.json()
        except ValueError:
            raise QueryError(f"HTTP {r.status_code}, reply is not JSON. First 300 characters: {r.text[:300]!r}", retryable=True)
        err = j.get("error") if isinstance(j, dict) else None
        if err or (isinstance(j, dict) and j.get("status") == "failed"):
            text = str(err)[:500]
            slow = any(w in text.lower() for w in ("timeout", "timed out", "cancel", "too long", "lost connection", "gone away", "interrupted"))
            raise QueryError(f"Metabase error: {text}", retryable=slow)
        if r.status_code >= 500:
            raise QueryError(f"HTTP {r.status_code}", retryable=True)
        return pd.DataFrame(j["data"]["rows"], columns=[c["name"] for c in j["data"]["cols"]])

    def slice(self, make_sql, a, b):
        """One ID range. On a 'too slow' failure: retry, then split the range in half."""
        last = None
        for attempt in range(self.retries if b - a + 1 <= self.min_span else 1):
            try:
                return self.sql(make_sql(a, b))
            except QueryError as e:
                if not e.retryable: raise
                last = e
                if b - a + 1 > self.min_span: break
                time.sleep(2 ** attempt)
        if b - a + 1 <= self.min_span: raise last
        mid = (a + b) // 2
        with self._lock: self.splits += 1
        self._say(f"  slice {a:,}-{b:,} failed ({str(last)[:90]}); splitting in two")
        return pd.concat([self.slice(make_sql, a, mid), self.slice(make_sql, mid + 1, b)])

    def run(self, make_sql, start, end, step=250_000):
        """Run make_sql(a, b) over [start, end] and add the slices up per country."""
        ranges = [(a, min(a + step - 1, end)) for a in range(start, end + 1, step)]
        t0 = time.time(); parts = {}; self.splits = 0
        with ThreadPoolExecutor(self.workers) as ex:
            futs = {ex.submit(self.slice, make_sql, a, b): (a, b) for a, b in ranges}
            for n, f in enumerate(as_completed(futs), 1):
                parts[futs[f]] = f.result()          # raises the real error if a slice failed for good
                self._say(f"{n}/{len(ranges)} slices done, {time.time() - t0:,.0f}s")
        allp = pd.concat(parts[r] for r in ranges)
        allp["country"] = allp["country"].map(lambda c: CANON.get(str(c).strip().lower(), "Other ASEAN"))   # 'INDIA' and 'India' are one country
        res = allp.groupby("country", as_index=False).sum(numeric_only=True)
        self._say(f"finished in {time.time() - t0:,.0f}s ({self.splits} slices were split)")
        return res
