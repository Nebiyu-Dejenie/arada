# ADR-002: Shared PostgreSQL, shared schema, Row-Level Security for the Starter tier

| Field | Value |
|---|---|
| **Status** | Proposed — implemented in Phase 1 |
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

## History
| Date | Change |
|---|---|
| 2026-09-26 | Implemented: FORCE RLS on merchant_profiles, tenant_memberships, tenant_membership_roles, tenant_invitations, tenant_invitation_roles and audit_events. The owner role has no policy, so it can neither read nor write those rows. Two narrow SECURITY DEFINER resolvers owned by the NOLOGIN role arada_resolver answer the only cross-tenant questions. Platform-wide reads use arada_platform_reader (BYPASSRLS, read-only). Composite (tenant_id, id) foreign keys hold even with RLS bypassed. Evidence: tests/security/test_tenant_isolation.py. |
| 2026-10-01 | Corrective pass (ADR-034): FORCE RLS extended to `domains`, `tenant_blueprint_assignments` and `feature_flag_overrides`, so every table with a `tenant_id` is now under RLS. Host resolution goes through the resolver `control.resolve_storefront_host`. The two Consequences claims are now true and tested: the RLS policy lint (`tests/security/test_rls_coverage.py`) and the reader allow-list (`tests/unit/test_kernel.py::test_platform_reader_is_used_only_by_allow_listed_functions`: `audit.list_platform`, `flags.list_flags`). Before this pass neither existed. Pool reuse is covered by `tests/security/test_connection_pool_isolation.py`. |
