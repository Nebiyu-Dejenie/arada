# Phase 1 report: platform kernel

Date: 2026-09-26 · Status: **implemented and verified; awaiting owner review** (do not start Phase 2 before it).

## Gates

| Gate | Result | Evidence |
|---|---|---|
| 1. Project foundation | PASS | Image builds (multi-stage, non-root); stack starts; `/readyz` reports the database |
| 2. Database | PASS | 7 migrations; zero → head → base → head round trip; code/schema drift check; runtime role cannot run DDL |
| 3. Identity | PASS | Login, lockout, timing-uniform failures, sessions (idle/absolute/revoke/disabled), TOTP with replay protection, secrets never stored in clear |
| 4. Authorization | PASS | Charter permissions; scoped roles; database-enforced role scopes; MFA-gated privileged scopes; escalation guards |
| 5. Tenancy | PASS | Server-side resolution (slug, Host); FORCE RLS; composite tenant keys; cross-tenant suite over every tenant route |
| 6. Blueprint | PASS | Semantic versions, meta-schema, immutable publication, compatibility classes, pinning, explicit reassignment |
| 7. Audit | PASS | Complete, correlated records for every administrative action; append-only even for owner and superuser; no secrets |
| 8. Feature flags | PASS | Platform, vertical and tenant overrides, blueprint defaults, kill switch, audited |
| 9. Security | PASS | Negative suites: authentication bypass, authorization bypass, IDOR, cross-tenant, escalation, mass assignment, SQL injection, disclosure, secret leakage |
| 10. Reproducibility | PASS | Clean GitHub runner, run [36266214515](https://github.com/Nebiyu-Dejenie/arada/actions/runs/36266214515): all jobs green; `scripts/phase1_demo.sh` 10/10 locally, twice |

## Test results

- 164 tests: unit, integration (database), API, tenant isolation, security. All pass locally and on CI (17 s on CI).
- Coverage: 89% of lines and branches, greenlet-aware. Main gap: the CLI (32%), which is exercised end to end by the demo and CI reproduction rather than by unit tests.
- Static: ruff (lint and format), mypy `--strict` (97 files), import-linter (2 contracts).
- Supply chain: pip-audit found no known vulnerabilities; gitleaks found no leaks across the full history; Trivy found no critical or high fixable vulnerabilities in the image.

## Non-vacuity checks (the tests can fail)

| Deliberate break | Result |
|---|---|
| Every authenticated person treated as owner of any tenant | Cross-tenant route attacks FAIL (3 personas) |
| RLS tenant context never set | 27 tests ERROR (the database refuses writes outside a context: fails closed) |

## Defects found and fixed during Phase 1

1. **Vacuous isolation suite.** FastAPI 0.141 nests included routers in `app.routes`, so route enumeration returned nothing and the suite asserted nothing. Found only by the sabotage check. Fixed by enumerating the OpenAPI document and requiring exact coverage (ADR-032).
2. **NUL byte → 500.** PostgreSQL rejects NUL in text (SQLSTATE 22021). Fixed at the boundary (request bodies reject NUL; strict query patterns) and in the error mapper (class-22 data exceptions → 422).
3. **Vulnerable build tool shipped in the image.** A HIGH finding in `quinn-proto` inside `uv`. Fixed with a multi-stage image.
4. **Coverage blind spot.** SQLAlchemy async runs in greenlets; coverage was under-reported (78% → 89% real). Fixed in the configuration.

## Stack verification (ADR-004)

Full evidence is in ADR-004. In summary: Telegram, tenancy, testing, resource use and maintainability meet the criteria. On the developer laptop (a shared 4-vCPU Docker VM), an authenticated RLS-scoped read is CPU-bound at about 20-55 req/s per worker. **The same ten queries on raw asyncpg cost 4.75 ms CPU**, so the overhead is in the data-access layer and request-path design, not in Python or PostgreSQL. A remedy is proposed in ADR-030 (not applied). Laptop numbers are not sizing numbers.

## Decisions to convert or take

- ADR-004 (backend stack): recommended to move from Assumed to Accepted.
- ADR-030 (hot-path data access): proposed; decide before Phase 2.
- ADR-028 (Phones reference vertical): still Assumed; confirm by Phase 5.
- U9 (repository visibility): code is now public; recommended private.
