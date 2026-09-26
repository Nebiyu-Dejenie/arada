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
- Phase 1 (foundation) waits for the owner's go-ahead.
- See `docs/15_ROADMAP.md`.
