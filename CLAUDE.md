# ARADA — operating rules for engineering agents

This file condenses the owner's charter for day-to-day work. The full text governs:
[`docs/charter/PERMANENT_COMMAND.md`](docs/charter/PERMANENT_COMMAND.md) (governs) and [`docs/charter/MASTER_DIRECTIVE.md`](docs/charter/MASTER_DIRECTIVE.md) (business model). Precedence and resolved conflicts are in [`docs/charter/README.md`](docs/charter/README.md).

## What ARADA is

A multi-tenant commerce operating system and merchant factory: `PLATFORM → VERTICAL → BLUEPRINT (versioned) → MERCHANT TENANT`. It is one shared runtime with strict logical tenant isolation. It is **never** per-merchant code, containers, databases or domains unless an explicit isolation-tier decision says so.

## Before any work

1. Read `docs/20_DECISIONS.md`: the ADR index (`docs/adr/`) and the question register (KNOWN / ASSUMED / UNKNOWN / BLOCKING). Do not re-litigate accepted ADRs; supersede them with a new ADR instead.
2. Classify every feature as **platform**, **vertical**, **tenant** or **customer** level, and do not mix levels.
3. For significant changes, follow the change-management steps: inspect, affected modules, dependencies, migrations, security, compatibility, tests, implement, verify, document.

## Priorities

Correctness → security → maintainability → extensibility → reliability → cost efficiency → scale. Tenant isolation and financial integrity are part of correctness and security. Never trade them for speed.

## Hard rules

- Tenant context is resolved **server-side** (host, validated Telegram `initData`, session membership, signed internal metadata). Never trust a client-supplied `tenant_id` or `X-Tenant-ID`, and never let business logic guess the tenant.
- Never trust `initDataUnsafe`. Validate `initData` server-side: HMAC + Ed25519 `signature` + bot binding + freshness.
- Never invent Telegram APIs. Verify capabilities against the current official Bot API docs before building on them.
- Money uses integer minor units with an explicit currency. There is no float anywhere. Payment state is not accounting state: the double-entry ledger is authoritative, append-only and idempotent. SMS alone is never proof of payment.
- Do not assume the platform may legally hold or settle funds. Settlement Model A (merchant-direct) is the default until legal review.
- `ROOT_DOMAIN = TBD`. It is configuration only; never hard-code hostnames. **Never use or connect `arada.fun` or `arada.click`**; they belong to unrelated projects.
- Never invent credentials, domains, IPs, server resources, payment configuration or legal permissions. Use placeholders.
- No secrets in the repository, which is **public**: no tokens, keys, passwords or credentials in code, fixtures, docs, logs or git history.
- No public origin: nothing is exposed except through Cloudflare Tunnel, there are no `ports:` in production compose, and Postgres and Redis are never public.
- AI never gets raw database or SQL access. It uses authorized tools only, and financial or destructive actions need explicit human confirmation.
- No premature complexity: modular monolith, Docker Compose, Postgres search (FTS + trigram) and a Postgres outbox. No Kubernetes, Kafka or OpenSearch until metrics justify them (ADR-001/016/018/020).
- No fake implementations of payments, Telegram auth, Cloudflare provisioning, bot provisioning, settlement or database security. Unavailable dependencies sit behind an adapter with a documented boundary; mocks are allowed only in tests.

## Question policy

Classify unknowns as KNOWN / ASSUMED / UNKNOWN / BLOCKING and record them in the register in `docs/20_DECISIONS.md`.

- If an unknown is not blocking, document an assumption and continue.
- Stop and ask only when a question blocks the **next** phase, or when the action is destructive, irreversible, legally unsafe or a risk to tenant isolation.

## Definition of done

Architecture, implementation, database, migration, authorization, tenant isolation, tests (including cross-tenant negative tests), observability, error handling, audit, documentation, security, rollback plan, and deployment verification — each at the appropriate level. Never report "done" when only code exists.

## Report format for significant work

1. Understanding
2. Current state
3. Impact
4. Architectural decision
5. Risks
6. Plan
7. Implementation
8. Verification (tests, lint, types, migrations, security, health)
9. Result
10. Remaining

## Git

