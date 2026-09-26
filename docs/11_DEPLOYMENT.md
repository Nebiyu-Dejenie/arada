# 11 — Deployment, Provisioning and Environments

Status: **Proposed; host topology blocked on Q4 (which machines)** · Related: ADR-001, ADR-010, ADR-020

## 1. Principles

- **Separate four things** (directive §82):
  - **code** is an image, identical for every tenant
  - **tenant configuration** is database rows
  - **infrastructure configuration** is in git: compose, Traefik, Ansible, Terraform
  - **secrets** are in the private ops repo and a runtime secret store
- **Reproducible.** A new machine goes from bare OS to a running stack using only Ansible and committed files (directive §63).
- **Simplest thing that scales.** Docker Compose on a few VMs. There is no Kubernetes until one of the triggers in §9 is met.

## 2. Topology

### Stage 1 (launch): 2 VMs + off-site backup target

```
VM-APP  (edge + compute)                 VM-DATA  (state)
 ├─ cloudflared                           ├─ postgres (primary)
 ├─ traefik                               ├─ pgbouncer
 ├─ api ×2                                ├─ redis
 ├─ worker ×2                             ├─ object store (S3 API)
 ├─ scheduler ×1 (leader lock)            └─ pgbackrest → OFF-SITE repo (encrypted)
 ├─ web-customer / web-console / web-site
 └─ otel-collector, promtail/alloy        VM-OBS (may be co-located on VM-DATA at launch)
                                           ├─ prometheus, alertmanager
                                           ├─ loki, tempo
                                           └─ grafana
```

- VM-APP ↔ VM-DATA communicate over a **private network**: a LAN VLAN or a WireGuard overlay. Nothing is exposed publicly.
- One Docker network per concern (`edge`, `app`, `data`, `obs`), with **host-unique container names** (lesson from `00` §6.2).

### Stage 2 (growth): add resilience before scale

- A Postgres **streaming replica** on a third VM (hot standby, for read-only reporting and failover).
- A second VM-APP, with cloudflared running on both. Cloudflare load-balances between tunnel replicas.
- Dedicated worker VM(s) for image processing and AI jobs.

### Stage 3: enterprise isolation

A dedicated Postgres VM per enterprise tenant (placement, `02` §3) and optionally dedicated `api`/`worker` containers, which Traefik routes to by tenant host.

## 3. Service catalogue (directive §21): initial sizing, to be validated by load tests

| Service | CPU (req → limit) | RAM (req → limit) | Storage | Network | Health check | Restart | Depends on |
|---|---|---|---|---|---|---|---|
| cloudflared | 0.1 → 0.5 | 64 → 256 MB | — | outbound 443 to Cloudflare; `edge` | `/ready` on metrics port | always | traefik |
| traefik | 0.2 → 1 | 128 → 512 MB | — | `edge`, `app` | `/ping` | always | — |
| api (each) | 0.5 → 2 | 512 MB → 1.5 GB | — | `app`, `data` | `/healthz` (process), `/readyz` (DB + Redis) | always | pgbouncer, redis, migrate✓ |
| worker (each) | 0.5 → 2 | 512 MB → 2 GB | tmp 2 GB (image processing) | `app`, `data`, outbound (Telegram, providers) | heartbeat row + `/healthz` | always | pgbouncer, redis, object store |
| scheduler | 0.2 → 1 | 256 → 512 MB | — | `app`, `data` | leader heartbeat | always | pgbouncer, redis |
| migrate (job) | 0.5 | 512 MB | — | `data` | exit 0 | no | postgres |
| web-* (static) | 0.1 → 0.5 | 64 → 128 MB | — | `app` | `/` 200 | always | — |
| postgres | 2 → 4 | 4 → 8 GB (shared_buffers ≈25%) | **100 GB SSD** + growth; WAL on the same or a separate volume | `data` | `pg_isready` | always | — |
| pgbouncer | 0.2 → 0.5 | 64 → 128 MB | — | `data` | `SHOW POOLS` | always | postgres |
| redis | 0.2 → 1 | 512 MB → 1 GB (`maxmemory` + `allkeys-lru` for cache DB; `noeviction` for queue/lock DB) | AOF 5 GB | `data` | `PING` | always | — |
| object store | 0.5 → 1 | 512 MB → 1 GB | **200 GB+** (grows with media) | `data` | `/minio/health/ready` or equivalent | always | — |
| otel-collector | 0.2 → 0.5 | 256 → 512 MB | — | `obs`, `app` | `/` (health extension) | always | — |
| prometheus | 0.5 → 1 | 1 → 2 GB | 50 GB (30 d retention) | `obs` | `/-/ready` | always | — |
| loki | 0.5 → 1 | 512 MB → 1 GB | 50 GB (14–30 d) | `obs` | `/ready` | always | — |
| tempo | 0.2 → 0.5 | 512 MB → 1 GB | 20 GB (7 d) | `obs` | `/ready` | always | — |
| grafana | 0.2 → 0.5 | 256 → 512 MB | 1 GB | `obs`, `edge` (via Access only) | `/api/health` | always | prometheus, loki, tempo |

