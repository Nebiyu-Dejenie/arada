# 20 — Architecture Decision Records and Open Questions

Status legend: **Proposed** (awaiting owner approval) · **Accepted** · **Blocked** (needs an answer to a question in §2) · **Superseded**

Every major decision is recorded here (directive §95). A change to an accepted decision gets a new ADR that supersedes the old one; ADRs are never edited in place after acceptance.

## 1. Decision records

| ADR | Decision | Reason | Alternatives rejected (for now) | Revisit when | Status |
|---|---|---|---|---|---|
| **001** | **Modular monolith**, one image, process roles `api`/`worker`/`scheduler`/`migrate` | Lowest operational cost; module boundaries enforced by import contracts; extraction stays possible | Microservices from day one: operational load without a measured need (directive §97) | A module needs independent scaling or isolation, measured | Proposed |
| **002** | **Shared PostgreSQL, shared schema, RLS** for the Starter tier | Cost per merchant; one migration path; RLS gives database-enforced isolation | Database per tenant by default: cost and operations at 1,000+ tenants. Schema per tenant: migration multiplication with no real isolation gain. | — | Proposed |
| **003** | **Control / Commerce / Finance / Ops planes**, no cross-plane joins; placement table for Pro/Enterprise | Makes isolation tiers a placement change; keeps money in one database | One undifferentiated schema: blocks enterprise placement later | — | Proposed |
| **004** | Backend: **Python 3.13+, FastAPI, Pydantic v2, SQLAlchemy 2 Core over asyncpg, Alembic, aiogram 3** | Strongest production evidence in this environment (ledger, Telegram auth, adapters, ops tooling already proven in the live game stack); async I/O suits webhook-heavy load | Spring Boot (AradaGebeya prototype: single-tenant, less proven here); Go/NestJS (no in-house evidence) | Profiling shows a CPU-bound hotspot (then extract that module in a faster runtime) | **Blocked on Q6** |
| **005** | Frontend: **one TypeScript runtime, two bundles** (customer, console), React + Vite + pnpm workspaces; SDK generated from OpenAPI | One codebase for every merchant (directive §9, §81); a small customer bundle for the Telegram WebView | Per-vertical or per-merchant apps (forbidden); Next.js SSR (unnecessary server runtime for a manifest-driven SPA) | SEO needs require SSR for storefronts: add pre-rendering for public listing pages | **Blocked on Q6** |
| **006** | Blueprints as **immutable versioned JSON documents**; core tables + `jsonb` attributes + a **typed attribute projection**; **no per-blueprint DDL** | Safe dynamic fields; indexed range filters; no runtime schema changes | Per-vertical tables (DDL at runtime, migration explosion); pure EAV (slow joins) | Filter performance degrades: OpenSearch via `SearchPort` | Proposed |
| **007** | Rules in **JSONLogic** (same evaluator semantics in Python and TypeScript) | Sandboxed, serialisable, diffable, portable | Embedded scripting (Lua/JS): an arbitrary-code risk. CEL: weaker JS ecosystem parity today | Rule needs outgrow JSONLogic | Proposed |
| **008** | Hostnames: **Option B**: `{slug}.DOMAIN` per merchant + shared `merchant.`, `admin.`, `finance.`, `ops.`, `api.` hosts | 1 DNS record per merchant; one admin attack surface; clean cookie isolation (`05` §2) | Option A (`admin-{slug}`, `finance-{slug}`): 3× records, thousands of admin hostnames | — | **Blocked on Q3** |
| **009** | DNS **explicit mode** (one proxied CNAME per merchant via API) + tunnel **wildcard ingress**; wildcard DNS as the scale fallback | Unknown hosts never reach the origin; auditable; no tunnel restarts per merchant | Manual records (forbidden); per-merchant tunnel routes | Record usage > 80% of the zone limit | Proposed |
| **010** | Ingress **Cloudflare → cloudflared (container) → Traefik v3** with **all routing in git**; default 404; no published ports | Directive §15, §19; fixes the "routers outside git" failure seen previously | Host-level cloudflared + untracked Traefik (proven fragile); cloudflared → services directly (no central middleware) | — | Proposed |
| **011** | Telegram: **Factory bot + managed bots** (Bot API 9.6) per merchant; BYO-token fallback; one multiplexed webhook endpoint | Automated per-merchant bots with API token rotation; no token pasting | Only BYO tokens (manual, merchant knows the token); one shared bot for all merchants (breaks merchant identity) | — | **Blocked on Q7** (ownership) |
| **012** | Mini App auth = **HMAC + Ed25519 `signature` + bot binding + freshness** → short-lived tenant-bound tokens | Blocks `initData` forgery by token holders; ties sessions to the merchant | HMAC only (forgeable by anyone with the token) | Telegram changes the scheme | Proposed |
| **013** | Money as **`bigint` minor units + ISO currency**; rates in **basis points**; largest-remainder allocation | Exactness; no floats (directive §27) | `NUMERIC` decimals (exact, but mixes scales and invites float conversion at edges) | Multi-currency with 3-decimal currencies: handled by the per-currency exponent table | Proposed |
| **014** | **Double-entry ledger** in the finance plane, append-only, zero-sum enforced by a deferred DB trigger, nightly rebuild compare | Financial integrity is priority #3; proven pattern | Balances on order rows (directive §96) | — | Proposed |
| **015** | Settlement **Model A (direct)** by default, **B (split)** once contracted, **C (platform collect)** only with written legal clearance | NBE legal framework must be confirmed before holding funds (directive §29) | Platform collect by default (regulatory risk) | Counsel's opinion + provider contracts (Q8) | **Blocked on Q8** |
| **016** | **Transactional outbox in Postgres** + inbox dedupe; no message broker initially | Atomicity with no extra infrastructure; at-least-once delivery + idempotent consumers | RabbitMQ/Kafka/NATS from day one (another stateful system to operate) | Dispatcher lag or outbox contention is measured | Proposed |
| **017** | Secrets: **envelope encryption (AES-256-GCM, AAD-bound)**, KEK outside the DB; infrastructure secrets in a **private ops repo** (SOPS/age or Ansible Vault) | This repository is public; ciphertext can't be moved across tenants | Plaintext env vars for per-merchant secrets (don't scale, leak easily); Vault on day one (operational load) | More than 1 operator or compliance needs: OpenBao/Vault transit behind the same interface | Proposed |
| **018** | Search: **Postgres full-text + attribute projection** behind `SearchPort` | Enough for launch; no extra cluster | OpenSearch on day one (memory-hungry, another cluster to operate) | Search p95 > 300 ms, or relevance or Amharic stemming needs | Proposed |
| **019** | Object storage via the **S3 API only**; server product chosen after a licence and maintenance review (MinIO community distribution changed in 2025; evaluate MinIO, Garage, SeaweedFS) | Keeps the backend swappable | Coupling code to one product | — | Proposed (product pending) |
| **020** | **Docker Compose + Ansible + Terraform (Cloudflare)**; no Kubernetes until the triggers in `11` §9 are met | Directive §20; the smallest operational surface | Kubernetes now | Triggers met | Proposed |
| **021** | The Commerce OS is **fully separate** from the gaming products: separate repo, database, tunnel, credentials and deployment. Patterns are ported, not shared at runtime. | Blast-radius isolation; different regulatory profiles; avoids repeating the shared-network incident | Extending the gaming codebase | — | **Blocked on Q9** |
| **022** | IDs: **UUIDv7** generated in the application; human `ref`s per tenant | Index locality; no DB-version dependency; non-enumerable | Serial ids (enumerable, leak volume); UUIDv4 (poor locality) | — | Proposed |
| **023** | Observability: OTel → Prometheus / Loki / Tempo / Grafana; **`tenant_id` in logs and traces, not as a Prometheus label**; tenant health in Postgres | Bounded metric cardinality at thousands of tenants | Per-tenant Prometheus labels | — | Proposed |
| **024** | Identity: global **person + provider identities**; **customer per tenant** | Telegram is the first provider, not the only one (directive §59) | Users keyed by Telegram id (current game stack) | — | Proposed |
| **025** | **Scoped RBAC** (platform/vertical/tenant) + policy checks + step-up + maker–checker + JIT support grants; single-operator mode until a second admin exists | Directive §32–35, §54; practical for a solo owner | Global roles (cannot express vertical or tenant scope) | — | Proposed |