- Conventional commits: `feat(tenancy): …`, `fix(auth): …`, `test(finance): …`, `docs(architecture): …`.
- Never commit secrets, and never rewrite history unnecessarily.
- Record every significant decision as an ADR in `docs/adr/` using the fields: Decision, Context, Alternatives, Reason, Consequences, Date, Status.

## Current status

- Phase 0 (discovery and architecture) is complete.
- Phase 1 (platform kernel) is **APPROVED** (owner, 2026-10-01, at `4896f60`). Do not reopen or redesign it without new evidence of a regression or architectural defect.
- **Phase 2 = Telegram foundation** is **implemented and awaits the owner's review** (`docs/reports/PHASE_2.md`). Outstanding owner actions: the live test-environment sample (A8, `scripts/telegram_sample_check.py`) and the pre-completion docs re-check. Scope stays the owner's ten items. Webhooks, deep links, notifications, managed bots, frontend and Redis are non-goals. **Do not start Phase 3.**
- Approval is **not** authorisation to deploy: no production DNS, Cloudflare tunnels, exposed services, production credentials or payment integrations. Docker is for development and testing only.
- ADR-030 is **Deferred**; do not implement it. **AUTH RATE LIMITING = REQUIRED BEFORE PUBLIC EXPOSURE** (register B4). Nothing may be called production-ready until it is implemented and verified.
- Register B5 is **resolved**. Telegram rules: never derive `bot_id` from the token (A9/D6); never use `initDataUnsafe`; the validator (`arada.telegram.miniapp`) stays pure and implements only the Mini App mechanism, not the Login Widget or OIDC. Every failed Telegram login is one generic 401, with the reason in logs only. Customer sessions are opaque and tenant-bound (ADR-036); never introduce JWT or refresh tokens for them without a new ADR.
- What exists: `docs/21_IMPLEMENTATION_STATUS.md`.

## Commands

- Local stack: `./scripts/init-env.sh && docker compose up -d --build --wait`
- Quality gates (in `backend/`): `uv run ruff check . ../scripts`, `uv run mypy`, `uv run lint-imports`, `uv run pytest -q`
- Phase 1 from zero: `./scripts/phase1_demo.sh`
- Runbook: `docs/runbooks/local-development.md`

## Engineering rules learned in Phase 1

- Security sweeps enumerate the OpenAPI document and assert exact coverage (ADR-032). Prove a new security suite fails against a sabotaged implementation before trusting it.
- Every new tenant-scoped route must be added to `SAMPLE_BODIES` in `tests/security/test_tenant_isolation.py`, or CI fails.
- Tenant-owned tables get FORCE RLS plus composite `(tenant_id, …)` foreign keys; cross-tenant lookups only through narrow SECURITY DEFINER resolvers.
- Migrations are raw SQL, never import app code; frozen seed data lives in the migration; code mirrors are checked by tests.
- Every table with a `tenant_id` column is under FORCE RLS; the RLS lint (`tests/security/test_rls_coverage.py`) fails CI otherwise. New RLS-bypassing reader uses must be added to the allow-list test.
- Never use `SELECT … FOR UPDATE` on a table where `arada_app` has no UPDATE grant. Serialise with an advisory lock, and put invariants that must survive races in the database (ADR-033).
- A session never gains privileges in place: rotate the token (ADR-035).
- Do not call a guarantee "tamper-proof" or claim a scan gate that CI does not enforce. Docs describe what the code and CI actually do.

## Engineering rules learned in Phase 2

- Customer tokens and staff tokens never share a table, a dependency or a principal type. Every new non-storefront route is covered automatically by the OpenAPI-driven customer-token sweep in `tests/security/test_telegram_auth.py`.
- The RLS lint scans every application schema (`APP_SCHEMAS` in `test_rls_coverage.py`); a new schema must be added there. `TENANT_TABLES` uses schema-qualified names.
- Give the runtime role column-level UPDATE grants that never include `tenant_id`, binding columns, tokens or expiry.
- Unauthenticated endpoints commit no database writes on failure. Failures go to logs, not the audit trail (register B4).
- Never put real Telegram tokens, raw `initData`, signatures or personal data in the repository. Tests generate throwaway keys and fake tokens (`tests/telegram_kit.py`).
