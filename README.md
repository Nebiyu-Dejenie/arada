# arada

**ARADA**: a multi-tenant commerce operating system and merchant factory for Ethiopia, with Telegram as the first channel.

One platform core runs many independent merchant businesses across many verticals (phones, cars, property, food, jobs, events, and more), all controlled from a single Super Admin console. Each merchant gets its own identity, storefront, Telegram bot, Mini App, staff portal, finance portal and payment configuration. All of this is **data and configuration on one shared, strictly tenant-isolated platform**, never copied code.

```
PLATFORM → VERTICAL → BLUEPRINT (versioned) → MERCHANT TENANT → BOT + MINI APP → CUSTOMER
                                   ORDER → PAYMENT → LEDGER → PAYOUT → DELIVERY → REVIEW → ANALYTICS → AI
```

## Status

| Phase | State |
|---|---|
| 0: Discovery and architecture | **Complete** |
| 1: Platform kernel | **Implemented and verified; awaiting owner review** |

What exists, and what deliberately does not yet: [`docs/21_IMPLEMENTATION_STATUS.md`](docs/21_IMPLEMENTATION_STATUS.md). How to run it: [`docs/runbooks/local-development.md`](docs/runbooks/local-development.md). Phase order: [`docs/15_ROADMAP.md`](docs/15_ROADMAP.md).

```bash
./scripts/init-env.sh && docker compose up -d --build --wait   # local stack
./scripts/phase1_demo.sh                                       # Phase 1 Definition of Done, from zero
```

## Start here

| | |
|---|---|
| [`docs/charter/`](docs/charter/) | The owner's governing directives, verbatim, with precedence rules. **The Permanent Command governs.** |
| [`CLAUDE.md`](CLAUDE.md) | Operating rules for engineering agents, condensed from the charter |
| [`docs/20_DECISIONS.md`](docs/20_DECISIONS.md) | ADR index and the KNOWN / ASSUMED / UNKNOWN / BLOCKING register |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records (ADR-001…032) |

## Architecture documents

| # | Document | Covers |
|---|---|---|
| 00 | [Discovery](docs/00_DISCOVERY.md) | Evidence-based findings, verified external facts, lessons |
| 01 | [Architecture](docs/01_ARCHITECTURE.md) | Four-level rule, product surfaces, modular monolith, control plane, modules |
| 02 | [Tenancy](docs/02_TENANCY.md) | Tenant model, lifecycle, isolation tiers, tenant resolution, RLS |
| 03 | [Blueprint Engine](docs/03_BLUEPRINT_ENGINE.md) | Blueprints, attributes, rules, workflows, core order lifecycle, versioning |
| 04 | [Telegram Architecture](docs/04_TELEGRAM_ARCHITECTURE.md) | Bots, webhooks, Mini App, `initData` authentication, deep links |
| 05 | [Domain and Tunnel](docs/05_DOMAIN_AND_TUNNEL.md) | `ROOT_DOMAIN` (TBD), hostname evaluation, DNS automation, Tunnel, Traefik |
| 06 | [Database Model](docs/06_DATABASE_MODEL.md) | Conventions, roles, schemas, tables, migrations |
| 07 | [Payment Architecture](docs/07_PAYMENT_ARCHITECTURE.md) | Provider adapters, intent state machine, idempotency, reconciliation |
| 08 | [Ledger](docs/08_LEDGER.md) | Double-entry ledger, commissions, payouts, finance portals |
| 09 | [Security](docs/09_SECURITY.md) | Authentication, sessions, secrets, media, AI, supply chain |
| 10 | [RBAC](docs/10_RBAC.md) | Scoped roles, permission catalogue, step-up, maker–checker |
| 11 | [Deployment](docs/11_DEPLOYMENT.md) | Role-based topology, service requirements, environments, CI/CD, provisioning |
| 12 | [Observability](docs/12_OBSERVABILITY.md) | Signals, tenant health, alerts, SLOs |
| 13 | [Disaster Recovery](docs/13_DISASTER_RECOVERY.md) | RPO/RTO, off-host backups, restore verification |
| 14 | [Cost Model](docs/14_COST_MODEL.md) | Cost per merchant, metering, plans, AI budgets |
| 15 | [Roadmap](docs/15_ROADMAP.md) | Phases 0–9 and the Phase 1 task list |
| 16 | [Threat Model](docs/16_THREAT_MODEL.md) | Threats with impact, likelihood, mitigation and verification |
| 17 | [API Contracts](docs/17_API_CONTRACTS.md) | Conventions, surfaces, initial endpoints |
| 18 | [Event Model](docs/18_EVENT_MODEL.md) | Envelope, outbox, event catalogue |
| 19 | [Acceptance Tests](docs/19_ACCEPTANCE_TESTS.md) | Success criteria; isolation, finance, edge and DR tests |
| 20 | [Decisions](docs/20_DECISIONS.md) | ADR index and question register |
| 21 | [Implementation Status](docs/21_IMPLEMENTATION_STATUS.md) | What is Implemented, Planned, Assumed or Deferred |

## Non-negotiables

- Tenant isolation is enforced by server-side resolution, scoped RBAC, PostgreSQL RLS, composite foreign keys and cross-tenant attack tests on every change.
- Money is stored as integer minor units, recorded in a double-entry append-only ledger, and every operation is idempotent. SMS alone is never proof of payment.
- `ROOT_DOMAIN` is configuration and currently TBD. The origin is reachable only through Cloudflare Tunnel.
- Blueprints are versioned and immutable once published. Merchants change version only through an explicit migration.
- **No secrets in this repository.** It is public, and secret scanning is a blocking CI gate.
