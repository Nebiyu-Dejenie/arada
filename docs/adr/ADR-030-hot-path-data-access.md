# ADR-030: Data access on per-request hot paths

| Field | Value |
|---|---|
| **Status** | **Deferred** — owner decision 2026-10-01. **Not implemented; must not be implemented** until the revisit conditions below are met |
| **Date** | 2026-09-26 (proposed) · 2026-10-01 (deferred) |

## Why it is deferred (2026-10-01)
The evidence does not establish the root cause:
- **The 4-worker result contradicts the simple CPU-bound explanation.** One worker managed about 50 req/s on the authenticated tenant read. Four workers at concurrency 40 managed 48.7 req/s, with **no scaling**. If a single CPU-bound Python process were the limit, more processes would have scaled on a 4-vCPU machine. Something shared is limiting throughput instead: the shared, noisy Docker Desktop VM, the database's per-transaction work, round trips, or pool waits. The measurements do not tell which.
- The raw-asyncpg comparison (4.75 ms of CPU against about 21.7 ms), the ApacheBench runs, the in-process profile and the 4-worker run were **ad-hoc**. Only `scripts/measure_api.py` is in the repository, so the numbers cannot be reproduced from it.
- All figures come from a shared developer laptop VM (two runs of the same test gave 54.8 and 22.3 req/s), not from the real machines (U2 is unknown).

The change touches the most security-critical path: authentication, tenant context, RLS and grant loading. It must not go ahead before the tests that would catch a regression there exist.

## Revisit only after all of these exist
1. A **reproducible benchmark harness** committed to the repository: fixed data set, warm-up, repetitions, variance reported, and the raw-driver baseline included.
2. **Profiling** that attributes the time (application CPU, driver, database, pool wait, network), including a multi-worker run that explains the scaling result.
3. **Pool and concurrency isolation tests.** These now exist: `tests/security/test_connection_pool_isolation.py`.
4. **Authorisation-equivalence tests.** For every persona and scope (platform, vertical, tenant, MFA-withheld), the grants from any new query must equal today's grants exactly.
5. **Measurements on the real machines** against an agreed target.

## Decision (as proposed on 2026-09-26; not adopted)
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
If it were ever adopted, the hot path would gain a narrow second data-access style, which would need to stay small and well tested. It is **not** scheduled for Phase 2. The current single data-access style stays in place.

Corrections to the original Context:
- "It does not come from Python, asyncpg or PostgreSQL" is **not established** (see above).
- "The API process is CPU-bound" was observed for one worker only, and the 4-worker run contradicts it being the whole story.

## History
| Date | Change |
|---|---|
| 2026-09-26 | Proposed from Phase 1 measurements. |
| 2026-10-01 | **Deferred** by the owner after the source-level audit. The root cause is not established, the evidence is not reproducible from the repository, and the prerequisite tests were missing. Revisit conditions recorded above. |
