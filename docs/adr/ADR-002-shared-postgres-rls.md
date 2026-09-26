# ADR-002: Shared PostgreSQL, shared schema, Row-Level Security for the Starter tier

| Field | Value |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-09-26 |

## Decision
Starter-tier tenants share one database and schema. Every tenant table has `tenant_id`, `UNIQUE(tenant_id, id)`, composite same-tenant foreign keys, and forced RLS keyed on `SET LOCAL app.tenant_id`.

## Context
Tenant isolation is a critical security boundary; cost per merchant must stay low (Master §7, §61; Permanent §21).

## Alternatives
Database per tenant by default (cost and operations at 1,000+ tenants); schema per tenant (migration multiplication without real isolation gain).

## Reason
Database-enforced isolation that fails closed, at shared-infrastructure cost.

## Consequences
The app connects as a non-owner, `NOBYPASSRLS` role. Platform-wide reads use a separate read-only reader role restricted to allow-listed modules. CI verifies every tenant table has a policy.
