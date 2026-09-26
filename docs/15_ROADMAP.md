# 15 — Roadmap

Status: **Proposed** · Directive §91 · Each phase has an **exit gate** (acceptance tests in `19`). No phase starts until the previous gate passes and the decisions it depends on are made.

## Phase overview

| Phase | Name | Delivers | Depends on decisions | Exit gate (summary) |
|---|---|---|---|---|
| **0** | Architecture discovery | This document set | — | **Owner approval of the architecture + answers to Q1–Q9** ← *we are here* |
| **1** | Foundation | Repo skeleton, CI with all security gates, compose (dev/staging), Postgres + RLS framework, migrations, Redis, `RequestContext`, identity (staff), scoped RBAC, tenancy (manual tenant create), audit, outbox/inbox, observability stack, backups + restore verification | Q4 (hosts), Q5 (backup), Q6 (stack) | Isolation suite green; RLS policy check; restore drill passes; alert reaches Ops chat; origin scan clean on staging |
| **2** | Blueprint engine | Attribute library, blueprint versions (draft → publish), meta-schema, JSONLogic rules, compiler, runtime manifest, workflow runtime, **Phones v1.0** seed, version migrations (preview/apply/rollback) | — | Phones v1.0 → v1.1 compatible upgrade; v2.0 breaking migration with rollback; tenant pinned on v1.0 unaffected |
| **3** | Merchant provisioning | Business Factory saga, `edge` module + Cloudflare DNS provider, domain verification, plans/entitlements, tenant lifecycle, Super Admin console shell | **Q1 (domain), Q3 (hostnames)**, Cloudflare API token | Create Merchant A and B from one blueprint with **zero manual DNS**; each gets a verified host |
| **4** | Telegram bot + Mini App | Factory bot, managed-bot provisioning, webhook multiplexer, `initData` auth (HMAC + Ed25519), customer bundle shell, deep links | **Q7 (bot ownership)** | Tenant A's `initData` rejected on tenant B; managed bot created and rotated; Mini App loads branded per tenant |
| **5** | Catalog + search | Listings, variants, media pipeline, inventory, category trees, PG FTS + attribute filters behind `SearchPort`, storefront browse | — | Filters on blueprint attributes; media validation; search never crosses tenants |
| **6** | Orders | Cart, checkout (re-pricing), inventory reservation, order state machine via blueprint workflow, cancellations | — | Concurrent-checkout test; invalid transitions rejected |
| **7** | Payments | Intent state machine, provider adapters (first: per Q8), webhooks, poller, refunds, reconciliation v1 | **Q8 (providers + settlement model + legal)** | Full `07` §8 matrix green against provider sandboxes |
| **8** | Ledger + finance | Ledger with DB invariants, posting rules, commission engine, merchant/vertical/platform finance portals, payouts (if Model C), period close | Q8 | Trial balance 0; rebuild matches; commission snapshot immutable under rule change |
| **9** | Notifications | Templates, Telegram channel with rate limiting, SMS/email adapters, preferences | SMS provider choice | Order lifecycle notifications per tenant, localized |
| **10** | Reviews + promotions | Eligibility-gated reviews, coupons, discounts, flash sales, referral engine | — | Duplicate/ineligible review blocked; referral self-attribution blocked |
| **11** | Delivery + support | Zones, pricing, courier app (Mini App), proof of delivery, tickets, disputes | — | Proof-of-delivery required for `delivered`; dispute blocks payout |
| **12** | AI | Gateway, tool registry, budgets, shopping agent (structured intent, Amharic), merchant assistant, listing generator, Super Admin copilot | Model provider choice | Tool authz tests; no financial action without human confirmation; budget exhaustion degrades gracefully |
| **13** | Analytics + trust/risk | Event facts, KPI definitions from blueprints, dashboards, trust signals (documented methodology), risk signals + review queue | — | Tenant analytics isolated; risk produces signals, not silent penalties |
| **14** | Advertising | Placements, sponsored search, ad billing via ledger | — | Ads revenue account; sponsored results labelled |
| **15** | Additional verticals | Computers, Electronics, Fashion, Furniture, Cars, Spare Parts, Property (res/com), Services, Food, Beauty, Education, Construction, Agriculture, Jobs, Courses, Events: blueprint YAML + extensions each | — | Each vertical: create 2 merchants, run core flows, no core code change (only `extensions/` + `blueprints/`) |

Phases 9–14 can partly overlap once Phase 8 is complete. Phases 1–8 are strictly sequential, because each depends on the invariants of the previous one.

## Phase 1 — detailed task list (to start after approval)

1. **Repo & tooling**: backend package skeleton (`kernel/`, `control/`, …), frontend pnpm workspace, pre-commit (ruff, mypy, gitleaks, prettier, eslint), import-linter contracts for module boundaries.
2. **CI**: GitHub Actions per `11` §5 with all gates from `09` §11 blocking from day one; no-`ports:` check; RLS-policy check; vertical-literal grep check.
3. **Compose**: `dev` (all services), `staging` template, `prod` template; isolated networks; host-unique names; healthchecks; resource limits from `11` §3.
4. **Kernel**: `Money`, UUIDv7, `RequestContext`, error model (RFC 9457), idempotency middleware, `SET LOCAL` DB session, data-plane router (single plane initially), outbox writer + dispatcher + inbox, leader lock, structured logging with redaction, OTel.
5. **Schemas & roles**: `control`, `commerce`, `finance`, `ops` schemas; DB roles (`06` §2); RLS helper for migrations; CI policy check.
6. **Identity (staff)**: persons, identities, passkeys + password/TOTP, sessions (`__Host-` cookies), CSRF, step-up, device management, brute-force protection.
7. **RBAC**: catalogue, system roles, scoped assignments, `authorize`, JIT access grants, single-operator mode.
8. **Tenancy**: organizations, tenants, merchants, placement, lifecycle commands, host resolution (with the `domains` table, manual entries for now).
9. **Audit**: append-only, partitioned, with before/after diffs.
10. **Observability**: collector, Prometheus, Loki, Tempo, Grafana (Access-protected), Alertmanager → Ops Telegram chat; first dashboards and alerts from `12` §6.
11. **Backups**: pgBackRest to the Q5 destination, weekly automated restore verification, first manual drill.
12. **Infra as code**: Ansible roles (base hardening, Docker, firewall default-deny, WireGuard, cloudflared, deploy), Terraform for Cloudflare zone settings + Access apps (staging).
13. **Tests**: isolation suite framework (auto-enumerates endpoints), auth tests, migration tests, a first cross-tenant attack battery.
14. **Staging go-live** behind Cloudflare Access on `stg-*` hostnames; external origin scan.
