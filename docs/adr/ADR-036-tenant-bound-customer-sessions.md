# ADR-036: Customer sessions are opaque, server-side and bound to one tenant and customer

| Field | Value |
|---|---|
| **Status** | Proposed — approved in principle by the owner (decision D4, 2026-10-01), implemented in Phase 2; awaiting the owner's final review. Once accepted it supersedes the JWT and refresh-handle text in `04` §5, `17` and ADR-012's original Decision |
| **Date** | 2026-10-01 |

## Decision
A customer who logs in (in Phase 2, with Telegram Mini App `initData`) receives an **opaque bearer token** for a **server-side session row** in `control.customer_sessions`. Each row is bound to exactly one `tenant_id` and one `customer_id`.

- **Token.** 32 random bytes (`secrets.token_urlsafe`). Only its SHA-256 is stored. It is accepted only in the `Authorization` header, never in a query string.
- **Lifetime.** A sliding idle timeout (default 30 min) under an absolute lifetime (default 12 h): `customer_session_idle_timeout_minutes` and `customer_session_absolute_timeout_hours`. Rotation never extends the absolute lifetime.
- **Tenant binding by the database.** `customer_sessions` is under FORCE RLS. A token is looked up only inside the tenant that the request `Host` resolves to (`access/customer.py:customer_scope`), so tenant A's token is invisible at tenant B's host. `(tenant_id, customer_id)` is a composite foreign key to `commerce.customers`, and the runtime role cannot update `tenant_id`, `customer_id`, `token_hash` or `expires_at` (column-level grants).
- **Separate from staff sessions.** Staff tokens live in `control.sessions` and are checked by `api/auth.py:authenticated`. Customer tokens live in `control.customer_sessions` and are checked only by `access/customer.py`. The principal types differ (`Principal` and `CustomerPrincipal`), so neither token works on the other's routes.
- **No authorisation from authentication.** A `CustomerScope` carries identity, never permissions. Business functions decide what a customer may do, by proving that a resource is the caller's own (`customer_id`) inside the scope's tenant.
- **Revocation.** Logout revokes one session. Replacing or disabling the tenant's bot revokes all of that tenant's customer sessions. Disabling the person, or the tenant leaving `active`, makes every session fail immediately. Revocation is **one-way in the database**: a trigger (migration 0011) refuses any change to `revoked_at` or `revoked_reason` once a session is revoked, for every role. A faulty code path therefore cannot resurrect a session (ADR-033 principle).

## Context
`04` §5 and `17` proposed a 15-minute EdDSA JWT plus a 12-hour refresh handle. The owner approved opaque tenant-bound sessions in principle (D4) and directed that no JWT or refresh architecture be introduced merely because an older document proposed it.

## Alternatives
- **EdDSA JWT plus refresh handle.** Stateless reads, but it adds a signing key to manage and rotate, it cannot be revoked before expiry without a deny-list, and its tenant binding is a claim checked by code rather than a database guarantee.
- **Reusing `control.sessions` with a tenant column.** That table would then fall under the RLS lint and change the reviewed staff authentication path. Mixing staff and customer credentials in one table also invites confusion between the two.

## Reason
It reuses the reviewed ADR-029 and ADR-035 mechanics. Revocation is immediate. The tenant binding is enforced by PostgreSQL rather than by application code. There is no key to manage. It adds no infrastructure: one table and one RLS policy.

## Consequences
- Every customer request reads its session row, inside the transaction that serves it. This is the same cost as staff sessions (ADR-030's performance work stays deferred).
- There is no refresh token. When a session expires, the Mini App re-exchanges its current `initData`, within the replay window (`PHASE_2_PLAN.md` §9), or asks the user to reopen it from the bot.
- Tests: `tests/security/test_telegram_auth.py` (foreign hosts, staff and customer token separation, the OpenAPI-driven sweep) and `tests/api/test_storefront_auth.py` (expiry, idle timeout, disabled person, suspended tenant, revocation on bot replacement). The SQL-level tests are in `tests/security/test_rls_coverage.py`.
- Authentication rate limiting remains **required before public exposure** (register B4).

## History
| Date | Change |
|---|---|
| 2026-10-01 | Proposed and implemented in Phase 2 after owner decision D4. |
| 2026-10-02 | Revocation made one-way by a database trigger (migration 0011). Still Proposed, awaiting the owner's final review. |
