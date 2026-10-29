"""Simulated data for GraphGuard. No real bank, customer or payment data is used.

`generate()` builds a complete in-memory dataset (users, groups, accounts, access grants,
memberships, transactions, audit events). The same dataset is loaded into Neo4j
(seed_loader.py), into SQLite (benchmark/) and used as a *reference model* to check that
the Cypher queries return the right answers (verify.py, tests/).
"""
from __future__ import annotations

import random
import time
from collections import defaultdict

from . import config
from .rules import RANK_NAMES, evaluate_rules, format_path, rank_of, VELOCITY_WINDOW_MS

DAY = 86_400_000
HOUR = 3_600_000
MINUTE = 60_000

OWNS, SIGN, ACCESS = "OWNS", "AUTHORIZED_SIGNATORY_OF", "HAS_ACCESS_TO"

FIRST = ["Arjun", "Kavya", "Rohan", "Nisha", "Vikram", "Sneha", "Amit", "Pooja", "Karthik", "Divya",
         "Manoj", "Ayesha", "Joseph", "Fathima", "Sanjay", "Deepa", "Imran", "Neha", "Gokul", "Revathi",
         "Nikhil", "Sara", "Hari", "Anjali", "Zubin", "Tara", "Rahul", "Mehak", "Sidharth", "Lekha"]
LAST = ["Menon", "Pillai", "Nair", "Iyer", "Varma", "Ali", "Kurian", "Thomas", "Sharma", "Das",
        "Rao", "Krishnan", "Mathew", "Joseph", "Khan", "Bhat", "Warrier", "Panicker"]
NOTES = ["Utility bill", "Rent", "Groceries", "Supplier payment", "Salary credit", "School fees",
         "Insurance premium", "Vendor invoice", "Refund", "Cash deposit", "Maintenance", "Travel"]


def active(edge, t):
    return edge["granted_at"] <= t and (edge["revoked_at"] is None or edge["revoked_at"] > t)


class Dataset:
    def __init__(self, now_ms, scale, seed):
        self.now_ms, self.scale, self.seed = now_ms, scale, seed
        self.users, self.groups, self.accounts = [], [], []
        self.grants, self.memberships = [], []
        self.transactions, self.events = [], []
        self.owner_of = {}      # account id -> owner user id
        self.chain = None       # set when chain_depth > 0
        self.final_balance = {}

    def index(self):
        return Index(self)

    def counts(self):
        return {
            "User": len(self.users), "Group": len(self.groups), "Account": len(self.accounts),
            "Transaction": len(self.transactions), "AccessEvent": len(self.events),
        }


class Index:
    """Reference model of the access rules. Mirrors the Cypher in queries.py exactly."""

    def __init__(self, ds):
        self.ds = ds
        self.names = {x["id"]: x["name"] for x in ds.users + ds.groups + ds.accounts}
        self.parent = {a["id"]: (a["parent_id"], a["inherits"]) for a in ds.accounts}
        self.grants_by_acct = defaultdict(list)
        for g in ds.grants:
            self.grants_by_acct[g["dst_id"]].append(g)
        self.members = defaultdict(list)
        for m in ds.memberships:
            self.members[m["group_id"]].append(m)

    def ancestors(self, aid):
        """Yield (ancestor id, chain from aid up to that ancestor). Stops at a non-inheriting edge."""
        chain = [aid]
        yield aid, list(chain)
        while len(chain) - 1 < config.MAX_DEPTH:
            pid, inherits = self.parent[chain[-1]]
            if pid is None or not inherits:
                return
            chain.append(pid)
            yield pid, list(chain)

    def effective(self, uid, aid, t):
        """Best access of user `uid` on account `aid` at time t, or None."""
        best = None
        for anc, chain in self.ancestors(aid):
            for g in self.grants_by_acct[anc]:
                if not active(g, t):
                    continue
                since = g["granted_at"]
                if g["src_type"] == "User" and g["src_id"] == uid:
                    holder, group, hops = uid, None, 1 + len(chain) - 1
                elif g["src_type"] == "Group":
                    ms = [m for m in self.members[g["src_id"]] if m["user_id"] == uid and active(m, t)]
                    if not ms:
                        continue
                    holder, group, hops = g["src_id"], g["src_id"], 2 + len(chain) - 1
                    since = max(since, ms[0]["granted_at"])
                else:
                    continue
                rank = rank_of(g["rel"], g["level"])
                if best is not None and (rank, -hops) <= (best["rank"], -best["hops"]):
                    continue
                steps = []
                n = self.names
                if group:
                    steps.append(dict(src_id=uid, src_name=n[uid], rel_type="MEMBER_OF",
                                      dst_id=group, dst_name=n[group], forward=True))
                steps.append(dict(src_id=holder, src_name=n[holder], rel_type=g["rel"],
                                  dst_id=anc, dst_name=n[anc], forward=True))
                for i in range(len(chain) - 1, 0, -1):
                    steps.append(dict(src_id=chain[i], src_name=n[chain[i]], rel_type="PART_OF",
                                      dst_id=chain[i - 1], dst_name=n[chain[i - 1]], forward=False))
                best = dict(rank=rank, hops=hops, access_since=since, grant_type=g["rel"], steps=steps)
        return best

    def candidate_users(self, aid):
        """Every user who could ever have had access to aid (any time). Used when generating data."""
        out = set()
        for anc, _ in self.ancestors(aid):
            for g in self.grants_by_acct[anc]:
                if g["src_type"] == "User":
                    out.add(g["src_id"])
                else:
                    out.update(m["user_id"] for m in self.members[g["src_id"]])
        return sorted(out)


