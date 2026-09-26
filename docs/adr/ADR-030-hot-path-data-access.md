# ADR-030: Data access on per-request hot paths

| Field | Value |
|---|---|
| **Status** | Proposed — **awaiting owner review; not implemented** |
| **Date** | 2026-09-26 |

## Decision (proposed)
Keep SQLAlchemy Core for general queries. For the code that runs on every request (session authentication, tenant resolution, grant loading), make three changes:
1. Resolve authentication and the tenant scope in **one transaction** instead of two.
2. Load platform, vertical and tenant grants in **one query**.
3. Execute these statements as **prepared asyncpg statements**, or as cached SQLAlchemy lambda statements, whichever measures better.

Every change must keep the isolation and security suites green, and be re-measured on the real machines.

## Context
Phase 1 measurement (ADR-004 Evidence) found an authenticated, RLS-scoped tenant read costs about 20-40 ms of CPU through the current path. The API process is CPU-bound while PostgreSQL waits. The same two transactions and ten queries on raw asyncpg cost 4.75 ms of CPU. The gap comes from our request-path design (two transactions, about 16 round trips) and from SQLAlchemy's async layer (statement construction and greenlet bridging per statement). It does not come from Python, asyncpg or PostgreSQL.

## Alternatives
Change language or framework (not supported by the evidence); leave as is and add workers (wastes the cost-per-merchant budget); cache grants across requests (adds invalidation risk to authorisation; not before measurement).

## Reason
It targets the measured bottleneck with the smallest change, and does not reopen the stack decision.

## Consequences
A narrow second data-access style in the hot path, which must stay small and well tested. Scheduled as the first task of Phase 2, if approved.