**Launch minimums:**

- VM-APP: 4 vCPU, 8 GB RAM, 60 GB SSD.
- VM-DATA (+ OBS co-located): 4–8 vCPU, 16 GB RAM, 500 GB SSD.
- An off-site backup repository of at least 2× the database size, plus media.

These are estimates. Phase 1 exit criteria include a load test that replaces them with measurements (`14` §3).

## 4. Environments (directive §64)

| | dev | staging | production |
|---|---|---|---|
| Where | Developer machine (compose) | Separate VM, or a separate compose project on a separate host from prod | VM-APP + VM-DATA |
| Hostnames | `*.localhost` | `stg-*.DOMAIN` behind Cloudflare Access | `DOMAIN` hostnames (`05` §3) |
| Tunnel | none | **Own tunnel** | Own tunnel |
| Database | Ephemeral, seeded | Own database; anonymised copy of prod refreshed monthly (PII scrubbed) | Production |
| Payments | Provider **sandbox** credentials only | Sandbox only | Live |
| Telegram | Test bots | Test bots, on Telegram's test environment where useful | Real bots |
| KEK and secrets | Dev-only values | Staging-only | Production-only |

**Hard guards against cross-environment use:**

- Every secret is tagged with its environment.
- At start-up, the app refuses to run if `ENVIRONMENT` and a secret's tag disagree.
- The payments module refuses live provider endpoints unless `ENVIRONMENT=production`.
- The production database rejects connections from non-production networks (`pg_hba`).

## 5. CI/CD pipeline

```
PR:        lint · typecheck (mypy --strict, tsc) · unit · integration (real PG/Redis) · isolation suite · finance suite
           · migrations up (empty + fixture) · RLS policy check · no-ports check · SAST · deps · secrets · IaC scan · build images
main:      same + e2e (Playwright vs compose stack) + Trivy image scan → push to GHCR by digest → SBOM
release:   tag CalVer YYYY.MM.N → deploy to staging (auto) → smoke tests → manual approval → production rollout
```

**Deploy is pull-based** from private infrastructure. A self-hosted runner, or an Ansible job on a deploy host, pulls the release by digest. Nothing on the internet can push into production, and no inbound ports are required.

**Rollout steps:**

1. Pull images by digest.
2. Run `migrate` (expand-only migrations for this release).
3. Start new `api`/`worker` containers alongside the old ones.
4. Readiness gates.
5. Traefik weight shift.
6. Drain the old containers.
7. Smoke tests.
8. Mark `releases.status = deployed`.

**Rollback:** redeploy the previous digest. The previous release is compatible with the current schema because of expand/contract (`06` §6). Data problems are fixed with roll-forward fixes or point-in-time recovery (`13`).

