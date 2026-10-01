# ADR-025: Scoped RBAC with step-up and maker–checker

| Field | Value |
|---|---|
| **Status** | Proposed — implemented in Phase 1 |
| **Date** | 2026-09-26 |

## Decision
Roles are assigned at a scope (platform, vertical or tenant) and contain granular `resource.action` permissions. Resource policies add ownership, assignment and limit checks. Sensitive actions require step-up re-authentication and, where configured, a second approver. Support access to tenant data uses just-in-time grants.

## Context
`admin=true` is forbidden; the role hierarchy spans platform, vertical and tenant.

## Alternatives
Global, unscoped roles.

## Reason
Expresses vertical and tenant boundaries precisely.

## Consequences
A single-operator mode applies until a second platform admin exists.

## History
| Date | Change |
|---|---|
| 2026-09-26 | Implemented: the charter's roles and permissions, scoped assignments, live grants per request, MFA-gated privileged scopes, no-self-escalation (a grant cannot exceed the grantor's own permissions), no self-modification, last-owner and last-super-admin protection. Not seeded yet: CUSTOMER (implicit, Phase 2), DELIVERY_AGENT and SERVICE_PROVIDER (need assignment-level policies, Phases 3/8), PLATFORM_OPS (not in the charter's list). Planned: step-up re-authentication, maker-checker, just-in-time support grants. |
| 2026-10-01 | **Correction.** The last-super-admin protection claimed on 2026-09-26 never worked: `revoke_role` used `SELECT … FOR UPDATE` without the UPDATE privilege, so revoking *any* SUPER_ADMIN failed with `permission denied`, and no test revoked a SUPER_ADMIN. Fixed by a database trigger (ADR-033), with tests including concurrency. Privileged tenant roles (owner, admin, finance) now need an MFA-verified session (ADR-035). |
