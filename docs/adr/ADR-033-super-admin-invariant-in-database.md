# ADR-033: The last SUPER_ADMIN is guarded by the database, not by a row lock

| Field | Value |
|---|---|
| **Status** | Proposed — implemented in the Phase 1 corrective pass; awaiting owner review |
| **Date** | 2026-10-01 |

## Decision
A trigger on `control.platform_role_assignments` (migration `0008_super_admin_guard`, function `control.keep_one_super_admin()`) refuses any DELETE or UPDATE that would leave the platform with no SUPER_ADMIN, for every role and code path.

The trigger works in three steps:
1. It takes a transaction-scoped advisory lock (`hashtextextended('control.super_admin_invariant', 0)`).
2. It then checks that a SUPER_ADMIN remains.
3. It refuses the change under REPEATABLE READ, where that check would read a snapshot taken before the lock.

`rbac/service.py:revoke_role` issues a plain DELETE and turns the trigger's `restrict_violation` into `409 Conflict`. The runtime role receives no new privilege.

## Context
The source audit of commit 6e265c1 found that revoking **any** SUPER_ADMIN failed. `revoke_role` serialised with `SELECT … FOR UPDATE`, which PostgreSQL only allows with an UPDATE privilege. Migration 0004 grants `arada_app` SELECT, INSERT and DELETE on the table, deliberately without UPDATE. As a result:
- A compromised SUPER_ADMIN could not be revoked through the API.
- The "last-super-admin protection" claimed in ADR-025 and `10_RBAC.md` had never run.

The only test in the area revoked a PLATFORM_ADMIN.

## Alternatives
1. **`GRANT UPDATE` on the table.** This lets the runtime role rewrite `role_key`, `granted_by` and `granted_at`, falsifying grant history silently, which INSERT and DELETE cannot do. It adds capability the application never needs. Rejected.
2. **Column-level `GRANT UPDATE (granted_at)` plus a trigger rejecting every UPDATE.** This makes `FOR UPDATE` legal while keeping updates impossible. But it is a privilege that exists only to satisfy a lock check, it is non-obvious, and it would still leave the invariant in application code only. Rejected.
3. **`LOCK TABLE … IN SHARE ROW EXCLUSIVE MODE` in the service**, which the existing DELETE privilege allows. It needs no new privilege, but it only protects code that remembers to take the lock. Not needed once the database guards the invariant.
4. **An advisory lock plus a count in the service only**, the same pattern as the last tenant owner (`tenancy/members.py`). It is cooperative, so a raw DELETE or future code path bypasses it.

## Reason
It is the narrowest option:
- **No new privilege.**
- **Atomicity.** The refusal aborts the whole transaction, so neither the deletion nor its audit event is committed. The successful path commits the deletion and `rbac.role_revoked` together.
- **Serialisation for every writer, not just cooperative ones.** A VOLATILE PL/pgSQL function under READ COMMITTED takes a fresh snapshot for each query, so the count after the lock sees every revocation committed before it.
- **Unchanged rules around it.** `roles.manage` is still required, and it exists only in SUPER_ADMIN and needs an MFA-verified session. Grants are still loaded per request.

This replaces row locking with a stronger, database-wide serialisation of SUPER_ADMIN removals. Grant loading (plain SELECT) is never blocked.

## Consequences
- Revocation is a plain DELETE. A second revocation waits for the first to commit, then is refused if it would remove the last one.
- A request whose grants were loaded before a revocation committed can finish that one request (READ COMMITTED); the next request of the revoked person has no platform grants.
- Holders of the schema-owner or superuser credentials can still disable the trigger. This is the same class of bypass as for the audit trail (`09_SECURITY.md` §12).
- Tests:
  - `tests/integration/test_super_admin_invariant.py` runs on its own fresh database. It covers revocation, the last-SUPER_ADMIN refusal, atomicity with the audit event, a deterministic overlapping pair, free-running races, raw concurrent deletes by the runtime role, REPEATABLE READ refusal, and other roles being unconstrained.
  - `tests/api/test_platform_rbac.py` covers immediacy, audit and authorisation.
- Sabotage checks run on 2026-10-01:
  - The trigger without its lock: 3 tests fail.
  - No trigger: 6 fail.
  - The original `FOR UPDATE` code: 5 fail with `permission denied for table platform_role_assignments`.
