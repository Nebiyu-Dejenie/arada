# ADR-029: Staff authentication: opaque server-side sessions, argon2id, TOTP

| Field | Value |
|---|---|
| **Status** | Proposed — implemented in Phase 1 |
| **Date** | 2026-09-26 |

## Decision
Staff authenticate with username + password (argon2id, hashed off the event loop) and, once enrolled, a TOTP second factor. Success issues an opaque 256-bit bearer token. Only its SHA-256 is stored, in `control.sessions`, with an absolute lifetime and a sliding idle timeout. Tokens are accepted only in the `Authorization` header. Privileged (platform and vertical) grants are usable only in MFA-verified sessions. People join tenants only through single-use, expiring, hashed invitation tokens.

## Context
The permanent command requires authentication separated from authorisation, admin MFA from day one, and no secrets at rest. There is no browser console yet, so no cookie or CSRF surface exists.

## Alternatives
JWT access and refresh tokens (revocation needs a denylist; offers nothing server-side sessions don't); passkeys first (heavier; no UI yet); admin-set passwords (administrators would know users' passwords).

## Reason
Immediate revocation (logout, disabled person), no token material in the database, and a simple threat model. Invitations avoid admins handling passwords and avoid username enumeration.

## Consequences
One indexed lookup per request (see ADR-030). When the console UI lands, the same sessions move to `__Host-` cookies with CSRF tokens (09_SECURITY.md §3). Passkeys, step-up re-authentication and device management are Planned. Per-IP rate limiting is Deferred to the edge (Cloudflare) and Redis; per-account lockout is implemented.

## History
| Date | Change |
|---|---|
| 2026-09-26 | Implemented in Phase 1. |
| 2026-10-01 | Corrective pass (ADR-035). Confirming TOTP rotates the session instead of upgrading the token in place, and the new token is capped at the old absolute expiry. TENANT_OWNER, TENANT_ADMIN and TENANT_FINANCE need an MFA-verified session. **Authentication rate limiting is REQUIRED BEFORE PUBLIC EXPOSURE** (register B4): lockout per account only; argon2id cost per attempt is a resource-exhaustion vector. |
