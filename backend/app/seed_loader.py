"""Load the simulated dataset into Neo4j.

    python -m app.seed_loader              # wipe + load the demo dataset (scale 1)
    python -m app.seed_loader --scale 3    # bigger dataset
"""
import argparse
import time

from . import config, db
from .seed_data import generate

CONSTRAINTS = [
    "CREATE CONSTRAINT user_id IF NOT EXISTS FOR (n:User) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT group_id IF NOT EXISTS FOR (n:Group) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT account_id IF NOT EXISTS FOR (n:Account) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT tx_id IF NOT EXISTS FOR (n:Transaction) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (n:AccessEvent) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX tx_ts IF NOT EXISTS FOR (n:Transaction) ON (n.ts)",
    "CREATE INDEX event_ts IF NOT EXISTS FOR (n:AccessEvent) ON (n.ts)",
    "CREATE INDEX event_target IF NOT EXISTS FOR (n:AccessEvent) ON (n.target_id)",
]

ACCT_PROPS = "id: r.id, name: r.name, kind: r.kind, balance: r.balance, opening_balance: r.opening_balance, created_at: r.created_at"


def _plan(ds):
    """(cypher, rows) pairs in load order."""
    main = [a for a in ds.accounts if not a["parent_id"]]
    sub = [a for a in ds.accounts if a["parent_id"]]
    plan = [
        ("UNWIND $rows AS r CREATE (:User {id: r.id, name: r.name})", ds.users),
        ("UNWIND $rows AS r CREATE (:Group {id: r.id, name: r.name, kind: r.kind, admin_id: r.admin_id})", ds.groups),
        (f"UNWIND $rows AS r CREATE (:Account {{{ACCT_PROPS}}})", main),
        (f"UNWIND $rows AS r CREATE (:Account:SubAccount {{{ACCT_PROPS}}})", sub),
        ("UNWIND $rows AS r MATCH (s:Account {id: r.id}), (p:Account {id: r.parent_id}) "
         "CREATE (s)-[:PART_OF {inherits: r.inherits}]->(p)", sub),
        ("UNWIND $rows AS r MATCH (u:User {id: r.user_id}), (g:Group {id: r.group_id}) "
         "CREATE (u)-[:MEMBER_OF {granted_at: r.granted_at, revoked_at: r.revoked_at, granted_by: r.granted_by}]->(g)",
         ds.memberships),
    ]
    for rel in ("OWNS", "AUTHORIZED_SIGNATORY_OF", "HAS_ACCESS_TO"):
        plan.append((
            "UNWIND $rows AS r MATCH (s:User|Group {id: r.src_id}), (a:Account {id: r.dst_id}) "
            f"CREATE (s)-[:{rel} {{granted_at: r.granted_at, revoked_at: r.revoked_at, level: r.level, "
            "granted_by: r.granted_by}]->(a)",
            [g for g in ds.grants if g["rel"] == rel]))
    txs = ds.transactions
    plan += [
        ("UNWIND $rows AS r CREATE (:Transaction {id: r.id, type: r.type, amount: r.amount, ts: r.ts, note: r.note, "
         "flagged: r.flagged, flag_reasons: r.flag_reasons, balance_after: r.balance_after, "
         "to_balance_after: r.to_balance_after})", txs),
        ("UNWIND $rows AS r MATCH (u:User {id: r.user_id}), (t:Transaction {id: r.id}) "
         "CREATE (u)-[:PERFORMED {access_level: r.access_level, access_path: r.access_path, at: r.ts}]->(t)", txs),
        ("UNWIND $rows AS r MATCH (t:Transaction {id: r.id}), (a:Account {id: r.account_id}) "
         "CREATE (t)-[:ON_ACCOUNT]->(a)", txs),
        ("UNWIND $rows AS r MATCH (t:Transaction {id: r.id}), (a:Account {id: r.to_account_id}) "
         "CREATE (t)-[:TO_ACCOUNT]->(a)", [t for t in txs if t["to_account_id"]]),
        ("UNWIND $rows AS r CREATE (:AccessEvent {id: r.id, type: r.type, ts: r.ts, actor_id: r.actor_id, "
         "actor_name: r.actor_name, subject_id: r.subject_id, subject_name: r.subject_name, "
         "target_id: r.target_id, target_name: r.target_name, rel_type: r.rel_type, level: r.level, "
         "reason: r.reason})", ds.events),
    ]
    return plan


def load(driver, ds, database=None, wipe=True, batch=500, log=print):
    database = database or config.NEO4J_DATABASE
    with driver.session(database=database) as s:
        if wipe:
            s.run("MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS").consume()
        for c in CONSTRAINTS:
            s.run(c).consume()
        for cypher, rows in _plan(ds):
            for i in range(0, len(rows), batch):
                chunk = rows[i:i + batch]
                s.execute_write(lambda tx, q=cypher, b=chunk: tx.run(q, rows=b).consume())
        s.execute_write(lambda tx: tx.run(
            "CREATE (:Meta {key: 'seed', now_ms: $now, scale: $scale, seed: $seed})",
            now=ds.now_ms, scale=ds.scale, seed=ds.seed).consume())
    log(f"Loaded {ds.counts()}")


def reseed(scale=1, seed=42, chain_depth=0):
    t0 = time.time()
    ds = generate(scale=scale, seed=seed, chain_depth=chain_depth)
    load(db.get_driver(), ds, log=lambda *_: None)
    return {"status": "ok", "counts": ds.counts(), "seconds": round(time.time() - t0, 1)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    ok, err = db.ping()
    if not ok:
        raise SystemExit(f"Cannot connect to Neo4j at {config.NEO4J_URI}: {err}")
    print(reseed(a.scale, a.seed))
    db.close_driver()
