# ADR-023: Observability: tenant_id in logs and traces, not in Prometheus labels

| Field | Value |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-09-26 |

## Decision
OpenTelemetry feeds Prometheus, Loki and (later) Tempo. `tenant_id` is carried on every log, trace and event, but not as a label on high-volume metrics. Per-tenant health and metric rollups are stored in PostgreSQL.

## Context
Per-tenant observability (Master §84) with thousands of tenants would explode metric cardinality.

## Alternatives
A per-tenant label on every metric.

## Reason
Bounded Prometheus cost with full per-tenant drill-down.

## Consequences
A bounded top-N exporter for the busiest tenants and tenants with open incidents.

## History
| Date | Change |
|---|---|
| 2026-09-26 | Phase 1 implements the correlation foundation only: request_id, W3C trace context, tenant_id and user_id on every log line and audit event, plus structured JSON logs with redaction. Prometheus, Loki, Grafana and a trace backend are Deferred to the first real deployment (owner: do not overbuild monitoring before deployment). |
