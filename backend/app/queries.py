"""All Cypher used by GraphGuard, in one place (handy for the report).

Time model: every access edge (OWNS, AUTHORIZED_SIGNATORY_OF, HAS_ACCESS_TO, MEMBER_OF)
carries `granted_at` and, once revoked, `revoked_at` (epoch milliseconds). Edges are never
deleted, so "who had access at time $t" is just a filter on those two properties.
PART_OF edges (sub-account -> parent) carry `inherits` (true = access flows down).
"""
from . import config

ACCESS_RELS = "OWNS|AUTHORIZED_SIGNATORY_OF|HAS_ACCESS_TO"


def _fmt(q, **kw):
    for k, v in kw.items():
        q = q.replace(f"@{k}@", str(v))
    return q


def temporal(p="p"):
    return (f"ALL(rl IN relationships({p}) WHERE rl.granted_at IS NULL OR "
            f"(rl.granted_at <= $t AND (rl.revoked_at IS NULL OR rl.revoked_at > $t)))")


def inherit(p="p"):
    return f"ALL(rl IN relationships({p}) WHERE type(rl) <> 'PART_OF' OR coalesce(rl.inherits, true) = true)"


# 3 = OWNER, 2 = TRANSACT, 1 = VIEW
RANK = ("CASE type(g) WHEN 'OWNS' THEN 3 WHEN 'AUTHORIZED_SIGNATORY_OF' THEN 2 "
        "ELSE (CASE g.level WHEN 'TRANSACT' THEN 2 ELSE 1 END) END")

STEPS = ("[i IN range(0, length(p) - 1) | {"
         "src_id: nodes(p)[i].id, src_name: nodes(p)[i].name, "
         "rel_type: type(relationships(p)[i]), "
         "dst_id: nodes(p)[i + 1].id, dst_name: nodes(p)[i + 1].name, "
         "forward: startNode(relationships(p)[i]) = nodes(p)[i]}]")

SINCE = ("reduce(s = 0, rl IN relationships(p) | "
         "CASE WHEN rl.granted_at IS NOT NULL AND rl.granted_at > s THEN rl.granted_at ELSE s END)")


def check_query(depth=None):
    """Can user $uid access account $aid at time $t? Returns up to 5 best paths."""
    return _fmt("""
MATCH (u:User {id: $uid}), (a:Account {id: $aid})
MATCH p = (u)-[:MEMBER_OF*0..1]->(holder)-[g:@REL@]->(anc:Account)<-[:PART_OF*0..@N@]-(a)
WHERE @TEMPORAL@ AND @INHERIT@
WITH p, g, @RANK@ AS rank
RETURN rank, length(p) AS hops, @SINCE@ AS access_since, type(g) AS grant_type, @STEPS@ AS steps
ORDER BY rank DESC, hops ASC
LIMIT 5
""", REL=ACCESS_RELS, N=depth or config.MAX_DEPTH, TEMPORAL=temporal(), INHERIT=inherit(),
        RANK=RANK, SINCE=SINCE, STEPS=STEPS)


def accounts_for_user_query(depth=None):
    """All accounts user $uid can access at $t, with the best (strongest, then shortest) path."""
    return _fmt("""
MATCH (u:User {id: $uid})
MATCH p = (u)-[:MEMBER_OF*0..1]->(holder)-[g:@REL@]->(anc:Account)<-[:PART_OF*0..@N@]-(a:Account)
WHERE @TEMPORAL@ AND @INHERIT@
WITH a, p, @RANK@ AS rank
ORDER BY rank DESC, length(p) ASC
WITH a, collect({rank: rank, hops: length(p), via: [n IN nodes(p) | n.name]})[0] AS best
RETURN a.id AS account_id, a.name AS name, a.kind AS kind, a.balance AS balance,
       best.rank AS rank, best.hops AS hops, best.via AS via
ORDER BY name
""", REL=ACCESS_RELS, N=depth or config.MAX_DEPTH, TEMPORAL=temporal(), INHERIT=inherit(), RANK=RANK)


