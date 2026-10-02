# 21 — Implementation Status

**This is the source of truth for what exists.** Other documents describe the target architecture. This one says what is built.

Labels:

| Label | Meaning |
|---|---|
| **Implemented** | The code exists and automated tests prove it |
| **Planned** | Designed, scheduled for the phase named |
| **Assumed** | A documented assumption (Permanent Command §53) |
| **Deferred** | Intentionally postponed, with the reason given |

Last updated: 2026-10-02. Phase 1 is **approved**. Phase 2 (Telegram foundation) is implemented, independently audited and hardened on 2026-10-02, and **awaits owner review**; the live test-environment sample (A8) is outstanding. Nothing is production-ready: **B4 (authentication rate limiting) is open**.

## Phase 1: platform kernel

| Capability | Status | Evidence / where |
|---|---|---|
| Project structure: modular monolith with import contracts | Implemented | `backend/src/arada/*`; `lint-imports` in CI |
| Typed central configuration; `ROOT_DOMAIN` as configuration (TBD) | Implemented | `kernel/config.py`; production guards tested |
| Database foundation: schemas `control` and `commerce` (Phase 2), 11 migrations, least-privilege roles | Implemented | `backend/migrations/`; zero → head → base → head round trip tested |
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

## Phase 2: Telegram foundation

Evidence and test lists are in `reports/PHASE_2.md`.

| Capability | Status | Evidence / where |
|---|---|---|
| Mini App `initData` validator: HMAC (`WebAppData` key) + mandatory Ed25519 + bot binding + freshness, pure module | Implemented | `telegram/miniapp.py`; ADR-012 (Accepted); `tests/unit/test_telegram_miniapp.py` |
| Telegram environment separation (test or production key; production refuses the test key) | Implemented | `kernel/config.py`; `test_production_refuses_the_test_key_and_any_mismatch` |
| Conformance with live Telegram data (assumption A8: form decoding, UTF-8) | **Not yet verified** | Owner-run `scripts/telegram_sample_check.py` on a test-environment sample; never committed |
| Merchant-owned bot binding (admin supplies `bot_id` and token; token envelope-encrypted; no Telegram call) | Implemented | `bots/service.py`; `PUT/GET/DELETE /v1/platform/tenants/{id}/telegram-bot`; D6 |
| Host → tenant → that tenant's bot (client never names a tenant) | Implemented | `customers/telegram_login.py`; `test_client_supplied_tenant_hints_never_choose_the_tenant` |
| Telegram identity → global person → per-tenant customer (`commerce.customers`) | Implemented | `identity/telegram.py`, `customers/service.py`; race test |
| Customer sessions: opaque, server-side, bound to tenant and customer by FORCE RLS | Implemented | ADR-036; `customers/sessions.py`; `access/customer.py` |
| Replay window per `initData` (reuse window + use cap; our policy) | Implemented | `bots/service.py:record_init_data_use`; concurrent replay test; prune margin `test_replay_rows_outlive_the_freshness_window` |
| Forward-only invariants in the database: customer-session revocation, bot disabling, replay counters | Implemented | Migration 0011; `test_revocation_disabling_and_replay_counts_only_move_forward` |
| Generic 401 for every failed Telegram login; reason in logs only | Implemented | D5; `test_every_rejection_is_the_same_generic_401_with_a_logged_reason` |
| Customer and staff credentials never interchangeable | Implemented | OpenAPI-driven sweep `test_customer_tokens_are_refused_by_every_staff_operation` |
| Audit: person and customer creation, customer login and logout, bot registration and disabling, with request and trace ids | Implemented | `test_logins_are_audited_inside_the_tenant_with_correlation_ids` |
| Failure metrics | **Logs only** | No metrics backend exists (deferred with monitoring); failures are `telegram.auth_failed` log events with a `reason` field |
| Authentication rate limiting on `/v1/storefront/auth/telegram` | **Missing: REQUIRED BEFORE PUBLIC EXPOSURE** | Register B4 applies to this endpoint too |

## Deliberately not in Phase 1

| Item | Status | Reason / phase |
|---|---|---|
| Frontend (Mini App, consoles) | Planned, later phase (a Phase 2 non-goal) | The owner scoped Phases 1 and 2 to the backend |
| Telegram webhooks, deep links, notifications, managed bots, outbound Bot API calls | **Not in Phase 2 either** (owner's non-goals) | `reports/PHASE_2_PLAN.md` §3 |
| Outbox and inbox (domain events) | Planned, with webhooks or notifications | No Phase 2 consumer exists |
| Redis (rate limits, dedupe) | Not introduced (Phase 2 non-goal) | Replay control uses PostgreSQL |
| Catalog, search, orders, reviews | Planned, Phase 3 | Out of scope |
| Payments, ledger, commissions, payouts | Planned, Phase 4 | Out of scope; settlement model blocked on U4 |
| `finance`, `ops` schemas; tenant placement | Planned, Phases 3-4 | Created with their first tables. `commerce` was created in Phase 2 with `customers` |
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
