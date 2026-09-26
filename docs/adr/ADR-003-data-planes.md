# ADR-003: Control / Commerce / Finance / Ops planes with no cross-plane joins

| Field | Value |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-09-26 |

## Decision
Separate schemas (`control`, `commerce`, `finance`, `ops`). Cross-plane data moves only through module interfaces or events. `tenant_placement` records where each tenant's commerce data lives.

## Context
Pro/Enterprise isolation tiers require moving a tenant's commerce data to a dedicated database without a rewrite (Master §7).

## Alternatives
One undifferentiated schema.

## Reason
Makes isolation tiers a placement change; keeps all money in one finance database for platform-wide reconciliation.

## Consequences
Some reporting needs read models fed by events instead of SQL joins.