def who_has_access_query(depth=None):
    """Every user who had access to account $aid at time $t, and how."""
    return _fmt("""
MATCH (a:Account {id: $aid})
MATCH p = (u:User)-[:MEMBER_OF*0..1]->(holder)-[g:@REL@]->(anc:Account)<-[:PART_OF*0..@N@]-(a)
WHERE @TEMPORAL@ AND @INHERIT@
WITH u, p, @RANK@ AS rank
ORDER BY rank DESC, length(p) ASC
WITH u, collect({rank: rank, hops: length(p), via: [n IN nodes(p) | n.name]})[0] AS best
RETURN u.id AS user_id, u.name AS name, best.rank AS rank, best.hops AS hops, best.via AS via
ORDER BY rank DESC, name
""", REL=ACCESS_RELS, N=depth or config.MAX_DEPTH, TEMPORAL=temporal(), INHERIT=inherit(), RANK=RANK)


def orphaned_query(depth=None):
    """Users with a DIRECT grant on a sub-account but no access to its parent account."""
    return _fmt("""
MATCH (sub:Account)-[po:PART_OF]->(parent:Account)
MATCH p = (u:User)-[:MEMBER_OF*0..1]->(holder)-[g:@REL@]->(sub)
WHERE @TEMPORAL@
  AND NOT EXISTS {
    MATCH q = (u)-[:MEMBER_OF*0..1]->(h2)-[g2:@REL@]->(anc2:Account)<-[:PART_OF*0..@N@]-(parent)
    WHERE @TEMPORAL_Q@ AND @INHERIT_Q@
  }
RETURN u.id AS user_id, u.name AS user_name, sub.id AS sub_id, sub.name AS sub_name,
       parent.id AS parent_id, parent.name AS parent_name, type(g) AS grant_type, g.level AS level,
       g.granted_at AS granted_at, po.inherits AS inherits
ORDER BY parent_name, sub_name, user_name
""", REL=ACCESS_RELS, N=depth or config.MAX_DEPTH, TEMPORAL=temporal(), TEMPORAL_Q=temporal("q"),
        INHERIT_Q=inherit("q"))


# ---------------------------------------------------------------- graph view
FOCUS_ACCOUNTS = _fmt("""
MATCH (a:Account {id: $aid})
OPTIONAL MATCH (a)-[:PART_OF*1..@N@]->(r:Account) WHERE NOT (r)-[:PART_OF]->()
WITH coalesce(r, a) AS root
MATCH (x:Account)-[:PART_OF*0..@N@]->(root)
OPTIONAL MATCH (x)-[po:PART_OF]->(par:Account)
RETURN DISTINCT x.id AS id, x.name AS name, x.kind AS kind, x.balance AS balance,
       par.id AS parent_id, po.inherits AS inherits
""", N=config.MAX_DEPTH)

FOCUS_ACCESS_EDGES = """
MATCH (s:User|Group)-[r:OWNS|AUTHORIZED_SIGNATORY_OF|HAS_ACCESS_TO]->(acc:Account)
WHERE acc.id IN $ids AND r.granted_at <= $t
RETURN s.id AS source, s.name AS source_name, labels(s)[0] AS source_label, acc.id AS target,
       type(r) AS type, r.level AS level, r.granted_at AS granted_at, r.revoked_at AS revoked_at,
       (r.revoked_at IS NULL OR r.revoked_at > $t) AS active
"""

FOCUS_MEMBERS = """
MATCH (u:User)-[m:MEMBER_OF]->(g:Group)
WHERE g.id IN $gids AND m.granted_at <= $t
RETURN u.id AS source, u.name AS source_name, g.id AS target, m.granted_at AS granted_at,
       m.revoked_at AS revoked_at, (m.revoked_at IS NULL OR m.revoked_at > $t) AS active
"""

