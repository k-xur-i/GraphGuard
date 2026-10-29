"""Business logic. Every function takes a Neo4j transaction `tx` as its first argument."""
import uuid

from . import queries as Q
from .db import rows
from .rules import RANK_NAMES, VELOCITY_WINDOW_MS, evaluate_rules, format_path

ACCESS_TYPES = ("OWNS", "AUTHORIZED_SIGNATORY_OF", "HAS_ACCESS_TO")


# ------------------------------------------------------------------ access resolution
def check_access(tx, uid, aid, t):
    found = rows(tx, Q.check_query(), uid=uid, aid=aid, t=t)
    base = {"user_id": uid, "account_id": aid, "as_of": t}
    if not found:
        return {**base, "allowed": False, "level": None, "can_view": False, "can_transact": False,
                "is_owner": False, "hops": None, "access_since": None, "path": [], "path_text": "",
                "alternatives": []}
    best = found[0]
    return {
        **base, "allowed": True, "level": RANK_NAMES[best["rank"]],
        "can_view": True, "can_transact": best["rank"] >= 2, "is_owner": best["rank"] == 3,
        "hops": best["hops"], "access_since": best["access_since"],
        "path": best["steps"], "path_text": format_path(best["steps"]),
        "alternatives": [{"level": RANK_NAMES[r["rank"]], "hops": r["hops"],
                          "path_text": format_path(r["steps"]), "path": r["steps"]} for r in found[1:]],
    }


def accounts_for_user(tx, uid, t):
    out = rows(tx, Q.accounts_for_user_query(), uid=uid, t=t)
    for r in out:
        r["level"] = RANK_NAMES[r.pop("rank")]
    return out


def who_has_access(tx, aid, t):
    out = rows(tx, Q.who_has_access_query(), aid=aid, t=t)
    for r in out:
        r["level"] = RANK_NAMES[r.pop("rank")]
    return out


def access_diff(tx, aid, t_from, t_to):
    before = {r["user_id"]: r for r in who_has_access(tx, aid, t_from)}
    after = {r["user_id"]: r for r in who_has_access(tx, aid, t_to)}
    return {
        "lost": [before[u] for u in before if u not in after],
        "gained": [after[u] for u in after if u not in before],
        "changed": [{"user_id": u, "name": after[u]["name"], "from": before[u]["level"], "to": after[u]["level"]}
                    for u in before if u in after and before[u]["level"] != after[u]["level"]],
        "unchanged": [after[u] for u in after if u in before and before[u]["level"] == after[u]["level"]],
    }


def orphaned_access(tx, t):
    return rows(tx, Q.orphaned_query(), t=t)


# ------------------------------------------------------------------ grant / revoke
def _is_owner(tx, actor, account_id, now):
    return check_access(tx, actor, account_id, now)["is_owner"]


def _deny(tx, uid, aid, op, reason, now):
    rows(tx, Q.DENIED_EVENT, uid=uid, aid=aid, op=op, reason=reason, now=now)


def grant(tx, subject_id, target_id, rel_type, level, actor, reason, now):
    if rel_type != "MEMBER_OF" and rel_type not in ACCESS_TYPES:   # whitelist: rel type is spliced into Cypher
        return {"status": "INVALID", "detail": f"Unknown relationship type {rel_type}"}
    if rel_type == "MEMBER_OF":
        ok = rows(tx, Q.IS_GROUP_ADMIN, gid=target_id, actor=actor)
        if not ok or not ok[0]["ok"]:
            return {"status": "FORBIDDEN", "detail": "Only the group admin can add members."}
        res = rows(tx, Q.GRANT_MEMBER, sid=subject_id, tid=target_id, actor=actor, reason=reason, now=now)
    else:
        if not _is_owner(tx, actor, target_id, now):
            _deny(tx, actor, target_id, f"GRANT:{rel_type}", "Actor is not an owner of the account", now)
            return {"status": "FORBIDDEN", "detail": "Only an account owner can grant access."}
        q = Q._fmt(Q.GRANT_ACCESS, REL=rel_type)
        res = rows(tx, q, sid=subject_id, tid=target_id, actor=actor, level=level, reason=reason, now=now)
    if not res:
        return {"status": "CONFLICT", "detail": "That access is already active (or a node does not exist)."}
    return {"status": "OK", "event_id": res[0]["event_id"]}


def revoke(tx, subject_id, target_id, rel_type, actor, reason, now):
    if rel_type is not None and rel_type != "MEMBER_OF" and rel_type not in ACCESS_TYPES:
        return {"status": "INVALID", "detail": f"Unknown relationship type {rel_type}"}
    if rel_type == "MEMBER_OF":
        ok = rows(tx, Q.IS_GROUP_ADMIN, gid=target_id, actor=actor)
        if not ok or not ok[0]["ok"]:
            return {"status": "FORBIDDEN", "detail": "Only the group admin can remove members."}
        rel, tlabel = "MEMBER_OF", "Group"
    else:
        if not _is_owner(tx, actor, target_id, now):
            _deny(tx, actor, target_id, "REVOKE", "Actor is not an owner of the account", now)
            return {"status": "FORBIDDEN", "detail": "Only an account owner can revoke access."}
        rel, tlabel = (rel_type or "|".join(ACCESS_TYPES)), "Account"
    q = Q._fmt(Q.REVOKE, REL=rel, TLABEL=tlabel)
    res = rows(tx, q, sid=subject_id, tid=target_id, actor=actor, reason=reason, now=now)
    if not res:
        return {"status": "NOT_FOUND", "detail": "No active access edge to revoke."}
    return {"status": "OK", "revoked": [r["rel_type"] for r in res], "event_ids": [r["event_id"] for r in res]}


