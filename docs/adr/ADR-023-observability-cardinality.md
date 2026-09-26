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
