"""The same access-control problem in a relational schema (SQLite), for the comparison in objective 6.

Schema (what a normal developer would build):
    users, groups, accounts(parent_id, inherits), memberships, grants
Access resolution needs a RECURSIVE CTE for the sub-account hierarchy plus joins to
grants and memberships, with the temporal filter repeated in both places.
"""
import sqlite3

SCHEMA = """
CREATE TABLE users(id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE groups(id TEXT PRIMARY KEY, name TEXT, admin_id TEXT);
CREATE TABLE accounts(id TEXT PRIMARY KEY, name TEXT, kind TEXT, parent_id TEXT, inherits INTEGER);
CREATE TABLE memberships(user_id TEXT, group_id TEXT, granted_at INTEGER, revoked_at INTEGER);
CREATE TABLE grants(src_type TEXT, src_id TEXT, account_id TEXT, rel TEXT, level TEXT,
                    granted_at INTEGER, revoked_at INTEGER);
CREATE INDEX ix_mem_user ON memberships(user_id);
CREATE INDEX ix_mem_group ON memberships(group_id, user_id);
CREATE INDEX ix_grants_acct ON grants(account_id);
CREATE INDEX ix_grants_src ON grants(src_type, src_id);
"""

CHECK_SQL = """
WITH RECURSIVE anc(id, hops) AS (
    SELECT :aid, 0
    UNION ALL
    SELECT a.parent_id, anc.hops + 1
    FROM anc JOIN accounts a ON a.id = anc.id
    WHERE a.parent_id IS NOT NULL AND a.inherits = 1 AND anc.hops < :maxd
)
SELECT MAX(CASE g.rel WHEN 'OWNS' THEN 3 WHEN 'AUTHORIZED_SIGNATORY_OF' THEN 2
                       ELSE CASE g.level WHEN 'TRANSACT' THEN 2 ELSE 1 END END) AS rank
FROM anc
JOIN grants g ON g.account_id = anc.id
WHERE g.granted_at <= :t AND (g.revoked_at IS NULL OR g.revoked_at > :t)
  AND ( (g.src_type = 'User' AND g.src_id = :uid)
     OR (g.src_type = 'Group' AND EXISTS (
            SELECT 1 FROM memberships m
            WHERE m.group_id = g.src_id AND m.user_id = :uid
              AND m.granted_at <= :t AND (m.revoked_at IS NULL OR m.revoked_at > :t))) )
"""


def build(ds):
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO users VALUES (?,?)", [(u["id"], u["name"]) for u in ds.users])
    con.executemany("INSERT INTO groups VALUES (?,?,?)", [(g["id"], g["name"], g["admin_id"]) for g in ds.groups])
    con.executemany("INSERT INTO accounts VALUES (?,?,?,?,?)",
                    [(a["id"], a["name"], a["kind"], a["parent_id"], int(a["inherits"])) for a in ds.accounts])
    con.executemany("INSERT INTO memberships VALUES (?,?,?,?)",
                    [(m["user_id"], m["group_id"], m["granted_at"], m["revoked_at"]) for m in ds.memberships])
    con.executemany("INSERT INTO grants VALUES (?,?,?,?,?,?,?)",
                    [(g["src_type"], g["src_id"], g["dst_id"], g["rel"], g["level"], g["granted_at"], g["revoked_at"])
                     for g in ds.grants])
    con.commit()
    return con


def check(con, uid, aid, t, max_depth=8):
    """Returns 0 (no access), 1 (VIEW), 2 (TRANSACT) or 3 (OWNER)."""
    row = con.execute(CHECK_SQL, {"uid": uid, "aid": aid, "t": t, "maxd": max_depth}).fetchone()
    return row[0] or 0


# The access-PATH explanation in SQL. Compare its length and nesting with the single Cypher MATCH
# in backend/app/queries.py (check_query) when you write the "query complexity" part of the report.
EXPLAIN_SQL = """
WITH RECURSIVE anc(id, hops, chain) AS (
    SELECT :aid, 0, (SELECT name FROM accounts WHERE id = :aid)
    UNION ALL
    SELECT a.parent_id, anc.hops + 1, p.name || ' <-[PART_OF]- ' || anc.chain
    FROM anc
    JOIN accounts a ON a.id = anc.id
    JOIN accounts p ON p.id = a.parent_id
    WHERE a.inherits = 1 AND anc.hops < :maxd
)
SELECT rank, hops, path FROM (
    SELECT CASE g.rel WHEN 'OWNS' THEN 3 WHEN 'AUTHORIZED_SIGNATORY_OF' THEN 2
                      ELSE CASE g.level WHEN 'TRANSACT' THEN 2 ELSE 1 END END AS rank,
           1 + anc.hops AS hops,
           u.name || ' -[' || g.rel || ']-> ' || anc.chain AS path
    FROM anc
    JOIN grants g ON g.account_id = anc.id AND g.src_type = 'User' AND g.src_id = :uid
    JOIN users u ON u.id = :uid
    WHERE g.granted_at <= :t AND (g.revoked_at IS NULL OR g.revoked_at > :t)
    UNION ALL
    SELECT CASE g.rel WHEN 'OWNS' THEN 3 WHEN 'AUTHORIZED_SIGNATORY_OF' THEN 2
                      ELSE CASE g.level WHEN 'TRANSACT' THEN 2 ELSE 1 END END,
           2 + anc.hops,
           u.name || ' -[MEMBER_OF]-> ' || gr.name || ' -[' || g.rel || ']-> ' || anc.chain
    FROM anc
    JOIN grants g ON g.account_id = anc.id AND g.src_type = 'Group'
    JOIN memberships m ON m.group_id = g.src_id AND m.user_id = :uid
                      AND m.granted_at <= :t AND (m.revoked_at IS NULL OR m.revoked_at > :t)
    JOIN groups gr ON gr.id = g.src_id
    JOIN users u ON u.id = :uid
    WHERE g.granted_at <= :t AND (g.revoked_at IS NULL OR g.revoked_at > :t)
)
ORDER BY rank DESC, hops ASC
LIMIT 1
"""


def explain(con, uid, aid, t, max_depth=8):
    """(rank, hops, path text) of the best access path, or None."""
    return con.execute(EXPLAIN_SQL, {"uid": uid, "aid": aid, "t": t, "maxd": max_depth}).fetchone()
