"""Check the live Neo4j database against the Python reference model.

    python -m app.verify

Regenerates the dataset that was loaded (same seed / timestamp), then asks Neo4j (through the
exact functions the API uses) for the access level of many (user, account) pairs at several
points in time, and compares each answer with the reference model. Prints PASS or the mismatches.
"""
import random
import sys

from . import db, services as S
from . import queries as Q
from .seed_data import DAY, generate


def main(samples=400):
    ok, err = db.ping()
    if not ok:
        sys.exit(f"Cannot connect to Neo4j: {err}")
    meta = db.read(lambda tx: db.rows(tx, Q.META))
    if not meta:
        sys.exit("No seed metadata found. Run: python -m app.seed_loader")
    m = meta[0]
    ds = generate(scale=m["scale"], seed=m["seed"], now_ms=m["now_ms"])
    idx = ds.index()

    # 1) node counts
    counts = {r["label"]: r["count"] for r in db.read(lambda tx: db.rows(tx, Q.NODE_COUNTS))}
    bad = 0
    for label, n in ds.counts().items():
        if counts.get(label) != n:
            print(f"COUNT MISMATCH {label}: neo4j={counts.get(label)} expected={n}")
            bad += 1

    # 2) access answers: demo users x demo accounts, plus random pairs, at 4 points in time
    rnd = random.Random(7)
    users = [u["id"] for u in ds.users]
    accts = [a["id"] for a in ds.accounts]
    demo_u = [u for u in users if not u[2:].isdigit()]
    demo_a = [a for a in accts if a.startswith(("a_menon", "a_kt"))]
    pairs = [(u, a) for u in demo_u for a in demo_a] + [(rnd.choice(users), rnd.choice(accts)) for _ in range(samples)]
    times = [ds.now_ms, ds.now_ms - 7 * DAY, ds.now_ms - 30 * DAY, ds.now_ms - 65 * DAY]
    checked = 0
    for t in times:
        for u, a in pairs:
            ref = idx.effective(u, a, t)
            got = db.read(S.check_access, u, a, t)
            want = ref["rank"] if ref else 0
            have = {"OWNER": 3, "TRANSACT": 2, "VIEW": 1, None: 0}[got["level"]]
            checked += 1
            if want != have:
                bad += 1
                if bad <= 15:
                    print(f"MISMATCH user={u} account={a} t=-{round((ds.now_ms - t) / DAY)}d  neo4j={have} reference={want}")

    # 3) every account's "who has access" list equals the reference
    for t in times:
        for a in demo_a:
            want = {u for u in users if idx.effective(u, a, t)}
            have = {r["user_id"] for r in db.read(S.who_has_access, a, t)}
            checked += 1
            if want != have:
                bad += 1
                print(f"WHO-HAS-ACCESS MISMATCH {a} t=-{round((ds.now_ms - t) / DAY)}d  only-neo4j={have - want} only-ref={want - have}")

    print(f"\nChecked {checked} answers. " + ("PASS - Neo4j matches the reference model." if not bad else f"FAIL - {bad} problems."))
    db.close_driver()
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
