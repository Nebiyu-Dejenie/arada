# 00 — Phase 0 Discovery

Status: **Complete** · Date: 2026-09-26 · Scope: directive §92 and §101 items 1–7

This records what exists *before* any Commerce OS code is written, what is worth reusing, and what must not be carried forward. Everything here was observed directly, not assumed. Where something could only be inferred, it is marked **Likely**.

Machine-specific details (private addresses, tunnel UUIDs, credential paths) are deliberately left out of this document because this repository is public.

---

## 1. This repository

| Item | Observed |
|---|---|
| Local path | `arada/`. It was empty before this commit. |
| Remote | `github.com/Nebiyu-Dejenie/arada`. It was empty before this commit. **Visibility: PUBLIC.** |
| Consequence | No secrets, internal hostnames, IPs, tunnel IDs, or provider credentials may ever enter this repo. Infrastructure secrets belong in a separate **private** ops repository (see `09_SECURITY.md` §6). Consider making this repo private before Phase 1 code lands. |

## 2. Existing systems found on the workstation

| System | Stack | State | Relevance |
|---|---|---|---|
| **Arada Bingo / Zemen Game** (the "game" codebase) | Python 3.12, FastAPI, asyncpg, Alembic (47 migrations), aiogram 3, Redis, PostgreSQL 15, Traefik, cloudflared, Prometheus/Grafana/OTel, GitHub Actions CI + self-hosted CD | **Live in production** with real-money flows | **High.** It has production-proven patterns for Telegram auth, the ledger, payment adapters, RBAC, audit, backup and PITR, and tunnel ingress. These should be ported and generalised, not shared at runtime. |
| **AradaGebeya** | Spring Boot 3 (≈360 Java files), Next.js 14 (≈80 TSX files), React Native, Stripe Billing | Single-tenant marketplace prototype | **Low–medium.** It is a requirements reference only. It is not multi-tenant, and Stripe does not serve Ethiopian merchants. |
| `aradapay` | — | Empty directory | None |
| `arada-beet` | Markdown notes | Research notes for an unrelated product | None |
| `marketplace` | Flutter stub | Skeleton | None |
| `payment-system-devops`, `loyalty-system`, `loyality` | Node / .NET demos | Learning projects | None |

## 3. Domain and Cloudflare state

| Item | Observed |
|---|---|
| `arada.fun` | Registrar **Hostinger**; nameservers are a Cloudflare pair (`nick`/`arya`). It **currently serves the live Bingo product** on the apex, `www`, `admin`, `finance`, `payments` and `agent`. |
| `arada.click` | Nameservers are a *different* Cloudflare pair (`dane`/`teresa`). It currently serves the live Zemen Game on the apex, `www`, `admin`, `finance`, `payments`, `agent` and `sms`. The registrar was not determined. |
| Cloudflare accounts | **Likely two accounts.** The two zones use different nameserver pairs, and the tunnel documented for `arada.fun` does not appear in the account the local `cloudflared` CLI is logged into. |
| Tunnels on the locally authenticated account | Four exist. Two are active and belong to other products. One named `arada` exists with **no active connections**; it may have been created for this platform. |
| Ingress patterns in use | There are two different patterns. (a) A host-level `cloudflared` runs as a systemd service and forwards to a Traefik instance whose config lives **outside git**. (b) A containerised `cloudflared` has committed config and routes straight to Compose services. |

**Conflict with directive §14 (one root domain):** both candidate domains are occupied by live gaming products, and both already use hostnames the Commerce OS needs, such as `admin.` and `finance.`. Choosing the domain is **blocking question Q1** (see `20_DECISIONS.md`).

## 4. Hosting state (from the game codebase's own ops docs)

- Production runs on a **Proxmox VM on a private LAN with no public IP**. The only ingress path is Cloudflare Tunnel, which already satisfies directive §15.
- A **host outage occurred on 2026-09-23**. A migration to a new VPS was being planned, but its sizing had not been measured.
- A GitHub Actions self-hosted runner is referenced for CD. Whether it is registered and active was never confirmed.
- Tooling on the workstation: Docker, Ansible, Terraform, `gh`, `cloudflared`, Node 22, Python 3, Go.

