# 15 — Roadmap

Status: **Accepted phase order** (ADR-027, Permanent Command §55) · Each phase ends at an **exit gate**, made of acceptance tests in `19` plus the quality gates in Permanent Command §31. A phase starts only when the previous gate passes and the unknowns that block it are resolved (`20` §2).

## Phase overview

| Phase | Name | Builds | Blocked by (from `20` §2) | Exit gate (summary) |
|---|---|---|---|---|
| **0** | Discovery | Architecture package, charter, ADRs, question register | — | Owner go-ahead (**B1**): done |
| **1** | Foundation **(implemented; awaiting owner review)** | Project structure, typed configuration, database foundation (schemas, roles, RLS, migrations, outbox/inbox), identity, tenancy, RBAC, audit, feature flags, **blueprint foundation**, merchant model; plus the enabling baseline: CI gates, local compose, observability, backup tooling | B1 (and A1 confirmed or not overridden) | ISO suite green; RLS policy lint; migration tests; blueprint publish/pin/immutability tests; an alert reaches the Ops channel locally; backup + restore verification on local compose |
| **2** | Telegram foundation | Bot integration (BYO token first; managed bots after U6 is verified), webhook multiplexer, Mini App `initData` authentication (HMAC + Ed25519), host-based tenant routing, deep links, notification foundation (Telegram channel, templates, rate limits) | U5, U6 | AUTH-1…5, ISO-4, ISO-8; webhook dedupe; per-bot rate limiting; Mini App shell renders a per-tenant manifest |
| **3** | Commerce core | Catalog and listings (blueprint attributes, media pipeline), search (FTS + trigram + filters), customers, cart, checkout (server re-pricing, reservation), orders (core lifecycle + blueprint workflow), reviews (eligibility-gated), notifications for the order lifecycle | U7 (media storage), U8 (SMS/email, if used) | FIN-10 concurrent checkout; BP-3/4/5; ISO-9; review eligibility tests |
| **4** | Payment + finance | Payment abstraction, provider adapters, payment intents, webhooks, poller, double-entry ledger, posting rules, commissions, refunds, reconciliation, payout architecture | **U4** | Full FIN-1…17 against provider sandboxes; trial balance 0; rebuild equals cache |
| **5** | Reference vertical (Phones, A3) | Production-grade Phones blueprint with IMEI extension; Mini App, merchant portal, finance portal and analytics end to end; first real tenant(s) created through the provisioning service (CLI or admin endpoint) | U1, U2, U3 (first real deployment) | SC-1 criteria met *without* the factory UI; production smoke tests; DR-1 passes on real infrastructure |
| **6** | Merchant Factory | Automated Create-Business saga, blueprint cloning and migrations (preview/apply/rollback), branding, Telegram (managed bots), Mini App verification, payment configuration, features, **domain provisioning (ADR-008/009 decided here)**, activation | U1 (Cloudflare token) | SC-1, SC-2, SC-3, SC-4 fully automated; EDGE-5…7 |
| **7** | Vertical expansion | The remaining 17 verticals as blueprints + extensions + workflows, prioritised by the business | — | SC-5 for each vertical: no core changes outside `blueprints/` and `extensions/` |
| **8** | Advanced platform | Delivery engine, trust, fraud/risk signals, AI gateway (shopping agent, merchant assistant, listing generator, copilot, Amharic intent), advertising, loyalty/promotions/referrals, advanced analytics, recommendations | U8 | AI-1…4; referral and fraud tests; delivery proof-of-delivery tests |
| **9** | Scale | Only on metrics: dedicated search, event streaming, database replicas, service extraction, HA, Kubernetes | Measured triggers | Documented measurements that justify each step, recorded as ADRs |

Phases 1–4 are strictly sequential, because each depends on the previous phase's invariants. Phases 7 and 8 may overlap once Phase 6 passes.

## Phase 1: as built (2026-09-26)

Implemented and verified: see `21_IMPLEMENTATION_STATUS.md`. Against the original task list below, these items were **deferred on the owner's Phase 1 instructions** ("do not overbuild monitoring before deployment", "platform kernel only"):

- Observability stack (Prometheus, Loki, Grafana): Deferred to the first deployment. The correlation and structured-logging foundation is implemented.
- Backup tooling (pgBackRest, off-host): Deferred to the first deployment (needs U2 and U3).
- Outbox and inbox: Planned for Phase 2, with its first consumer.
- Frontend workspace skeleton: Planned for Phase 2.
- Staff passkeys and step-up re-authentication: Planned (TOTP MFA is implemented).

## Phase 1: original task list (for traceability)

Every item meets the Definition of Done at foundation level: tests, typing, lint, migration check, security scan, tenant-isolation check, observability hooks and documentation.

1. **Project structure.** Backend package (`kernel/`, `control/`, `commerce/`, `finance/`, `engagement/`, `intelligence/`, `extensions/`, `entrypoints/`); frontend pnpm workspace skeleton; import-linter contracts for module boundaries.
2. **Configuration.** Typed settings (pydantic-settings) with `ROOT_DOMAIN` and all hostnames as configuration; environment tagging (`dev`/`staging`/`production`) enforced at start-up; a secret-provider interface (no secrets in env files committed).
3. **CI.** Lint, type check, unit and integration tests on real Postgres/Redis, migration tests, gitleaks, pip-audit, Semgrep/Bandit, Trivy (filesystem), a no-`ports:` check, an RLS-policy lint and a vertical-literal lint. All blocking.
4. **Local compose.** Postgres, Redis, api, worker, scheduler and the observability stack. Isolated networks, host-unique names, health checks. Resource requests stay **TBD** until measured (`11` §3).
5. **Database foundation.** Schemas `control`/`commerce`/`finance`/`ops`; database roles; RLS helpers; the `SET LOCAL` session; the data-plane router (single plane); outbox dispatcher + inbox; idempotency-key store; leader lock.
6. **Kernel.** `Money`, UUIDv7, `RequestContext`, RFC 9457 errors, request-id and trace propagation, log redaction.
7. **Identity.** Persons, identities, staff authentication (passkey + password/TOTP), sessions, CSRF, step-up, brute-force protection.
8. **Tenancy + merchant model.** Organizations, tenants, merchants, placement, lifecycle commands, host resolution against the `domains` table (local `*.localhost` hosts only).
9. **RBAC.** Permission catalogue (charter names: `products.*`, `orders.*`, `payments.*`, `finance.*`, `users.*`, `staff.*`, `blueprints.*`, `tenants.*`), scoped roles, `authorize`, JIT grants, single-operator mode.
10. **Audit.** Append-only, partitioned, with actor, tenant, action, resource, request_id, trace_id, before/after, reason and source.
11. **Feature flags.** Platform → vertical → tenant layering, with evaluation cached by config version.
12. **Blueprint foundation.** Attribute library, blueprints, versions (draft → publish, immutable), meta-schema validation, JSONLogic evaluator (server), compiler, tenant pinning, and a *test* blueprint. The production Phones blueprint comes in Phase 5; version migrations in Phase 6.
13. **Observability baseline.** OTel SDK, collector, Prometheus, Loki, Grafana and Alertmanager on local compose, with first dashboards and a test alert.
14. **Backup tooling.** pgBackRest configuration and restore-verification job against a local repository. The off-host destination is plugged in at U3.
15. **Isolation test framework.** Auto-enumerates tenant-scoped endpoints and runs cross-tenant attacks. It gates every PR from day one.
