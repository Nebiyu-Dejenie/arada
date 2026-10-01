# 21 — Implementation Status

**This is the source of truth for what exists.** Other documents describe the target architecture. This one says what is built.

Labels:

| Label | Meaning |
|---|---|
| **Implemented** | The code exists and automated tests prove it |
| **Planned** | Designed, scheduled for the phase named |
| **Assumed** | A documented assumption (Permanent Command §53) |
| **Deferred** | Intentionally postponed, with the reason given |

Last updated: 2026-10-01, Phase 1 corrective pass after the source-level audit (awaiting owner review; Phase 2 blocked).

## Phase 1: platform kernel

| Capability | Status | Evidence / where |
|---|---|---|
| Project structure: modular monolith with import contracts | Implemented | `backend/src/arada/*`; `lint-imports` in CI |
| Typed central configuration; `ROOT_DOMAIN` as configuration (TBD) | Implemented | `kernel/config.py`; production guards tested |
| Database foundation: schema `control`, 9 migrations, least-privilege roles | Implemented | `backend/migrations/`; zero → head → base → head round trip tested |
| Code/schema drift detection | Implemented | `tests/integration/test_migrations.py` |
| UUIDv7 identifiers | Implemented | `kernel/ids.py` |
| Identity: persons, provider identities, argon2id passwords, lockout | Implemented | `identity/`; `tests/api/test_identity.py` |
| Sessions: opaque, hashed, idle and absolute expiry, revocation | Implemented | ADR-029 |
| Session rotation when a session becomes MFA-verified (old token revoked; absolute expiry kept) | Implemented (2026-10-01) | ADR-035; `test_mfa_confirmation_rotates_the_session`, `test_pre_mfa_token_never_gains_privileged_access` |
| Password hashing kept outside database transactions | **Missing** (found 2026-10-01) | `identity/service.py:create_person_with_password` hashes inside the caller's transaction. Under heavy load the server's 30 s idle-in-transaction limit killed the session once (`PHASE_1_CORRECTIVE.md` §10). Fix together with B4 |
| Authentication rate limiting (per IP, global) | **Missing: REQUIRED BEFORE PUBLIC EXPOSURE** | Register B4. Only per-account lockout exists; argon2id cost per attempt is a resource-exhaustion vector |
| TOTP MFA (encrypted secret, replay-proof) | Implemented | `identity/totp.py` |
| Envelope encryption (AES-GCM, versioned KEK, AAD-bound) | Implemented | `kernel/crypto.py` |
| Scoped RBAC: platform, vertical, tenant; charter permission names | Implemented | `rbac/`; ADR-025 |
| MFA-gated privileged scopes (platform, vertical) | Implemented | `test_privileged_roles_require_an_mfa_verified_session` |
| MFA-gated privileged tenant roles (owner, admin, finance) | Implemented (2026-10-01) | ADR-035; `tests/api/test_tenant_mfa.py` |
| Privilege-escalation guards (subset rule, no self-change, last owner) | Implemented | `tests/api/test_tenancy.py`, `test_platform_rbac.py` |
| Last-SUPER_ADMIN guard; SUPER_ADMIN revocation | Implemented (2026-10-01). **It was broken before:** revoking any SUPER_ADMIN failed | ADR-033; `tests/integration/test_super_admin_invariant.py` |
| Tenancy: tenants (merchants), lifecycle, merchant profile, domains table | Implemented | `tenancy/service.py` |
| Server-side tenant resolution (slug for the console, Host header for the storefront) | Implemented | `access/scopes.py`; `test_storefront_resolves_tenant_from_host_only` |
| RLS on every table with a `tenant_id` (9 tables), composite tenant foreign keys, narrow resolvers | Implemented (extended 2026-10-01) | migrations 0006, 0009; ADR-002, ADR-034; `tests/security/test_rls_coverage.py` |
| RLS policy lint (catalogue test) | Implemented (2026-10-01) | `test_every_table_with_a_tenant_id_is_under_forced_rls` |
| Connection-pool and concurrent tenant isolation tests | Implemented (2026-10-01) | `tests/security/test_connection_pool_isolation.py` |
| Platform-reader (BYPASSRLS) allow-list | Implemented (2026-10-01) | `test_platform_reader_is_used_only_by_allow_listed_functions` |
| Memberships and single-use invitations | Implemented | `tenancy/members.py` |
| Verticals | Implemented | `verticals/` |
| Blueprint foundation: blueprints, semantic versions, meta-schema, immutable publication, compatibility classes, database-computed content hash | Implemented | `blueprints/`; `tests/api/test_blueprints.py` |
| Tenant blueprint pinning and explicit reassignment with history | Implemented | `tenancy/service.assign_blueprint` |
| Vertical extension registry (`imei.luhn`) | Implemented | `blueprints/extensions.py` |
| Phones seed blueprints 1.0.0 / 1.1.0 / 2.0.0 | Implemented (data) | `blueprints/phones/` |
| Feature flags: platform, vertical, tenant, blueprint defaults, kill switch | Implemented | `flags/`; ADR-031 |
| Audit: append-only for the application, correlated, RLS-scoped, sanitised. Tamper-resistant, **not tamper-proof or tamper-evident**: the schema owner or a superuser can bypass it (`09` §12) | Implemented | `audit/`; `tests/api/test_audit_trail.py`; `test_known_limitation_schema_owner_can_disable_audit_guards` |
| Correlation: request_id, W3C trace, tenant_id, user_id; structured JSON logs with redaction | Implemented | `api/middleware.py`, `kernel/logging.py` |
| RFC 9457 errors with no disclosure; NUL-safe input | Implemented | `tests/security/test_input_and_disclosure.py` |
| Security negative suites (authentication bypass, IDOR, cross-tenant, escalation, mass assignment, injection, disclosure, secret leakage) | Implemented | `tests/security/` |
| CI: lint (ruff incl. `S` rules), strict types, boundaries, tests, pip-audit, gitleaks, fresh-stack Definition-of-Done, Trivy image scan (gates CRITICAL with a fix only) | Implemented | `.github/workflows/ci.yml` |
| SAST (Semgrep or Bandit), SBOM, image digest pinning, scheduled vulnerability scans | Planned (first deployment gate) | `09` §11 |
| Local reproduction from zero | Implemented | `scripts/phase1_demo.sh`; runbook |
| Hot-path data-access optimisation | **Deferred** (owner, 2026-10-01) | ADR-030: root cause not established; revisit conditions recorded |

