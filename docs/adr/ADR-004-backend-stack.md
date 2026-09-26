# ADR-004: Backend stack: Python + FastAPI

| Field | Value |
|---|---|
| **Status** | Assumed — Phase 1 verification complete (see Evidence); recommended for Accepted, awaiting owner decision |
| **Date** | 2026-09-26 |

## Decision
Python 3.12+ (images pin an exact minor version), FastAPI, Pydantic v2 + pydantic-settings (typed configuration), SQLAlchemy 2 Core over asyncpg, Alembic, aiogram 3.

## Context
The owner has not specified a stack. The development workstation has Python 3.12, Node 22 and Docker. Webhook-heavy, I/O-bound workloads dominate.

## Alternatives
Spring Boot / Java; Go; NestJS / TypeScript.

## Reason
Strong async I/O ecosystem, mature Telegram library, fast iteration, strict typing via mypy, and prior in-house experience with these patterns.

## Consequences
CPU-bound hotspots, if measured, are extracted into a faster runtime later. Changing the stack after Phase 1 would be expensive, so an override should come before Phase 1 starts.

## Evidence (Phase 1 stack verification, 2026-09-26)

Measured on the development workstation: 4 vCPU Docker Desktop VM on WSL2, shared with other projects' containers. These figures are **indicative only**; production sizing waits for the real machines (U2).

| Criterion | Evidence | Verdict |
|---|---|---|
| Telegram Mini Apps | aiogram 3.31.0 implements Bot API 10.3, the current version, which includes managed bots. `cryptography` covers the Ed25519 `initData` signature. `@telegram-apps/sdk-react` 3.3.9 exists for the frontend. | Meets |
| Multi-tenancy | PostgreSQL RLS driven per transaction through asyncpg `set_config(..., true)`. Cross-tenant suites attack every tenant route; deliberately disabling authorisation, or the RLS context, makes them fail. | Meets |
| Financial correctness | Python integers are exact at any size; `Decimal` is available; the database enforces constraints and triggers. No money code exists yet (Phase 4). | Meets (for Phase 1) |
| Testing | 164 tests against real PostgreSQL in about 60 s; mypy strict; import contracts; in-process ASGI testing. | Meets |
| Resources | API process about 65-77 MiB RSS idle and under load (1 worker); PostgreSQL about 50-100 MiB; image 484 MB (no build tools). | Meets |
| Maintainability | Strict typing, module boundaries enforced in CI, explicit SQL through SQLAlchemy Core. | Meets |
| Performance | `/healthz` about 518 req/s on 1 worker. An authenticated, RLS-scoped tenant read managed only about 20-55 req/s on 1 worker, and the API process was CPU-bound (about 98%) while PostgreSQL waited ("idle in transaction"). **The same two transactions and ten queries on raw asyncpg cost 4.75 ms CPU (about 9.6 ms wall) per request**, which is about 200 req/s per core. The overhead is therefore in the data-access layer and the request path design (two transactions, about 16 round trips, per-statement construction and greenlet bridging), not in Python, asyncpg or PostgreSQL. | Meets, with a proposed remedy (ADR-030) |
| Future scaling | Stateless process; horizontal replicas behind the proxy; per-worker scaling. (A 4-worker experiment on this shared VM did not show scaling; the VM was saturated by the load generator, database and other stacks, so the result is inconclusive and must be repeated on real hardware.) | Meets in design; measure on real machines |

## History
| Date | Change |
|---|---|
| 2026-09-26 | Created as a documented assumption (Phase 0). |
| 2026-09-26 | Phase 1 verification against the owner's criteria recorded in Evidence. No evidence that a different language or framework is needed. A data-access amendment for per-request hot paths is proposed separately (ADR-030), not applied. |
