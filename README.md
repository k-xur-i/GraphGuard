# GraphGuard: Graph-Based Access Control and Audit System for Shared Bank Accounts (Neo4j)

Course project, BCSE406L NoSQL Databases, VIT Vellore.
Members : Gouri Dinesh (23BCE2211) | Riya Ann Ignatious (23BCE2176) | Guide: Dr. D. Vivek

All data is **simulated**. No real bank data, no real payments.

## Overview
Shared bank accounts have owners, joint holders, family or business groups, signatories and sub-accounts. Deciding who can do what, and proving it later, is a question about *relationships*. GraphGuard stores those relationships in Neo4j and answers "can this user touch this account, and why?" with one graph query.

## Features
- **Access check with explanation:** direct, via group, or inherited from a parent account; returns the exact path and access level (VIEW, TRANSACT, OWNER).
- **Time travel:** access links are never deleted (`granted_at` / `revoked_at`), so the system can be viewed "as of" any past moment.
- **Grant / revoke** access, each logged as an AccessEvent (GRANT, REVOKE, DENIED).
- **Transactions** (deposit, withdrawal, transfer) that store the access path that allowed them.
- **Fraud rules:** LARGE_AMOUNT, HIGH_VELOCITY, NEW_ACCESS_LARGE_TX.
- **Orphaned access report** and **graph visualisation**.

## Architecture
React (Vite, react-force-graph) -> FastAPI REST API -> Neo4j AuraDB Free (Cypher via the official Python driver).

## Requirements
Python 3.10+, Node 18+, a Neo4j instance (AuraDB Free, or local Neo4j 5). Python packages are in `backend/requirements.txt`; frontend packages in `frontend/package.json`.

## Setup
1. Create a free Neo4j AuraDB instance and keep the connection details it gives you.
2. Configure the backend:
   ```
   cd backend
   cp .env.example .env        # Windows: copy .env.example .env
   # edit .env: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
   pip install -r requirements.txt
   ```
   `.env` is git-ignored. **Never commit it.**
3. Create schema and load seed data (constraints, indexes, simulated dataset):
   ```
   python -m app.seed_loader
   ```
   Seed 42 gives 68 users, 22 groups, 60 accounts, 455 transactions and 191 access events.
4. Check the database against an independent Python reference model:
   ```
   python -m app.verify
   ```

## Run
```
cd backend && uvicorn app.main:app --reload     # API at http://localhost:8000 (docs at /docs)
cd frontend && npm install && npm run dev        # UI at http://localhost:5173
```

## Tests
```
cd backend && python -m pytest -q tests
```
Six tests compare the reference access model with a SQLite recursive-CTE implementation.

## Data model
Nodes: `User`, `Group`, `Account` (+ `SubAccount`), `Transaction`, `AccessEvent`.
Relationships: `MEMBER_OF`, `OWNS`, `AUTHORIZED_SIGNATORY_OF`, `HAS_ACCESS_TO`, `PART_OF`, `PERFORMED`, `ON_ACCOUNT`, `TO_ACCOUNT`.

## Screenshots
See `docs/screenshots/`.

## Team contributions
| Member | Reg. No. | Contribution |
|---|---|---|
| Gouri Dinesh | 23BCE2211 | (fill in) |

## Limitations
No real authentication, no balance locking, append-only ledger enforced at API level only, single database instance, simulated data.
