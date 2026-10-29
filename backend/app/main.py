from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable
from pydantic import BaseModel, Field

from . import config, db, queries as Q, services as S
from .timeutil import now_ms, parse_as_of


@asynccontextmanager
async def lifespan(app):
    yield
    db.close_driver()


app = FastAPI(title="GraphGuard API", version="1.0",
              description="Graph-based access control & audit for shared (simulated) bank accounts.",
              lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ServiceUnavailable)
@app.exception_handler(AuthError)
async def neo4j_down(_, exc):
    return JSONResponse(status_code=503, content={"detail": f"Cannot reach Neo4j: {exc}"})


@app.exception_handler(Neo4jError)
async def neo4j_error(_, exc):
    return JSONResponse(status_code=500, content={"detail": f"Neo4j error: {exc.message}"})


def _http(res):
    """Turn a service result with a non-OK status into an HTTP error."""
    code = {"OK": 200, "FORBIDDEN": 403, "DENIED": 403, "NOT_FOUND": 404, "CONFLICT": 409, "INVALID": 422}
    if res["status"] != "OK":
        raise HTTPException(code.get(res["status"], 400), detail=res.get("detail", res["status"]))
    return res


# ------------------------------------------------------------------ models
class GrantReq(BaseModel):
    subject_id: str
    target_id: str
    rel_type: Literal["OWNS", "AUTHORIZED_SIGNATORY_OF", "HAS_ACCESS_TO", "MEMBER_OF"]
    level: Literal["VIEW", "TRANSACT"] = "VIEW"
    actor_id: str
    reason: str = ""


class RevokeReq(BaseModel):
    subject_id: str
    target_id: str
    rel_type: Optional[Literal["OWNS", "AUTHORIZED_SIGNATORY_OF", "HAS_ACCESS_TO", "MEMBER_OF"]] = None
    actor_id: str
    reason: str = ""


class TxReq(BaseModel):
    user_id: str
    account_id: str
    type: Literal["DEPOSIT", "WITHDRAWAL", "TRANSFER"]
    amount: float = Field(gt=0, le=10_000_000)
    to_account_id: Optional[str] = None
    note: str = Field("", max_length=140)


# ------------------------------------------------------------------ meta / lookups
@app.get("/health")
def health():
    ok, err = db.ping()
    return {"status": "ok" if ok else "degraded", "neo4j": ok, "error": err}


@app.get("/stats")
def stats():
    def f(tx):
        return {"nodes": db.rows(tx, Q.NODE_COUNTS), "relationships": db.rows(tx, Q.REL_COUNTS),
                "seed": (db.rows(tx, Q.META) or [None])[0]}
    return db.read(f)


@app.get("/users")
def users():
    return db.read(lambda tx: db.rows(tx, Q.LIST_USERS))


@app.get("/groups")
def groups():
    return db.read(lambda tx: db.rows(tx, Q.LIST_GROUPS))


@app.get("/accounts")
def accounts():
    return db.read(lambda tx: db.rows(tx, Q.LIST_ACCOUNTS))


# ------------------------------------------------------------------ access
@app.get("/access/check")
def access_check(user_id: str, account_id: str, as_of: Optional[str] = None):
    return db.read(S.check_access, user_id, account_id, parse_as_of(as_of))


@app.get("/users/{user_id}/accounts")
def user_accounts(user_id: str, as_of: Optional[str] = None):
    return db.read(S.accounts_for_user, user_id, parse_as_of(as_of))


@app.get("/accounts/{account_id}/access")
def account_access(account_id: str, as_of: Optional[str] = None):
    """Who has (or had, if as_of is in the past) access to this account."""
    return db.read(S.who_has_access, account_id, parse_as_of(as_of))


@app.get("/accounts/{account_id}/access-diff")
def account_access_diff(account_id: str, from_ts: str = Query(..., alias="from"), to: Optional[str] = None):
    return db.read(S.access_diff, account_id, parse_as_of(from_ts), parse_as_of(to))


@app.post("/access/grant")
def access_grant(req: GrantReq):
    return _http(db.write(S.grant, req.subject_id, req.target_id, req.rel_type, req.level,
                          req.actor_id, req.reason or "Granted via API", now_ms()))


@app.post("/access/revoke")
def access_revoke(req: RevokeReq):
    return _http(db.write(S.revoke, req.subject_id, req.target_id, req.rel_type, req.actor_id,
                          req.reason or "Revoked via API", now_ms()))


# ------------------------------------------------------------------ transactions
@app.post("/transactions")
def new_transaction(req: TxReq):
    res = db.write(S.create_transaction, req.user_id, req.account_id, req.type, req.amount,
                   req.to_account_id, req.note, now_ms())
    return _http(res)


@app.get("/accounts/{account_id}/transactions")
def account_statement(account_id: str, as_of: Optional[str] = None, viewer_id: Optional[str] = None,
                      limit: int = Query(100, le=500)):
    """Bank-statement view. If viewer_id is given, the viewer must have had access at as_of."""
    t = parse_as_of(as_of)

    def f(tx):
        if viewer_id:
            acc = S.check_access(tx, viewer_id, account_id, t)
            if not acc["can_view"]:
                return None
        return S.statement(tx, [account_id], t, limit)

    out = db.read(f)
    if out is None:
        raise HTTPException(403, "Viewer had no access to this account at that time.")
    return out


@app.get("/users/{user_id}/visible-transactions")
def visible_transactions(user_id: str, as_of: Optional[str] = None, limit: int = Query(100, le=500)):
    """All transactions the user could see at as_of (history up to as_of, on accounts they could view then)."""
    t = parse_as_of(as_of)

    def f(tx):
        ids = [a["account_id"] for a in S.accounts_for_user(tx, user_id, t)]
        return S.statement(tx, ids, t, limit) if ids else []

    return db.read(f)


@app.get("/transactions/flagged")
def flagged(limit: int = Query(50, le=200)):
    return db.read(lambda tx: db.rows(tx, Q.FLAGGED, limit=limit))


# ------------------------------------------------------------------ audit
@app.get("/audit/events")
def audit(account_id: Optional[str] = None, subject_id: Optional[str] = None, as_of: Optional[str] = None,
          limit: int = Query(100, le=500)):
    return db.read(S.audit_events, account_id, subject_id, parse_as_of(as_of), limit)


@app.get("/audit/orphaned-access")
def orphaned(as_of: Optional[str] = None):
    return db.read(S.orphaned_access, parse_as_of(as_of))


# ------------------------------------------------------------------ graph view
@app.get("/graph/focus/{account_id}")
def graph_focus(account_id: str, as_of: Optional[str] = None):
    return db.read(S.focus_graph, account_id, parse_as_of(as_of))


# ------------------------------------------------------------------ admin
@app.post("/admin/reseed")
def reseed(scale: int = Query(1, ge=1, le=5)):
    if not config.ENABLE_ADMIN:
        raise HTTPException(403, "Admin endpoints are disabled (ENABLE_ADMIN=0).")
    from . import seed_loader
    return seed_loader.reseed(scale=scale)
