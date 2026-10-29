"""Compare access-check performance: Neo4j (Cypher) vs relational (SQLite recursive CTE).

    # relational side only (no Neo4j needed)
    python benchmark/run_benchmark.py --scales 1 5 20

    # both (WIPES the connected Neo4j database and loads benchmark data; re-run
    # `python -m app.seed_loader` afterwards to restore the demo data)
    python benchmark/run_benchmark.py --scales 1 5 20 --neo4j --depths 2 4 6 8

Timing notes (state these in your report):
  * SQLite runs in-process, so its time has no network cost.
  * For Neo4j we report the *server-side* time from the driver's result summary
    (result_available_after + result_consumed_after), which excludes the network round-trip.
    With AuraDB that round-trip can be 50-200 ms; a local Neo4j has almost none.
  * Each query is warmed up first; we report the median and p95 of N runs.
"""
import argparse
import csv
import os
import random
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app import config  # noqa: E402
from app.seed_data import DAY, generate  # noqa: E402
import relational  # noqa: E402


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def summarize(xs):
    return round(statistics.median(xs), 3), round(pct(xs, 95), 3)


def sql_timings(con, pairs, t, depth):
    out, answers = [], []
    for u, a in pairs:
        t0 = time.perf_counter()
        r = relational.check(con, u, a, t, depth)
        out.append((time.perf_counter() - t0) * 1000)
        answers.append(r)
    return out, answers


def neo_timings(driver, pairs, t, depth):
    from app import queries as Q
    q = Q.check_query(depth)
    out, answers = [], []
    with driver.session(database=config.NEO4J_DATABASE) as s:
        for u, a in pairs:
            res = s.run(q, uid=u, aid=a, t=t)
            rows = res.data()
            summ = res.consume()
            out.append(summ.result_available_after + summ.result_consumed_after)
            answers.append(rows[0]["rank"] if rows else 0)
    return out, answers


def pairs_for(ds, n, rnd):
    users = [u["id"] for u in ds.users]
    accts = [a["id"] for a in ds.accounts if not a["id"].startswith("a_chain_")]
    return [(rnd.choice(users), rnd.choice(accts)) for _ in range(n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scales", type=int, nargs="+", default=[1, 5, 20])
    ap.add_argument("--depths", type=int, nargs="+", default=[2, 4, 6, 8])
    ap.add_argument("--pairs", type=int, default=300)
    ap.add_argument("--neo4j", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "benchmark", "results.csv"))
    a = ap.parse_args()

    driver = None
    if a.neo4j:
        from app import db
        from app.seed_loader import load
        ok, err = db.ping()
        if not ok:
            sys.exit(f"Cannot connect to Neo4j: {err}")
        driver = db.get_driver()

    rnd = random.Random(1)
    rows = []

    print("\n== Experiment A: random access checks as the dataset grows ==")
    for scale in a.scales:
        ds = generate(scale=scale)
        con = relational.build(ds)
        prs = pairs_for(ds, a.pairs, rnd)
        relational.check(con, *prs[0], ds.now_ms)                          # warm-up
        ts, sa = sql_timings(con, prs, ds.now_ms, config.MAX_DEPTH)
        entry = {"experiment": "scale", "param": scale, "nodes": sum(ds.counts().values()),
                 "sql_median_ms": summarize(ts)[0], "sql_p95_ms": summarize(ts)[1]}
        if driver:
            load(driver, ds, log=lambda *_: None)
            neo_timings(driver, prs[:5], ds.now_ms, config.MAX_DEPTH)       # warm-up
            tn, na = neo_timings(driver, prs, ds.now_ms, config.MAX_DEPTH)
            entry.update(neo4j_median_ms=summarize(tn)[0], neo4j_p95_ms=summarize(tn)[1],
                         answers_agree=(sa == na))
        rows.append(entry)
        print(entry)

    print("\n== Experiment B: owner -> deepest sub-account, as the hierarchy gets deeper ==")
    for depth in a.depths:
        ds = generate(scale=1, chain_depth=depth)
        con = relational.build(ds)
        c = ds.chain
        prs = [(c["owner"], c["leaf"])] * 100
        ts, sa = sql_timings(con, prs, ds.now_ms, depth)
        entry = {"experiment": "depth", "param": depth, "nodes": sum(ds.counts().values()),
                 "sql_median_ms": summarize(ts)[0], "sql_p95_ms": summarize(ts)[1]}
        assert sa[0] == 3, "relational query should find OWNER access at the deepest level"
        if driver:
            load(driver, ds, log=lambda *_: None)
            neo_timings(driver, prs[:5], ds.now_ms, depth)
            tn, na = neo_timings(driver, prs, ds.now_ms, depth)
            entry.update(neo4j_median_ms=summarize(tn)[0], neo4j_p95_ms=summarize(tn)[1], answers_agree=(sa == na))
        rows.append(entry)
        print(entry)

    keys = sorted({k for r in rows for k in r}, key=lambda k: ["experiment", "param", "nodes"].index(k)
                  if k in ("experiment", "param", "nodes") else 9)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved {a.out}")
    if driver:
        print("Neo4j now holds benchmark data. Restore the demo with: python -m app.seed_loader")


if __name__ == "__main__":
    main()
