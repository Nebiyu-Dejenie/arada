# arada

**Arada Commerce OS**: a Telegram-first, multi-tenant, blueprint-driven commerce operating system.

One platform core runs many independent merchant businesses across many verticals (phones, cars, property, food, jobs, events, and more). Everything is controlled from a single Super Admin console. Each merchant gets its own storefront, Telegram bot, Mini App, staff console, finance portal and payment configuration, and all of them are **data and configuration on one shared platform**, never copied code.

```
PLATFORM → VERTICAL → BLUEPRINT (versioned) → TENANT/MERCHANT → BOT + MINI APP → CUSTOMER
                                   ORDER → PAYMENT → LEDGER → PAYOUT → DELIVERY → REVIEW → ANALYTICS → AI
```

## Status

**Phase 0 (architecture) is complete and awaiting owner approval.** No production code has been written yet, by design. Phase 1 (foundation) starts once the architecture is approved and the blocking questions in [`docs/20_DECISIONS.md`](docs/20_DECISIONS.md#2-blocking-questions-for-the-owner) are answered.

## Architecture documents

| # | Document | Covers |
|---|---|---|
| 00 | [Discovery](docs/00_DISCOVERY.md) | What already exists, reusable components, technical debt not to repeat |
| 01 | [Architecture](docs/01_ARCHITECTURE.md) | Style, control plane, modules, frontend runtime, repository layout |
| 02 | [Tenancy](docs/02_TENANCY.md) | Tenant model, lifecycle, isolation tiers, tenant resolution, RLS |
| 03 | [Blueprint Engine](docs/03_BLUEPRINT_ENGINE.md) | Blueprints, attributes, rules, workflows, versioning, migrations |
| 04 | [Telegram Architecture](docs/04_TELEGRAM_ARCHITECTURE.md) | Managed bots, webhooks, Mini App, initData authentication, deep links |
| 05 | [Domain and Tunnel](docs/05_DOMAIN_AND_TUNNEL.md) | One domain, hostname scheme, DNS automation, Cloudflare Tunnel, Traefik |
| 06 | [Database Model](docs/06_DATABASE_MODEL.md) | Conventions, roles, schemas, tables, ERD, migrations |
| 07 | [Payment Architecture](docs/07_PAYMENT_ARCHITECTURE.md) | Provider interface, intent state machine, idempotency, reconciliation |
| 08 | [Ledger](docs/08_LEDGER.md) | Double-entry ledger, chart of accounts, commissions, payouts, finance portals |
| 09 | [Security](docs/09_SECURITY.md) | Authentication, sessions, secrets, media, AI, supply chain |
| 10 | [RBAC](docs/10_RBAC.md) | Scoped roles, permissions, step-up, maker–checker |
| 11 | [Deployment](docs/11_DEPLOYMENT.md) | Topology, sizing, environments, CI/CD, Business Factory, staged rollout |
| 12 | [Observability](docs/12_OBSERVABILITY.md) | Signals, tenant health, alerts, SLOs |
| 13 | [Disaster Recovery](docs/13_DISASTER_RECOVERY.md) | RPO/RTO, backups, restore verification, scenarios |
| 14 | [Cost Model](docs/14_COST_MODEL.md) | Cost per merchant, metering, plans, AI budgets |
| 15 | [Roadmap](docs/15_ROADMAP.md) | Phases 0–15 with exit gates; Phase 1 task list |
| 16 | [Threat Model](docs/16_THREAT_MODEL.md) | STRIDE threats and mitigations |
| 17 | [API Contracts](docs/17_API_CONTRACTS.md) | Conventions, surfaces, initial endpoints |
| 18 | [Event Model](docs/18_EVENT_MODEL.md) | Envelope, outbox, event catalogue |
| 19 | [Acceptance Tests](docs/19_ACCEPTANCE_TESTS.md) | Success criteria, isolation, finance, edge, DR tests |
| 20 | [Decisions](docs/20_DECISIONS.md) | ADR-001…025 and the blocking questions |

## Non-negotiables

- Tenant isolation is enforced by server-side resolution, scoped RBAC, PostgreSQL RLS, composite foreign keys and automated cross-tenant attack tests.
- Money is stored as integer minor units, recorded in a double-entry append-only ledger, and every operation is idempotent.
- One root domain on Cloudflare. The origin is reachable only through Cloudflare Tunnel, with no public ports.
- Blueprints are versioned and immutable once published. Merchants never change version without an explicit migration.
- **No secrets in this repository.** It is public. Secret scanning is a blocking CI gate.