# ---------------------------------------------------------------- writes
GRANT_ACCESS = """
MATCH (s:User|Group {id: $sid})
MATCH (t:Account {id: $tid})
OPTIONAL MATCH (act:User {id: $actor})
OPTIONAL MATCH (s)-[ex:@REL@]->(t) WHERE ex.revoked_at IS NULL
WITH s, t, act, ex WHERE ex IS NULL
CREATE (s)-[r:@REL@ {granted_at: $now, level: $level, granted_by: $actor}]->(t)
CREATE (e:AccessEvent {id: 'e_' + randomUUID(), type: 'GRANT', ts: $now, actor_id: $actor,
        actor_name: act.name, subject_id: s.id, subject_name: s.name, target_id: t.id,
        target_name: t.name, rel_type: '@REL@', level: $level, reason: $reason})
RETURN e.id AS event_id
"""

GRANT_MEMBER = """
MATCH (s:User {id: $sid})
MATCH (t:Group {id: $tid})
OPTIONAL MATCH (act:User {id: $actor})
OPTIONAL MATCH (s)-[ex:MEMBER_OF]->(t) WHERE ex.revoked_at IS NULL
WITH s, t, act, ex WHERE ex IS NULL
CREATE (s)-[r:MEMBER_OF {granted_at: $now, granted_by: $actor}]->(t)
CREATE (e:AccessEvent {id: 'e_' + randomUUID(), type: 'GRANT', ts: $now, actor_id: $actor,
        actor_name: act.name, subject_id: s.id, subject_name: s.name, target_id: t.id,
        target_name: t.name, rel_type: 'MEMBER_OF', level: 'MEMBER', reason: $reason})
RETURN e.id AS event_id
"""

REVOKE = """
MATCH (s:User|Group {id: $sid})-[r:@REL@]->(t:@TLABEL@ {id: $tid})
WHERE r.revoked_at IS NULL
SET r.revoked_at = $now, r.revoked_by = $actor
WITH s, t, r
OPTIONAL MATCH (act:User {id: $actor})
CREATE (e:AccessEvent {id: 'e_' + randomUUID(), type: 'REVOKE', ts: $now, actor_id: $actor,
        actor_name: act.name, subject_id: s.id, subject_name: s.name, target_id: t.id,
        target_name: t.name, rel_type: type(r), level: coalesce(r.level, 'MEMBER'), reason: $reason})
RETURN e.id AS event_id, type(r) AS rel_type
"""

DENIED_EVENT = """
MATCH (a:Account {id: $aid})
OPTIONAL MATCH (u:User {id: $uid})
CREATE (e:AccessEvent {id: 'e_' + randomUUID(), type: 'DENIED', ts: $now, actor_id: $uid,
        actor_name: u.name, subject_id: $uid, subject_name: u.name, target_id: a.id,
        target_name: a.name, rel_type: $op, reason: $reason})
RETURN e.id AS event_id
"""

IS_GROUP_ADMIN = "MATCH (g:Group {id: $gid}) RETURN g.admin_id = $actor AS ok"

TX_STATS = """
MATCH (a:Account {id: $aid})
OPTIONAL MATCH (x:Transaction)-[:ON_ACCOUNT]->(a)
WITH a, count(x) AS n, avg(x.amount) AS avg_amt
OPTIONAL MATCH (:User {id: $uid})-[:PERFORMED]->(rt:Transaction)-[:ON_ACCOUNT]->(a)
WHERE rt.ts >= $since AND rt.ts <= $now
RETURN a.balance AS balance, n, avg_amt, count(rt) AS recent
"""

BALANCE = "MATCH (a:Account {id: $aid}) RETURN a.balance AS balance, a.name AS name"