# ------------------------------------------------------------------ transactions
def create_transaction(tx, uid, aid, ttype, amount, to_aid, note, now):
    amount = round(float(amount), 2)
    acc = rows(tx, Q.BALANCE, aid=aid)
    if not acc:
        return {"status": "NOT_FOUND", "detail": f"Unknown account {aid}"}
    if ttype == "TRANSFER":
        if not to_aid or to_aid == aid:
            return {"status": "INVALID", "detail": "A transfer needs a different destination account."}
        dest = rows(tx, Q.BALANCE, aid=to_aid)
        if not dest:
            return {"status": "NOT_FOUND", "detail": f"Unknown destination account {to_aid}"}

    access = check_access(tx, uid, aid, now)
    if not access["can_transact"]:
        why = ("No active access path to this account" if not access["allowed"]
               else f"Access level {access['level']} cannot transact")
        _deny(tx, uid, aid, f"TRANSACT:{ttype}", why, now)
        return {"status": "DENIED", "detail": why, "access": access}

    stats = rows(tx, Q.TX_STATS, aid=aid, uid=uid, since=now - VELOCITY_WINDOW_MS, now=now)[0]
    balance = stats["balance"]
    if ttype in ("WITHDRAWAL", "TRANSFER") and amount > balance:
        return {"status": "INVALID", "detail": f"Insufficient funds (balance {balance:,.2f})."}

    reasons = evaluate_rules(amount, stats["n"], stats["avg_amt"] or 0, stats["recent"],
                             now - (access["access_since"] or now))
    bal_after = round(balance + amount if ttype == "DEPOSIT" else balance - amount, 2)
    tid = "t_" + uuid.uuid4().hex[:10]
    rows(tx, Q.CREATE_TX, uid=uid, aid=aid, tid=tid, type=ttype, amount=amount, now=now, note=note or "",
         flagged=bool(reasons), reasons=reasons, bal_after=bal_after, level=access["level"],
         path=access["path_text"])
    if ttype == "TRANSFER":
        bal_to = round(dest[0]["balance"] + amount, 2)
        rows(tx, Q.CREATE_TX_DEST, bid=to_aid, tid=tid, bal_to=bal_to)
    return {"status": "OK", "transaction_id": tid, "flagged": bool(reasons), "flag_reasons": reasons,
            "balance_after": bal_after, "access_level": access["level"], "access_path": access["path_text"]}


def statement(tx, ids, t, limit=200):
    out = rows(tx, Q.STATEMENT, ids=ids, t=t, limit=limit)
    for r in out:
        credit = r["type"] == "DEPOSIT" or r["leg"] == "TO_ACCOUNT"
        r["direction"] = "CREDIT" if credit else "DEBIT"
    return out


def audit_events(tx, aid, sid, t, limit=200):
    ids = rows(tx, Q.AUDIT_SCOPE, aid=aid)[0]["ids"] if aid else None
    return [r["ev"] for r in rows(tx, Q.AUDIT_EVENTS, ids=ids, sid=sid, t=t, limit=limit)]


# ------------------------------------------------------------------ graph view
def focus_graph(tx, aid, t):
    accts = rows(tx, Q.FOCUS_ACCOUNTS, aid=aid)
    ids = [a["id"] for a in accts]
    access = rows(tx, Q.FOCUS_ACCESS_EDGES, ids=ids, t=t)
    gids = sorted({e["source"] for e in access if e["source_label"] == "Group"})
    members = rows(tx, Q.FOCUS_MEMBERS, gids=gids, t=t) if gids else []

    nodes, links = {}, []
    for a in accts:
        nodes[a["id"]] = {"id": a["id"], "name": a["name"], "type": "SubAccount" if a["parent_id"] else "Account",
                          "kind": a["kind"], "balance": a["balance"], "focus": a["id"] == aid}
        if a["parent_id"]:
            links.append({"source": a["id"], "target": a["parent_id"], "type": "PART_OF", "active": True,
                          "inherits": a["inherits"] is not False})
    for e in access:
        nodes.setdefault(e["source"], {"id": e["source"], "name": e["source_name"], "type": e["source_label"]})
        links.append({"source": e["source"], "target": e["target"], "type": e["type"], "level": e["level"],
                      "active": e["active"], "granted_at": e["granted_at"], "revoked_at": e["revoked_at"]})
    for m in members:
        nodes.setdefault(m["source"], {"id": m["source"], "name": m["source_name"], "type": "User"})
        links.append({"source": m["source"], "target": m["target"], "type": "MEMBER_OF", "active": m["active"],
                      "granted_at": m["granted_at"], "revoked_at": m["revoked_at"]})
    return {"nodes": list(nodes.values()), "links": links, "as_of": t}
