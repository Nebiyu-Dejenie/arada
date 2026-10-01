# 11 — Deployment, Provisioning and Environments

Status: **Proposed; machines are UNKNOWN (U2, blocking at the first staging or production deployment)** · Related: ADR-001, ADR-010, ADR-020, ADR-027

## 1. Principles

- **Separate four things** (directive §82):
  - **code** is an image, identical for every tenant
  - **tenant configuration** is database rows
  - **infrastructure configuration** is in git: compose, Traefik, Ansible, Terraform
  - **secrets** are in the private ops repo and a runtime secret store
- **Reproducible.** A new machine goes from bare OS to a running stack using only Ansible and committed files (directive §63).
- **Simplest thing that scales.** Docker Compose on a few VMs. There is no Kubernetes until one of the triggers in §9 is met.

## 2. Topology

The **actual topology depends on the machines the owner provides** (U2), which are unknown and are not guessed (Permanent Command §25, §52). The design fixes the **roles and boundaries**, so any machine count from one upward can host them:

```
EDGE role        cloudflared (one project tunnel) → traefik
APP role         api · worker · scheduler (leader lock) · web-customer / web-console / web-site
DATA role        postgres (+ pgbouncer) · redis · object store (S3 API) · pgbackrest → OFF-HOST repo (encrypted)
OBS role         otel-collector · prometheus · alertmanager · loki · grafana (tempo later)
```

| Machines available | Placement |
|---|---|
| 1 | All roles on one host. Acceptable for staging. For production it is acceptable only with off-host backups and a tested restore. |
| 2 | EDGE + APP on one, DATA + OBS on the other (the state tier is separated first) |
| 3–5 | Follows the Permanent Command §25 pattern: edge; api/workers/bots; PostgreSQL; Redis/search; monitoring/backup |

Rules that hold in every placement:

- Hosts talk over a **private network** (LAN VLAN or WireGuard overlay). Nothing is exposed publicly.
- One Docker network per concern (`edge`, `app`, `data`, `obs`), with **host-unique container names** (lesson `00` §6.2).

Later stages happen **only on measured need** (Phase 9):

- a Postgres streaming replica
- a second APP host with a second `cloudflared` replica
- dedicated worker hosts
- per-enterprise-tenant database hosts (placement, `02` §3)

## 3. Service catalogue (Master Directive §21): every service declares its requirements

The **values are TBD**. They come from measurement: the Phase 1 local profile, then Phase 5 load tests on the real machines. They are never estimated in advance (Permanent Command §25). Each compose service must declare `cpus` and `mem_limit` (and reservations) once measured. CI fails on a production service without them, from the first real deployment onwards.

| Service | CPU | RAM | Storage | Network | Health check | Restart | Depends on |
|---|---|---|---|---|---|---|---|
| cloudflared | TBD | TBD | — | outbound 443 to Cloudflare; `edge` | `/ready` on metrics port | always | traefik |
| traefik | TBD | TBD | — | `edge`, `app` | `/ping` | always | — |
| api | TBD per replica | TBD | — | `app`, `data` | `/healthz` (process), `/readyz` (DB + Redis) | always | pgbouncer, redis, migrate✓ |
| worker | TBD per replica | TBD | temp space for image processing: TBD | `app`, `data`, outbound (Telegram, providers) | heartbeat row + `/healthz` | always | pgbouncer, redis, object store |
| scheduler | TBD | TBD | — | `app`, `data` | leader heartbeat | always | pgbouncer, redis |
| migrate (job) | TBD | TBD | — | `data` | exit 0 | no | postgres |
| web-* (static) | TBD | TBD | — | `app` | `/` returns 200 | always | — |
| postgres | TBD | TBD (`shared_buffers` tuned to the measured RAM) | TBD (growth tracked by `14` §3 meters) | `data` | `pg_isready` | always | — |
| pgbouncer | TBD | TBD | — | `data` | `SHOW POOLS` | always | postgres |
| redis | TBD | TBD (`maxmemory` set; `allkeys-lru` for cache DB, `noeviction` for queue/lock DB) | AOF: TBD | `data` | `PING` | always | — |
| object store | TBD | TBD | TBD (grows with media) | `data` | product health endpoint | always | — |
| otel-collector | TBD | TBD | — | `obs`, `app` | health extension | always | — |
| prometheus | TBD | TBD | TBD (retention per `12`) | `obs` | `/-/ready` | always | — |
| loki | TBD | TBD | TBD (retention per `12`) | `obs` | `/ready` | always | — |
| grafana | TBD | TBD | TBD | `obs`, `edge` (Access only) | `/api/health` | always | prometheus, loki |

**How the values get filled:** the Phase 1 local profile (`docker stats` under the test suite and a synthetic load), then k6 load tests on the real machines at Phase 5. The results are recorded in this table and in an ADR.

## 4. Environments (directive §64)

| | dev | staging | production |
|---|---|---|---|
| Where | Developer machine (compose) | Separate host(s) from production (U2) | Production host(s) per §2 placement (U2) |
| Hostnames | `*.localhost` | `stg-*.ROOT_DOMAIN` behind Cloudflare Access | `ROOT_DOMAIN` hostnames (`05` §3) |
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

> **As built (2026-10-01):** CI (`.github/workflows/ci.yml`) runs:
> - ruff (lint, including its `S` security rules, and format);
> - mypy `--strict` and import-linter;
> - pytest on real PostgreSQL: unit, integration, API, isolation and security suites, including the RLS policy check;
> - pip-audit on runtime dependencies;
> - gitleaks over the full history;
> - a fresh-stack reproduction (`scripts/phase1_demo.sh`);
> - a Trivy **image** scan that fails only on **CRITICAL** findings with a fix available.
>
> Not in CI yet: Semgrep or Bandit SAST, the no-`ports:` check, IaC scanning, SBOM, e2e, and push by digest. Redis does not exist yet.

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
Payment: CONNECTED (chapa, split, last reconcile 100%)     Domain: ACTIVE (abc-phones.ROOT_DOMAIN)
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
