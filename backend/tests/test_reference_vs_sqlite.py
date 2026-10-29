"""Offline tests (no Neo4j needed).

The relational (SQLite recursive-CTE) implementation and the Python reference model are two
independent implementations of the access rules. If they agree on thousands of (user, account,
time) combinations, the rules in seed_data.py are internally consistent. verify.py then checks
Neo4j against the same reference.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "benchmark"))

import relational  # noqa: E402
from app.rules import evaluate_rules, format_path  # noqa: E402
from app.seed_data import DAY, generate  # noqa: E402


def test_reference_matches_sql_everywhere():
    ds = generate(scale=1)
    idx, con = ds.index(), relational.build(ds)
    rnd = random.Random(3)
    users, accts = [u["id"] for u in ds.users], [a["id"] for a in ds.accounts]
    n = 0
    for t in (ds.now_ms, ds.now_ms - 7 * DAY, ds.now_ms - 30 * DAY, ds.now_ms - 65 * DAY, ds.now_ms - 110 * DAY):
        for _ in range(1500):
            u, a = rnd.choice(users), rnd.choice(accts)
            ref = idx.effective(u, a, t)
            assert (ref["rank"] if ref else 0) == relational.check(con, u, a, t), (u, a, t)
            n += 1
    assert n == 7500


def test_demo_story():
    ds = generate(scale=1)
    idx, now = ds.index(), ds.now_ms
    lvl = lambda u, a, days=0: (lambda e: e["rank"] if e else 0)(idx.effective(u, a, now - days * DAY))
    # Dev left the partnership 20 days ago: had Main + Payroll a month ago, not now ...
    assert lvl("u_dev", "a_kt", 30) == 2 and lvl("u_dev", "a_kt") == 0
    assert lvl("u_dev", "a_kt_payroll", 30) == 2 and lvl("u_dev", "a_kt_payroll") == 0
    # ... but the Escrow sub-account (inherits=False, direct grant) was never cleaned up.
    assert lvl("u_dev", "a_kt_escrow") == 2
    # Sub-accounts inherit from the parent when inherits=True
    assert lvl("u_lakshmi", "a_kt_payroll") == 2 and lvl("u_suresh", "a_kt_tax") == 3
    # Family: Anita owner, Ravi signatory, Meera view-only via the group
    assert (lvl("u_anita", "a_menon"), lvl("u_ravi", "a_menon"), lvl("u_meera", "a_menon")) == (3, 2, 1)
    # Priya became a signatory 3 hours ago
    assert lvl("u_priya", "a_kt") == 2 and lvl("u_priya", "a_kt", 1) == 0
    assert lvl("u_farhan", "a_kt") == 0


def test_seed_is_consistent():
    ds = generate(scale=1)
    idx = ds.index()
    assert 500 <= sum(ds.counts().values()) <= 1000
    bal = {a["id"]: a["opening_balance"] for a in ds.accounts}
    for t in ds.transactions:                               # chronological, immutable ledger
        eff = idx.effective(t["user_id"], t["account_id"], t["ts"])
        assert eff and eff["rank"] >= 2, t                  # every tx was made with TRANSACT access
        bal[t["account_id"]] += t["amount"] if t["type"] == "DEPOSIT" else -t["amount"]
        if t["type"] == "TRANSFER":
            bal[t["to_account_id"]] += t["amount"]
        assert round(bal[t["account_id"]], 2) == t["balance_after"]
        assert bal[t["account_id"]] >= -0.01
    for a in ds.accounts:
        assert round(bal[a["id"]], 2) == a["balance"]
    assert any(t["flagged"] for t in ds.transactions)


def test_deterministic():
    a, b = generate(seed=1, now_ms=10**12), generate(seed=1, now_ms=10**12)
    assert a.transactions == b.transactions and a.grants == b.grants


def test_rules_and_path_format():
    assert evaluate_rules(50_000, 10, 2_000, 0, None) == ["LARGE_AMOUNT"]
    assert evaluate_rules(500, 10, 2_000, 3, None) == ["HIGH_VELOCITY"]
    assert evaluate_rules(20_000, 0, 0, 0, 1000) == ["NEW_ACCESS_LARGE_TX"]
    assert evaluate_rules(500, 10, 400, 0, 10**9) == []
    steps = [dict(src_name="A", rel_type="OWNS", dst_name="P", forward=True),
             dict(src_name="P", rel_type="PART_OF", dst_name="S", forward=False)]
    assert format_path(steps) == "A -[OWNS]-> P <-[PART_OF]- S"


def test_sql_path_explanation_matches_reference():
    ds = generate(scale=1)
    idx, con = ds.index(), relational.build(ds)
    for u, a, days in [("u_lakshmi", "a_kt_payroll", 0), ("u_priya", "a_kt", 0), ("u_ravi", "a_menon", 0),
                       ("u_meera", "a_menon", 0), ("u_dev", "a_kt_payroll", 30), ("u_dev", "a_kt_escrow", 0)]:
        t = ds.now_ms - days * DAY
        ref = idx.effective(u, a, t)
        rank, hops, path = relational.explain(con, u, a, t)
        assert (rank, hops, path) == (ref["rank"], ref["hops"], format_path(ref["steps"])), (u, a)
    assert relational.explain(con, "u_dev", "a_kt_payroll", ds.now_ms) is None
