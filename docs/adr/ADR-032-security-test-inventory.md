# ADR-032: Security tests enumerate the OpenAPI contract and must be non-vacuous

| Field | Value |
|---|---|
| **Status** | Accepted — engineering rule adopted after a Phase 1 defect |
| **Date** | 2026-09-26 |

## Decision
Tests that sweep "every route" (authentication bypass, cross-tenant isolation) enumerate the application's **OpenAPI document**, not `app.routes`. They assert an **exact correspondence** between live routes and the test's samples (no uncovered route, no stale sample) plus a minimum count, so an empty or partial inventory fails. New security suites are shown to fail against a deliberately broken implementation before they are trusted.

## Context
The first cross-tenant suite passed while authorisation was deliberately disabled. FastAPI 0.141 nests included routers in `app.routes`, so the suite enumerated zero routes and asserted nothing. Only a deliberate sabotage run revealed it.

## Alternatives
Walking FastAPI internals (fragile across versions); hand-maintained route lists (drift).

## Reason
The OpenAPI document is the public contract of what is served. Exact correspondence turns every new route into a test obligation.

## Consequences
Every new tenant-scoped route must be added to the isolation samples, or the build fails. Recorded sabotage checks: granting everyone owner rights → isolation tests fail; never setting the RLS context → 27 tests error.