## 2. Blocking questions for the owner

Only questions that change the architecture are listed. Everything discoverable was discovered (`00_DISCOVERY.md`). Each question notes what it blocks.

### A. Domain and edge (blocks Phases 3–4 and any public deployment; does **not** block Phase 1 code)

**Q1. Which single root domain does the Commerce OS use?**
Both `arada.fun` (registrar Hostinger) and `arada.click` currently run live **real-money gaming** products and already use `admin.`, `finance.`, `payments.` and `agent.`. Options:

- (a) `arada.fun` for the Commerce OS, and move the Bingo product elsewhere
- (b) `arada.click`, with the same trade-off
- (c) keep gaming and commerce on different domains; this is an exception to the one-domain rule and needs your explicit approval

Recommendation: do **not** co-host the commerce platform and gambling on one domain. Payment providers, Telegram policy and brand trust treat them differently. Please also confirm which Cloudflare account holds the chosen zone; the tunnel must be in the same account.

**Q2. Cloudflare API access:** will you create a **zone-scoped API token** (DNS edit for that zone; tunnel read) for the provisioning service when Phase 3 starts? It is stored encrypted and never committed.

**Q3. Approve hostname Option B** (`{slug}.DOMAIN` + shared `merchant.`/`admin.`/`finance.` consoles) over Option A (`admin-{slug}`, `finance-{slug}`). See `05` §2.