## 6. Business Factory: tenant provisioning saga (directive §3, §99)

"Create Business" in the Super Admin console starts a **provisioning run**. Each step is **idempotent**, recorded in `provisioning_steps`, retryable and resumable, and has a compensating action where one is meaningful.

| # | Step | Automated | Compensation |
|---|---|---|---|
| 1 | Validate input: vertical, blueprint version (`published`), owner, slug (`05` §4), plan | ✓ | — |
| 2 | Create `organization` (if new), `tenant` (`provisioning`), `merchant`, and `tenant_placement` (Starter) | ✓ | mark failed |
| 3 | Seed roles, owner `TENANT_OWNER` assignment, default staff invitations | ✓ | revoke |
| 4 | Apply blueprint: categories, default workflows, templates, commission defaults, feature flags | ✓ | remove seeds |
| 5 | Branding: logo upload (media pipeline), theme tokens | ✓ | — |
| 6 | Payment configuration: provider, settlement model, credentials submitted by the owner (encrypted), sandbox test transaction | ✓ (the owner submits credentials) | disable configuration |
| 7 | Delivery configuration (if enabled by the blueprint) | ✓ | — |
| 8 | Domain: create the `domains` row, `DnsProvider.ensure_record`, verify (`05` §5) | ✓ | delete record (guarded) |
| 9 | Bot: managed-bot flow through the Factory bot (`04` §2), webhook, commands, menu button; access restricted to testers | ✓ (the owner taps once) | unset webhook, unlink |
| 10 | Main Mini App in @BotFather | **Guided manual step**, then automated verification | — |
| 11 | Notifications: templates and channels | ✓ | — |
| 12 | Analytics and monitoring: tenant health row, dashboards (template-driven, no per-tenant Grafana config) | ✓ | — |
| 13 | **Validation suite:** storefront loads on the host, the manifest resolves, `initData` login works on the tester account, a sandbox payment succeeds and reconciles, bot webhook healthy, RLS probe (read as another tenant returns 0 rows) | ✓ | stays in `validating` |
| 14 | `ready`: owner preview | ✓ | — |
| 15 | **Activate** (explicit Super Admin or owner action): lift bot access restriction, enable live payments, set tenant `active`, emit `MerchantProvisioned` | ✓ | suspend |

Creating Merchant B from the same blueprint is **the same run with different inputs**. No code is copied, nothing is deployed and nothing is restarted.

## 7. Deployment engine view (directive §62)

The Super Admin tenant page shows computed, never self-reported, status:

```
Tenant: ABC Phones     Deployment: READY    Release: 2026.10.1 (ring 2)
Health: HEALTHY        Bot: CONNECTED       Mini App: HEALTHY (main app verified)
API: HEALTHY           Database: HEALTHY (placement: shared/starter)
Payment: CONNECTED (chapa, split, last reconcile 100%)     Domain: ACTIVE (abc-phones.DOMAIN)
```

## 8. Staged rollout (directive §86)

- **Feature flags** gate new behaviour per tenant. This is the default mechanism, because the code is shared.
- **Release rings** for risky releases:
  - ring 0: internal test tenants
  - ring 1: 10% of tenants (opt-in and low-risk cohorts)
  - ring 2: 25–50%
  - ring 3: 100%

  Traefik routes each ring's tenant hosts to the canary `api` pool, using a generated host-to-pool mapping file committed by the release job.
- **Automatic halt** if a ring's error rate or payment-failure rate exceeds the baseline by the configured factor.

## 9. When Kubernetes becomes justified (ADR-020)

Revisit when **two or more** of these are true for more than a month:

- more than 6 application VMs to manage
- the need for per-tenant dedicated compute is routine rather than exceptional
- autoscaling needs react faster than the Ansible/compose workflow
- a team of 3 or more operators is on call

Until then, Compose + Ansible is cheaper to run and easier to reason about.
