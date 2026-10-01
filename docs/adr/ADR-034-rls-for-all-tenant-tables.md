# ADR-034: Every table with a tenant_id is under forced RLS

| Field | Value |
|---|---|
| **Status** | Accepted — owner-directed (Phase 1 corrective pass: "add PostgreSQL RLS unless there is a demonstrated technical reason not to") |
| **Date** | 2026-10-01 |

## Decision
`domains`, `tenant_blueprint_assignments` and `feature_flag_overrides` are under ENABLE + FORCE row-level security (migration `0009_control_plane_rls`), like the six tenant tables of 0006 and `audit_events`.

A catalogue test, the **RLS policy lint**, now fails CI when any table in `control` has a `tenant_id` column but any of these is missing:
- FORCE RLS;
- a policy for `arada_app`;
- a runtime-role policy keyed on `control.current_tenant_id()`, with every write policy having a WITH CHECK.

The test is `tests/security/test_rls_coverage.py::test_every_table_with_a_tenant_id_is_under_forced_rls`.

| Table | SELECT | INSERT | UPDATE | DELETE | App grants |
|---|---|---|---|---|---|
| `tenant_blueprint_assignments` | `tenant_id = current_tenant_id()` | WITH CHECK same | same (no grant; the trigger rejects it) | same (no grant; the trigger rejects it) | SELECT, INSERT |
| `domains` | `tenant_id = current_tenant_id()` | WITH CHECK same | USING and WITH CHECK same | no grant | SELECT, INSERT, UPDATE |
| `feature_flag_overrides` | `tenant_id IS NULL OR tenant_id = current_tenant_id()` | WITH CHECK `tenant_id IS NOT DISTINCT FROM current_tenant_id()` | USING and WITH CHECK `IS NOT DISTINCT FROM` | USING `IS NOT DISTINCT FROM` | SELECT, INSERT, UPDATE, DELETE |

The access paths that must work without a tenant context are covered as follows:
- **Host header → tenant (storefront).** This goes through the new narrow resolver `control.resolve_storefront_host(text)`, which is SECURITY DEFINER, owned by the NOLOGIN role `arada_resolver`, has a pinned `search_path`, and does an exact hostname match only. `tenancy/service.py:resolve_by_host` uses it.
- **The platform-wide flag list** (`GET /v1/platform/feature-flags`, which is `flags.manage` and platform-only). It is authorised first, then read on the read-only `arada_platform_reader` pool, following the same pattern as the platform audit log.
- **Platform and vertical flag overrides** (`tenant_id IS NULL`). These are global configuration, readable in every context, but writable only outside any tenant context. Tenant-scoped code therefore cannot flip a platform kill switch.
- **Platform-kind domains** (`tenant_id IS NULL`). No feature uses them yet, and the runtime role cannot see or create them until one defines an access path.

## Context
Migrations 0006 and 0007 left the three tables without RLS as "control-plane metadata" read before a tenant context exists. The audit found this left no database backstop for a service bug. The owner directed RLS unless a technical reason prevents it. None does: each pre-context read is either a single exact lookup (host) or an authorised platform-wide read.

## Alternatives
- Keep them outside RLS with compensating service checks. This was rejected, because there is no technical reason to do so.
- A BYPASSRLS read for host resolution. Rejected: it is broader than an exact-match function.
- Moving flag overrides into per-scope tables. That is a larger schema change for no isolation gain.

## Reason
Isolation is enforced by the database for every tenant row, with the same fail-closed semantics everywhere: no context means no tenant rows.

## Consequences
- The reader pool has two call sites (`audit/service.py:list_platform`, `flags/service.py:list_flags`). The allow-list is enforced by `tests/unit/test_kernel.py::test_platform_reader_is_used_only_by_allow_listed_functions`.
- Future platform-domain features need an explicit policy or resolver.
- The schema owner is subject to FORCE RLS with no policy, so migrations cannot read or write these rows either. Data fixes go through a new, reviewed migration that adds what it needs.
- Tests are in `tests/security/test_rls_coverage.py`:
  - reads and writes per table for all nine tenant tables;
  - flag global-row rules;
  - the domain resolver;
  - `tenant_invitation_roles`;
  - role attributes.
- Sabotage check (migration 0009 made a no-op): 9 tests fail, exactly those three tables' tests, the lint and the table-specific rules.