def generate(scale=1, seed=42, now_ms=None, chain_depth=0, n_tx=None):
    rnd = random.Random(seed)
    NOW = now_ms or int(time.time() * 1000)
    ds = Dataset(NOW, scale, seed)

    def t(days):
        return NOW - int(days * DAY)

    def add_user(uid, name):
        ds.users.append({"id": uid, "name": name})

    def add_group(gid, name, kind, admin):
        ds.groups.append({"id": gid, "name": name, "kind": kind, "admin_id": admin})

    def add_account(aid, name, kind, opening, parent=None, inherits=True, owner=None):
        ds.accounts.append({"id": aid, "name": name, "kind": kind, "opening_balance": opening,
                            "balance": opening, "parent_id": parent, "inherits": inherits,
                            "created_at": t(125)})
        if owner:
            ds.owner_of[aid] = owner

    def grant(src, src_type, dst, rel, level, granted, revoked=None, by=None):
        ds.grants.append({"src_id": src, "src_type": src_type, "dst_id": dst, "rel": rel,
                          "level": level, "granted_at": granted, "revoked_at": revoked,
                          "granted_by": by or ds.owner_of.get(dst)})

    def member(uid, gid, granted, revoked=None):
        admin = next(g["admin_id"] for g in ds.groups if g["id"] == gid)
        ds.memberships.append({"user_id": uid, "group_id": gid, "granted_at": granted,
                               "revoked_at": revoked, "granted_by": admin})

    # ------------------------------------------------------------------ demo scenario
    for uid, name in [("u_anita", "Anita Menon"), ("u_ravi", "Ravi Menon"), ("u_meera", "Meera Menon"),
                      ("u_suresh", "Suresh Pillai"), ("u_dev", "Dev Nair"), ("u_lakshmi", "Lakshmi Iyer"),
                      ("u_priya", "Priya Varma"), ("u_farhan", "Farhan Ali")]:
        add_user(uid, name)

    # Family account: 1 admin (Anita), 3 members (Anita, Ravi, Meera)
    add_account("a_menon", "Menon Family Account", "FAMILY", 250_000, owner="u_anita")
    add_group("g_menon", "Menon Family Members", "FAMILY", "u_anita")
    grant("u_anita", "User", "a_menon", OWNS, "TRANSACT", t(120))
    grant("g_menon", "Group", "a_menon", ACCESS, "VIEW", t(120))
    member("u_ravi", "g_menon", t(120))
    member("u_meera", "g_menon", t(110))
    grant("u_ravi", "User", "a_menon", SIGN, "TRANSACT", t(100))

    # Business account with sub-accounts
    add_account("a_kt", "Kozhikode Traders - Main", "BUSINESS", 1_200_000, owner="u_suresh")
    add_account("a_kt_payroll", "Kozhikode Traders - Payroll", "BUSINESS", 400_000, "a_kt", True, "u_suresh")
    add_account("a_kt_tax", "Kozhikode Traders - Tax Reserve", "BUSINESS", 300_000, "a_kt", True, "u_suresh")
    add_account("a_kt_escrow", "Kozhikode Traders - Project Escrow", "BUSINESS", 500_000, "a_kt", False, "u_suresh")
    add_group("g_partners", "Kozhikode Traders Partners", "BUSINESS", "u_suresh")
    grant("u_suresh", "User", "a_kt", OWNS, "TRANSACT", t(120))
    grant("g_partners", "Group", "a_kt", ACCESS, "TRANSACT", t(120))
    member("u_lakshmi", "g_partners", t(100))
    member("u_dev", "g_partners", t(90), revoked=t(20))          # Dev left the partnership 20 days ago
    # Escrow does NOT inherit from Main. Dev was given a direct signatory right and it was never removed.
    grant("u_dev", "User", "a_kt_escrow", SIGN, "TRANSACT", t(85))
    grant("u_lakshmi", "User", "a_kt_escrow", SIGN, "TRANSACT", t(85))
    grant("u_suresh", "User", "a_kt_escrow", OWNS, "TRANSACT", t(120))
    # A brand-new signatory (used for the live "suspicious transaction" demo)
    grant("u_priya", "User", "a_kt", SIGN, "TRANSACT", t(3 / 24), by="u_suresh")

    planted = [
        # (ts, account, user, type, amount, to_account, note)
        (t(45), "a_kt", "u_dev", "WITHDRAWAL", 25_000, None, "Supplier payment"),
        (t(30), "a_kt", "u_dev", "TRANSFER", 12_000, "a_kt_payroll", "Payroll top-up"),
        (t(12), "a_kt", "u_lakshmi", "WITHDRAWAL", 60_000, None, "Equipment purchase"),
        (t(40), "a_menon", "u_ravi", "WITHDRAWAL", 4_200, None, "School fees"),
        (t(25), "a_menon", "u_anita", "DEPOSIT", 30_000, None, "Salary credit"),
        (t(8), "a_menon", "u_ravi", "TRANSFER", 6_000, "a_kt", "Loan repayment"),
        (t(35), "a_kt_escrow", "u_dev", "WITHDRAWAL", 9_000, None, "Contractor milestone"),
        (t(6), "a_kt_escrow", "u_dev", "WITHDRAWAL", 18_000, None, "Contractor milestone"),  # after he left Main
    ]

    # ------------------------------------------------------------------ generated data
    pool_n = max(60 * scale, 20)
    pool = []
    used = set()
    while len(pool) < pool_n:
        nm = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
        if nm in used:
            nm = f"{nm} {len(pool) + 1}"
        used.add(nm)
        uid = f"u_{len(pool) + 1:04d}"
        add_user(uid, nm)
        pool.append(uid)

    def pick(k, exclude=()):
        return rnd.sample([u for u in pool if u not in exclude], k)

    n_fam, n_biz, n_joint = 10 * scale, 10 * scale, 15 * scale
    for i in range(1, n_fam + 1):
        owner = pick(1)[0]
        mems = pick(rnd.randint(2, 4), (owner,))
        aid, gid = f"a_fam_{i:03d}", f"g_fam_{i:03d}"
        add_account(aid, f"{rnd.choice(LAST)} Family Account {i}", "FAMILY", rnd.randint(50, 400) * 1000, owner=owner)
        add_group(gid, f"Family Members {i}", "FAMILY", owner)
        grant(owner, "User", aid, OWNS, "TRANSACT", t(rnd.uniform(90, 120)))
        grant(gid, "Group", aid, ACCESS, "VIEW", t(rnd.uniform(90, 120)))
        for m in mems:
            gj = t(rnd.uniform(60, 118))
            rv = t(rnd.uniform(2, 50)) if rnd.random() < 0.15 else None
            member(m, gid, gj, rv)
        grant(mems[0], "User", aid, SIGN, "TRANSACT", t(rnd.uniform(40, 88)),
              t(rnd.uniform(1, 30)) if rnd.random() < 0.15 else None)

    for i in range(1, n_biz + 1):
        owner = pick(1)[0]
        mems = pick(rnd.randint(2, 3), (owner,))
        aid, gid = f"a_biz_{i:03d}", f"g_biz_{i:03d}"
        add_account(aid, f"{rnd.choice(LAST)} & Co {i} - Main", "BUSINESS", rnd.randint(300, 2000) * 1000, owner=owner)
        add_group(gid, f"Partners {i}", "BUSINESS", owner)
        grant(owner, "User", aid, OWNS, "TRANSACT", t(rnd.uniform(100, 120)))
        grant(gid, "Group", aid, ACCESS, "TRANSACT", t(rnd.uniform(100, 120)))
        ex_members = []
        for m in mems:
            rv = t(rnd.uniform(2, 50)) if rnd.random() < 0.25 else None
            member(m, gid, t(rnd.uniform(60, 98)), rv)
            if rv:
                ex_members.append(m)
        for s in (1, 2):
            sid = f"a_biz_{i:03d}_s{s}"
            inherits = not (s == 2 and rnd.random() < 0.3)
            add_account(sid, f"{rnd.choice(LAST)} & Co {i} - Sub {s}", "BUSINESS",
                        rnd.randint(50, 300) * 1000, aid, inherits, owner)
            grant(owner, "User", sid, OWNS, "TRANSACT", t(rnd.uniform(90, 110)))
            if not inherits:       # access must be granted directly
                grant(mems[0], "User", sid, SIGN, "TRANSACT", t(rnd.uniform(60, 88)))
        # a few ex-partners keep a stray direct grant -> "orphaned access"
        if ex_members and rnd.random() < 0.5:
            grant(ex_members[0], "User", f"a_biz_{i:03d}_s1", ACCESS, "VIEW", t(rnd.uniform(55, 88)))

    for i in range(1, n_joint + 1):
        a_, b_, c_ = pick(3)
        aid = f"a_jnt_{i:03d}"
        add_account(aid, f"Joint Account {i}", "JOINT", rnd.randint(20, 300) * 1000, owner=a_)
        grant(a_, "User", aid, OWNS, "TRANSACT", t(rnd.uniform(100, 120)))
        grant(b_, "User", aid, OWNS, "TRANSACT", t(rnd.uniform(100, 120)))
        if rnd.random() < 0.3:
            grant(c_, "User", aid, ACCESS, "VIEW", t(rnd.uniform(30, 90)),
                  t(rnd.uniform(1, 25)) if rnd.random() < 0.5 else None)

    if chain_depth:
        owner = pick(1)[0]
        prev = None
        for i in range(chain_depth + 1):
            add_account(f"a_chain_{i}", f"Chain Level {i}", "BUSINESS", 100_000, prev, True, owner)
            prev = f"a_chain_{i}"
        grant(owner, "User", "a_chain_0", OWNS, "TRANSACT", t(120))
        ds.chain = {"owner": owner, "root": "a_chain_0", "leaf": f"a_chain_{chain_depth}"}

    # ------------------------------------------------------------------ transactions
    idx = ds.index()
    acct_ids = [a["id"] for a in ds.accounts if not a["id"].startswith("a_chain_")]
    target = n_tx if n_tx is not None else 450 * scale
    cands = list(planted)
    tries = 0
    while len(cands) < target and tries < target * 40:
        tries += 1
        aid = rnd.choice(acct_ids)
        ts = t(rnd.uniform(0.05, 100))
        users = idx.candidate_users(aid)
        if not users:
            continue
        uid = rnd.choice(users)
        eff = idx.effective(uid, aid, ts)
        if not eff or eff["rank"] < 2:
            continue
        typ = rnd.choices(["DEPOSIT", "WITHDRAWAL", "TRANSFER"], [35, 40, 25])[0]
        amt = round(min(max(rnd.lognormvariate(8.3, 0.9), 200), 90_000), -1)
        if rnd.random() < 0.015:
            amt = float(rnd.randint(120, 350) * 1000)
        to = rnd.choice(acct_ids) if typ == "TRANSFER" else None
        cands.append((ts, aid, uid, typ, amt, to, rnd.choice(NOTES)))
    # short bursts by one user (to exercise the HIGH_VELOCITY rule)
    for _ in range(max(2, 3 * scale)):
        aid = rnd.choice(acct_ids)
        users = idx.candidate_users(aid)
        if not users:
            continue
        uid, base = rnd.choice(users), t(rnd.uniform(1, 60))
        if not (idx.effective(uid, aid, base) and idx.effective(uid, aid, base + 8 * MINUTE)):
            continue
        for k in range(5):
            cands.append((base + k * 90_000, aid, uid, "WITHDRAWAL", float(rnd.randint(5, 40) * 10), None, "ATM"))

    cands.sort(key=lambda c: c[0])
    bal = {a["id"]: a["opening_balance"] for a in ds.accounts}
    hist = defaultdict(list)        # account -> amounts of earlier ON_ACCOUNT transactions
    recent = defaultdict(list)      # (user, account) -> timestamps
    planted_set = set(planted)
    for c in cands:
        ts, aid, uid, typ, amt, to, note = c
        eff = idx.effective(uid, aid, ts)
        if not eff or eff["rank"] < 2:
            if c in planted_set:
                raise AssertionError(f"planted transaction has no access: {c}")
            continue
        if typ in ("WITHDRAWAL", "TRANSFER") and amt > bal[aid]:
            typ, to = "DEPOSIT", None
        if typ == "TRANSFER" and (to is None or to == aid):
            typ, to = "WITHDRAWAL", None
        prior = hist[aid]
        avg = sum(prior) / len(prior) if prior else 0
        rec = sum(1 for x in recent[(uid, aid)] if 0 <= ts - x <= VELOCITY_WINDOW_MS)
        reasons = evaluate_rules(amt, len(prior), avg, rec, ts - eff["access_since"])
        if typ == "DEPOSIT":
            bal[aid] += amt
        else:
            bal[aid] -= amt
        to_after = None
        if typ == "TRANSFER":
            bal[to] += amt
            to_after = round(bal[to], 2)
        hist[aid].append(amt)
        recent[(uid, aid)].append(ts)
        ds.transactions.append({
            "id": f"t_{len(ds.transactions) + 1:05d}", "type": typ, "amount": float(amt), "ts": ts,
            "note": note, "user_id": uid, "account_id": aid, "to_account_id": to,
            "access_level": RANK_NAMES[eff["rank"]], "access_path": format_path(eff["steps"]),
            "flagged": bool(reasons), "flag_reasons": reasons,
            "balance_after": round(bal[aid], 2), "to_balance_after": to_after,
        })
    for a in ds.accounts:
        a["balance"] = round(bal[a["id"]], 2)

    # ------------------------------------------------------------------ audit events
    raw = []
    names = idx.names
    for g in ds.grants:
        base = dict(actor_id=g["granted_by"], actor_name=names.get(g["granted_by"]),
                    subject_id=g["src_id"], subject_name=names[g["src_id"]],
                    target_id=g["dst_id"], target_name=names[g["dst_id"]],
                    rel_type=g["rel"], level=g["level"])
        raw.append({**base, "type": "GRANT", "ts": g["granted_at"], "reason": "Access granted"})
        if g["revoked_at"] is not None:
            raw.append({**base, "type": "REVOKE", "ts": g["revoked_at"], "reason": "Access revoked"})
    for m in ds.memberships:
        base = dict(actor_id=m["granted_by"], actor_name=names.get(m["granted_by"]),
                    subject_id=m["user_id"], subject_name=names[m["user_id"]],
                    target_id=m["group_id"], target_name=names[m["group_id"]],
                    rel_type="MEMBER_OF", level="MEMBER")
        raw.append({**base, "type": "GRANT", "ts": m["granted_at"], "reason": "Added to group"})
        if m["revoked_at"] is not None:
            raw.append({**base, "type": "REVOKE", "ts": m["revoked_at"], "reason": "Removed from group"})
    for ts, uid, aid, why in [
        (t(10), "u_meera", "a_menon", "TRANSACT attempt with VIEW-only access"),
        (t(5), "u_dev", "a_kt", "No active access path (left partnership)"),
    ]:
        raw.append(dict(type="DENIED", ts=ts, actor_id=uid, actor_name=names[uid], subject_id=uid,
                        subject_name=names[uid], target_id=aid, target_name=names[aid],
                        rel_type="TRANSACT", reason=why))
    raw.sort(key=lambda e: e["ts"])
    for i, e in enumerate(raw, 1):
        ds.events.append({"id": f"e_{i:05d}", **e})
    return ds
