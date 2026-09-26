# 20 — Decisions and Question Register

This is the project's decision memory (Permanent Command §48). Each ADR lives in its own file in [`adr/`](adr/) with these fields: Decision, Context, Alternatives, Reason, Consequences, Date, Status. **An accepted ADR is never edited in place.** A change gets a new ADR that supersedes it.

**Status meanings:**

| Status | Meaning |
|---|---|
| Accepted | Mandated by the charter or approved by the owner |
| Proposed | Architect's recommendation, awaiting owner approval |
| Assumed | A documented assumption under §53; work proceeds unless the owner objects |
| Deferred | Intentionally decided later, at the phase named |
| Superseded | Replaced by a later ADR |

## 1. ADR index

| ADR | Title | Status |
|---|---|---|
| [001](adr/ADR-001-modular-monolith.md) | Modular monolith with process roles | **Accepted** |
| [002](adr/ADR-002-shared-postgres-rls.md) | Shared PostgreSQL, shared schema, RLS for the Starter tier | Proposed |
| [003](adr/ADR-003-data-planes.md) | Control / Commerce / Finance / Ops planes | Proposed |
| [004](adr/ADR-004-backend-stack.md) | Backend: Python + FastAPI | Assumed |
| [005](adr/ADR-005-frontend-runtime.md) | Frontend: one TypeScript runtime, two bundles | Assumed |
| [006](adr/ADR-006-blueprint-storage.md) | Blueprint storage: immutable versions, no per-blueprint DDL | Proposed |
| [007](adr/ADR-007-jsonlogic-rules.md) | Rules in JSONLogic | Proposed |
| [008](adr/ADR-008-hostname-convention.md) | Hostname naming convention | Deferred (domain phase) |
| [009](adr/ADR-009-dns-provisioning-mode.md) | DNS provisioning mode | Deferred (domain phase) |
| [010](adr/ADR-010-ingress-tunnel-traefik.md) | Ingress: Cloudflare Tunnel → Traefik, routing in git | Proposed |
| [011](adr/ADR-011-telegram-managed-bots.md) | Telegram managed bots + BYO fallback | Proposed (verify limits before Phase 2) |
| [012](adr/ADR-012-miniapp-authentication.md) | Mini App auth: HMAC + Ed25519 + bot binding | Proposed |
| [013](adr/ADR-013-money-minor-units.md) | Money as integer minor units | **Accepted** |
| [014](adr/ADR-014-double-entry-ledger.md) | Double-entry append-only ledger | **Accepted** |
| [015](adr/ADR-015-settlement-model.md) | Settlement defaults to merchant-direct | **Accepted** (default); final model at Phase 4 |
| [016](adr/ADR-016-transactional-outbox.md) | Transactional outbox, no broker | **Accepted** |
| [017](adr/ADR-017-secrets-envelope-encryption.md) | Envelope encryption; infrastructure secrets outside the repo | Proposed |
| [018](adr/ADR-018-postgres-search.md) | PostgreSQL search: FTS + trigram + filters | **Accepted** |
| [019](adr/ADR-019-object-storage.md) | Object storage behind the S3 API | Proposed (product pending) |
| [020](adr/ADR-020-compose-no-kubernetes.md) | Compose + Ansible, no Kubernetes yet | **Accepted** |
| [021](adr/ADR-021-separation-from-other-projects.md) | Separate from unrelated local projects | **Accepted** |
| [022](adr/ADR-022-uuidv7-identifiers.md) | UUIDv7 + per-tenant human references | Proposed |
| [023](adr/ADR-023-observability-cardinality.md) | Tenant id in logs and traces, not metric labels | Proposed |
| [024](adr/ADR-024-provider-agnostic-identity.md) | Provider-agnostic identity; customers per tenant | **Accepted** |
| [025](adr/ADR-025-scoped-rbac.md) | Scoped RBAC, step-up, maker–checker | Proposed |
| [026](adr/ADR-026-root-domain-tbd.md) | `ROOT_DOMAIN` is configuration and TBD | **Accepted** |
| [027](adr/ADR-027-phase-order.md) | Phase order per Permanent Command §55 | **Accepted** |
| [028](adr/ADR-028-reference-vertical-phones.md) | Reference vertical: Phones | Assumed |