### B. Infrastructure (blocks Phase 1 staging and production)

**Q4. Which machines?** The existing Proxmox host (which had an outage on 2026-09-23), the planned new server, or new VMs? For each: vCPU, RAM, disk (SSD?), and whether it has a public IP. With a public IP, all inbound traffic is firewalled and only the tunnel is used. Minimum for launch: 2 VMs (`11` §3).

**Q5. Off-site backup destination:** a second physical site or NAS you control, or an encrypted S3-compatible bucket from a third-party provider? It must be in a different failure domain from the database host.

### C. Technology (blocks Phase 1 code)

**Q6. Approve the stack:** Python/FastAPI backend (ADR-004) + React/TypeScript/Vite frontend (ADR-005), porting proven patterns from the game stack, rather than Spring Boot/Next.js from the AradaGebeya prototype.

### D. Telegram (blocks Phase 4)

**Q7. Who owns each merchant's bot?**

- (a) The **merchant owner's** Telegram account, as a managed bot controlled by our Factory bot (recommended: the merchant truly owns their identity, and we can still rotate tokens and configure it).
- (b) A **platform-owned** Telegram account, so the merchant depends on the platform.

Also: create a new Factory bot for the platform (recommended), or reuse an existing one?

### E. Payments and legal (blocks Phases 7–8)

**Q8.**

- Which payment providers do you have **signed merchant or API agreements** with today (Telebirr merchant API, Chapa, SantimPay, ArifPay, CBE Birr, M-PESA)?
- Do any support **split settlement or sub-accounts**?
- Has counsel reviewed whether the platform may **collect and hold** merchant funds under the NBE framework?

Until answered, the design defaults to Model A (merchant-direct).

### F. Relationship to existing systems (blocks the repo and infrastructure setup in Phase 1)

**Q9. Confirm that the Commerce OS is a separate system from the gaming products** (ADR-021): its own database, tunnel, credentials and deployment, reusing *patterns* but not runtime. Also confirm whether this repository should stay **public**: it will contain architecture and code but never secrets, and making it private is recommended once code lands.

## 3. Non-blocking items (decided later, in the phase named)

- SMS and email providers (Phase 9)
- AI model provider(s) and data-processing terms (Phase 12)
- Object-storage product (Phase 1, ADR-019)
- Plan prices and limits (Phase 3)
- Status-page tooling (Phase 1)
- Courier partners (Phase 11)
