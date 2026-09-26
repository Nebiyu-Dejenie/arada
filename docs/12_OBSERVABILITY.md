# 12 — Observability

Status: **Proposed** · Related: ADR-023 · Phase 1 (stack), then grows per phase

The observability stack ships in **Phase 1**. The previous platform had alert rules and no production evaluator (`00` §6.4), and that must not repeat.

## 1. Correlation fields (directive §52)

Every request, job and event carries:

| Field | Source |
|---|---|
| `request_id` | Generated at Traefik (a client value is replaced), echoed in the `X-Request-Id` response header, and shown in user-facing error pages so support can find it |
| `trace_id` / `span_id` | W3C `traceparent` (OpenTelemetry). Propagated into outbox events, so a webhook → worker → notification chain is one trace. |
| `tenant_id` | From `RequestContext`. Also on events and jobs. |
| `principal_id`, `principal_type` | When authenticated (never PII such as a phone number or name) |
| `cf_ray` | Cloudflare's ray id, to match edge logs |
| `release` | Image version (CalVer) |

## 2. Signals and where they go

```
app (OTel SDK: traces + metrics + structlog JSON logs)
  → otel-collector (batching, tail sampling, attribute redaction)
      → Tempo (traces, 7 d)       → Prometheus (metrics, 30 d)       → Loki (logs, 14–30 d)
                                         → Alertmanager → Ops Telegram chat (+ email fallback)
Grafana (ops.DOMAIN, Cloudflare Access) reads all three.
```

- **Tail sampling:** keep 100% of traces with errors, slow requests (> 1 s) and payment or ledger spans; keep 10% of everything else.
- **Logs:** structured JSON, redacted (`09` §10), with one line per request (access log) plus domain events at `info`.

## 3. Cardinality rule for thousands of tenants (ADR-023)

`tenant_id` is **not** a Prometheus label on high-volume metrics. With thousands of tenants it would multiply series without bound. Instead:

- **Prometheus** holds platform-wide and per-vertical, per-plan and per-provider metrics (bounded label sets).
- **Per-tenant views** (directive §84) come from logs and traces, which are filterable by `tenant_id` in Loki and Tempo, and from **`control.tenant_health`** plus hourly **tenant metric rollups** in Postgres, written by `scheduler` from those sources.
- Exception: a **bounded top-N** exporter publishes per-tenant series for the 50 highest-traffic tenants and any tenant with an open incident.

## 4. What is measured

| Area | Key metrics / SLIs |
|---|---|
| HTTP | Request rate, error rate (5xx), latency p50/p95/p99 by route template and surface (storefront/console/webhook) |
| Database | Connections, pool wait, slow queries (`pg_stat_statements`), replication lag, deadlocks, bloat, disk |
| Redis | Memory, evictions (must be 0 on the queue database), latency |
| Events and jobs | Outbox lag (oldest unpublished age), consumer lag per consumer, job failures, dead letters |
| Payments | Intents created, success rate per provider, callback latency, signature failures, poller recoveries, reconciliation match rate, unmatched value |
| Ledger | Posting rate, balance-rebuild mismatches (**must be 0**), suspense balance age |
| Telegram | Webhook updates/s, secret-token failures, `getWebhookInfo` errors, send 429s, per-bot queue depth |
| Mini App (client beacon) | Load time, JS errors, `initData` validation failures by reason |
| Ingress | cloudflared connection count and health, Traefik 404 rate on unknown hosts (probing indicator) |
| Workers | Heartbeat age, throughput, image-processing time, AI cost/min |
| Business | Orders/min, GMV (from ledger), active tenants, checkout funnel |

## 5. Tenant health (directive §85)

Computed every 5 minutes. **Never user-settable.**

| Subsystem | Healthy when |
|---|---|
| Domain | DNS record present, TLS valid, external probe of `https://{slug}.DOMAIN/healthz` returns 200 within 2 s |
| API | Tenant's 5xx rate < 1% and p95 < 1 s over 15 minutes (from rollups) |
| Bot | `getMe` succeeds, webhook URL matches, `last_error_date` older than 15 minutes, pending updates < 100 |
| Mini App | Main app verified; client error rate < 2% |
| Payments | Configuration valid; success rate within 2σ of the tenant's baseline; no failed reconciliation today |
| Workers | Tenant's queue partition lag < 60 s |

**Status rules:**

- `MAINTENANCE` if the flag is set (an explicit, audited action)
- otherwise `OFFLINE` if the domain or API is down
- otherwise `DEGRADED` if any subsystem is unhealthy
- otherwise `HEALTHY` if all checks are fresh (under 15 minutes old)
- otherwise `UNKNOWN`

Transitions emit `TenantHealthChanged` and notify the owner (Factory bot) and ops, rate-limited.

## 6. Alerts (initial, platform-level)

| Alert | Condition | Severity |
|---|---|---|
| API error budget burn | 5xx > 2% for 5 min (fast burn) or > 0.5% for 1 h | page |
| Payment success drop | Provider success rate < 70% of its 7-day baseline for 10 min | page |
| Ledger mismatch | Any balance-rebuild mismatch, or an unbalanced-transaction attempt | page |
| Outbox lag | Oldest unpublished event > 2 min | page |
| Webhook hijack suspicion | Bot webhook URL mismatch (`04` §3) | page |
| Tunnel down | cloudflared ready = 0 for 2 min | page |
| Backup failure | No successful backup or WAL push in 1 h, or restore verification failed | page |
| Disk | > 80% (warn), > 90% (page) | warn/page |
| Cert or domain | Domain verification failing for an active tenant | warn |
| Suspense | Suspense balance ≠ 0 for 48 h | warn |

Every alert links to a **runbook** (`docs/runbooks/<alert>.md`, written alongside the alert). The alert pipeline itself is tested end-to-end in Phase 1: a synthetic firing alert must arrive in the Ops chat.

## 7. SLOs (initial targets, reviewed after 90 days of data)

| SLO | Target |
|---|---|
| Storefront availability (successful page and API responses) | 99.5% monthly |
| Checkout API p95 latency | < 800 ms |
| Payment confirmation to order `paid` | 99% within 60 s of the provider's success |
| Telegram webhook processing | 99% acknowledged in < 1 s; processed in < 5 s |