## Deliberately not in Phase 1

| Item | Status | Reason / phase |
|---|---|---|
| Frontend (Mini App, consoles) | Planned, Phase 2+ | The owner scoped Phase 1 to the platform kernel |
| Telegram bots, `initData` validation, webhooks | Planned, Phase 2 | Owner: no production bots in Phase 1 |
| Outbox and inbox (domain events) | Planned, Phase 2 | First consumer arrives with notifications and Telegram |
| Redis (rate limits, dedupe) | Planned, Phase 2 | Not needed until webhooks and rate limiting |
| Catalog, search, orders, reviews | Planned, Phase 3 | Out of scope |
| Payments, ledger, commissions, payouts | Planned, Phase 4 | Out of scope; settlement model blocked on U4 |
| `commerce`, `finance`, `ops` schemas; tenant placement | Planned, Phases 2-4 | Created with their first tables (ADR-003 history) |
| Blueprint data migrations (plans, preview, rollback of data) | Planned, Phase 6 | No blueprint-bound tenant data exists yet |
| Passkeys, step-up re-authentication, maker-checker, just-in-time support access, TOTP reset/recovery, per-tenant staff-MFA policy | Planned | ADR-025 / ADR-029 / ADR-035 |
| Console cookies and CSRF | Planned, with the console UI | No browser surface yet |
| Prometheus, Loki, Grafana, trace backend | Deferred, until first deployment | Owner: do not overbuild monitoring before deployment |
| Backups (pgBackRest, off-host) | Deferred, until first deployment | Needs U2 and U3 |
| Domain and Cloudflare provisioning | Deferred, Phase 6 | `ROOT_DOMAIN` TBD (U1) |
| Plans and entitlements | Planned, Phase 6 | — |
| Production compose, Ansible, Terraform | Deferred, until first deployment | Needs U2 |

## Assumed (unchanged)

- A1: Python/FastAPI backend. Verified, recommended for Accepted (ADR-004).
- A2: React/TypeScript frontend (ADR-005).
- A3: Phones reference vertical (ADR-028).
- A4-A6: see `20_DECISIONS.md`.