## 5. Reusable components (port and generalise; do not import at runtime)

| Component | What is good about it | What must change for the Commerce OS |
|---|---|---|
| Telegram `initData` validator | It is correct: HMAC-SHA256 with `WebAppData`, constant-time comparison, `auth_date` freshness and future-date rejection, and it never logs the raw string. | It must use per-tenant bot tokens. **Add Ed25519 `signature` verification** against Telegram's public key, bind `bot_id` to the resolved tenant, and use a shorter max age (see `04`). |
| Double-entry ledger | Append-only. A **deferred constraint trigger** rejects any transaction whose entries do not sum to zero, and idempotency-key conflicts across operation kinds are detected. | Use `bigint` minor units instead of `NUMERIC`. Add `tenant_id` and generic account owners, check the zero-sum per currency, and remove Bingo-specific foreign keys (`round_id`). |
| `PaymentProvider` protocol + Chapa/SantimPay/ArifPay adapters | Provider-agnostic, verifies signatures, exposes `fetch_status` for reconciliation, and supports payouts. | Add a per-merchant credential scope, split/sub-account settlement, the `Money` type, and a provider-event inbox. |
| RBAC permission map | Explicit per-permission role sets with no god-mode bypass, and a documented least-privilege rationale. | Roles must be scoped (platform / vertical / tenant) and assignable at runtime (see `10`). |
| Admin auth | bcrypt, TOTP (pyotp), and an IP allowlist that correctly trusts `CF-Connecting-IP` behind the tunnel. | Add WebAuthn, step-up re-authentication, Cloudflare Access, and device/session management. |
| Ops tooling | `pg_dump` and basebackup scripts, PITR restore, a restore drill runbook, systemd timers, a reconciliation job, and incident runbooks. | Back up **off-box**, encrypt backups, and verify restores automatically. |
| Engineering discipline | mypy strict, integration tests against real Postgres/Redis, Playwright e2e, and `gitleaks` config. | Keep all of it, and add tenant-isolation suites. |
| Amharic bot locales | Existing i18n structure. | Make it per-tenant and override-able. |

## 6. Dangerous technical debt: do NOT carry forward

1. **Ingress config outside version control.** On one deployment the Traefik routers lived only on the host, and four of them silently disappeared. → Every ingress rule for the Commerce OS lives in git (`11_DEPLOYMENT.md`).
2. **Shared Docker networks between unrelated stacks.** An ambiguous DNS alias pointed services at *another application's database* for about 19.5 hours. → One isolated network per stack, host-unique container names, and no shared networks (`11`).
3. **Backups on the same disk as the database** (dumps and WAL archive). → Encrypted off-box backups with automated restore verification (`13`).
4. **Alert rules with no evaluator.** Prometheus was not deployed in production, so no alert could fire. → The observability stack is part of Phase 1, not an afterthought (`12`).
5. **Payment confirmation by parsing SMS on an Android phone.** This was a pragmatic workaround for Telebirr. → It is not acceptable as a primary rail for multi-merchant commerce. Merchant payments use provider APIs with signed callbacks (`07`).
6. **Identity hard-coded to a Telegram user id.** → Use a provider-agnostic identity layer (`02` §6).
7. **A single bot token in environment config.** → Per-merchant bots with encrypted, rotatable tokens (`04`).
8. **A single LAN host as the only production machine**, which has already had an outage. → Separate the data tier, run a replica, and document RTO/RPO (`13`).
9. **Template `.env` files that once held real values.** → Secret scanning in pre-commit and CI, blocking (`09`).

## 7. Implications for the architecture

- The platform must be a **separate codebase, database, tunnel and deployment** from the gaming products. It shares proven *patterns*, not runtime, data or credentials. This is proposed in ADR-021 and confirmed or rejected by Q9.
- Directive §15 (no public origin) is already achievable with the existing Cloudflare Tunnel practice.
- The Python/FastAPI stack has the strongest production evidence in this environment, so the backend stack recommendation (ADR-004) builds on it.