## 2. Question register (Permanent Command §53)

### KNOWN

| # | Fact | Source |
|---|---|---|
| K1 | `ROOT_DOMAIN` is TBD. `arada.fun` and `arada.click` are unrelated and must not be used. | Owner, Permanent Command §26, §51 |
| K2 | ARADA is separate from all other local projects: no shared code, runtime, infrastructure, credentials or domain. | Owner (ADR-021) |
| K3 | The first deployment is self-hosted VMs with Docker Compose. Ingress is only through one project Cloudflare Tunnel. No Kubernetes, no premature brokers or search clusters. | Permanent Command §18, §19, §25, §26 |
| K4 | Repository: `github.com/Nebiyu-Dejenie/arada`, **public**. | Observed |
| K5 | Development workstation: Ubuntu 24.04 (WSL2), Docker 29 + Compose v2.29, Python 3.12, Node 22, Ansible, Terraform, `gh`, `cloudflared`. This is development only and says nothing about production capacity. | Observed |
| K6 | Telegram Bot API documents managed bots (`KeyboardButtonRequestManagedBot`, `getManagedBotToken`, `replaceManagedBotToken`, `setManagedBotAccessSettings`), which need management enabled in @BotFather and a user action to create each bot. Main Mini App and direct-link apps are configured in @BotFather. | Official Bot API docs, checked 2026-09-26 |
| K7 | Mini App `initData` validation: HMAC-SHA256 with the `WebAppData` key derivation, plus an Ed25519 `signature` verifiable with Telegram's published public keys. | Official Mini Apps docs, checked 2026-09-26 |

### ASSUMED (documented; work proceeds unless the owner objects)

| # | Assumption | Where | Revisit by |
|---|---|---|---|
| A1 | Backend: Python 3.12+, FastAPI, SQLAlchemy Core/asyncpg, Alembic, aiogram 3 | ADR-004 | **Before Phase 1 code** (an override later is expensive) |
| A2 | Frontend: React + TypeScript + Vite, two bundles | ADR-005 | Before Phase 2 UI work |
| A3 | Reference vertical is Phones | ADR-028 | Before Phase 5 |
| A4 | Settlement Model A (merchant-direct) until legal review | ADR-015 | Phase 4 |
| A5 | Currency ETB (minor-unit exponent 2); locales Amharic + English; time zone `Africa/Addis_Ababa`; Ethiopian calendar as a display option only | `06` | Phase 1 |
| A6 | Local development uses `*.localhost` hostnames. No public environment exists until the domain is supplied. | ADR-026 | Domain phase |

### UNKNOWN (not blocking yet; asked only when the named phase needs it)

| # | Unknown | Becomes blocking at |
|---|---|---|
| U1 | `ROOT_DOMAIN`, its Cloudflare account, and a zone-scoped API token | The first public deployment (staging), or Phase 6 domain provisioning, whichever comes first |
| U2 | Production and staging machines: CPU, RAM, disk, network, VM topology, OS | The first staging or production deployment |
| U3 | Off-host backup destination | The first deployment that holds real data |
| U4 | Payment providers with signed agreements; split or sub-account support; legal opinion on holding funds | Phase 4 |
| U5 | Merchant bot ownership: the merchant's own Telegram account (managed bot) or a platform account | Phase 2 |
| U6 | Managed-bot limits and API coverage (bots per manager, Main Mini App configuration by API). This is a **verification task**, not an owner question. | Phase 2 (verify against docs plus a test bot before building on it) |
| U7 | Object-storage product (licence and maintenance review) | Before first deployment |
| U8 | SMS/email providers; AI model provider and data terms; courier partners | Phases 3 / 8 / 8 |
| U9 | Whether this repository should stay public once code lands (recommended: private) | Before Phase 1 code is pushed |

### BLOCKING

| # | Item | Why |
|---|---|---|
| B1 | **Owner go-ahead to start Phase 1.** | Master Directive §101.19 requires architectural approval before implementation. Nothing else blocks Phase 1: it runs entirely on local Docker, with no domain, machines, payments or Telegram credentials. |