CREATE_TX = """
MATCH (u:User {id: $uid}), (a:Account {id: $aid})
CREATE (t:Transaction {id: $tid, type: $type, amount: $amount, ts: $now, note: $note,
        flagged: $flagged, flag_reasons: $reasons, balance_after: $bal_after})
CREATE (u)-[:PERFORMED {access_level: $level, access_path: $path, at: $now}]->(t)
CREATE (t)-[:ON_ACCOUNT]->(a)
SET a.balance = $bal_after
"""

CREATE_TX_DEST = """
MATCH (b:Account {id: $bid}), (t:Transaction {id: $tid})
CREATE (t)-[:TO_ACCOUNT]->(b)
SET b.balance = $bal_to, t.to_balance_after = $bal_to
"""

STATEMENT = """
MATCH (a:Account)<-[rel:ON_ACCOUNT|TO_ACCOUNT]-(t:Transaction)
WHERE a.id IN $ids AND t.ts <= $t
OPTIONAL MATCH (u:User)-[pf:PERFORMED]->(t)
OPTIONAL MATCH (t)-[:ON_ACCOUNT]->(src:Account)
OPTIONAL MATCH (t)-[:TO_ACCOUNT]->(dst:Account)
RETURN t.id AS id, t.type AS type, t.amount AS amount, t.ts AS ts, t.note AS note,
       t.flagged AS flagged, t.flag_reasons AS flag_reasons,
       a.id AS account_id, a.name AS account_name,
       u.id AS actor_id, u.name AS actor, pf.access_level AS access_level, pf.access_path AS access_path,
       src.name AS from_account, dst.name AS to_account, type(rel) AS leg,
       CASE type(rel) WHEN 'ON_ACCOUNT' THEN t.balance_after ELSE t.to_balance_after END AS balance_after
ORDER BY t.ts DESC
LIMIT $limit
"""

# Events that can change who has access to an account: those on the account itself, on its
# (inheriting) ancestors, and on groups that hold access to any of them.
AUDIT_SCOPE = _fmt("""
MATCH (a:Account {id: $aid})
OPTIONAL MATCH p = (a)-[:PART_OF*0..@N@]->(anc:Account)
WHERE ALL(rl IN relationships(p) WHERE coalesce(rl.inherits, true) = true)
OPTIONAL MATCH (grp:Group)-[:HAS_ACCESS_TO]->(anc)
RETURN collect(DISTINCT anc.id) + collect(DISTINCT grp.id) AS ids
""", N=config.MAX_DEPTH)

AUDIT_EVENTS = """
MATCH (e:AccessEvent)
WHERE e.ts <= $t AND ($ids IS NULL OR e.target_id IN $ids) AND ($sid IS NULL OR e.subject_id = $sid)
RETURN properties(e) AS ev
ORDER BY ev.ts DESC
LIMIT $limit
"""

FLAGGED = """
MATCH (u:User)-[pf:PERFORMED]->(t:Transaction {flagged: true})-[:ON_ACCOUNT]->(a:Account)
RETURN t.id AS id, t.type AS type, t.amount AS amount, t.ts AS ts, t.flag_reasons AS flag_reasons,
       u.name AS actor, a.name AS account_name, pf.access_path AS access_path
ORDER BY t.ts DESC
LIMIT $limit
"""

LIST_USERS = "MATCH (u:User) RETURN u.id AS id, u.name AS name ORDER BY name"
LIST_GROUPS = "MATCH (g:Group) RETURN g.id AS id, g.name AS name, g.kind AS kind, g.admin_id AS admin_id ORDER BY name"
LIST_ACCOUNTS = ("MATCH (a:Account) RETURN a.id AS id, a.name AS name, a.kind AS kind, a.balance AS balance, "
                 "a:SubAccount AS is_sub ORDER BY name")
NODE_COUNTS = "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count ORDER BY label"
REL_COUNTS = "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY type"
META = "MATCH (m:Meta {key: 'seed'}) RETURN m.now_ms AS now_ms, m.scale AS scale, m.seed AS seed"
