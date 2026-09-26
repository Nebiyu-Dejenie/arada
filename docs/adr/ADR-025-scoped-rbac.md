# ADR-025: Scoped RBAC with step-up and maker–checker

| Field | Value |
|---|---|
| **Status** | Proposed — the principles are mandated by Permanent Command §10, §40 |
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
