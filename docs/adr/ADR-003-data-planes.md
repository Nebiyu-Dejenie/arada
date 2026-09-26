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

## History
| Date | Change |
|---|---|
| 2026-09-26 | Phase 1 evidence: memberships, membership roles and invitations are authorisation data that must be resolvable across tenants ('my tenants'), so they live in the always-central `control` schema under RLS, not in the relocatable `commerce` plane. Merchant profile/branding is control-plane tenant metadata (Permanent Command §9), also under RLS. The `commerce`, `finance` and `ops` schemas are created when their first tables land (Phases 2-4); the placement table is deferred with them. |
