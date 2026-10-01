# ADR-035: MFA for privileged tenant roles; sessions rotate when they gain MFA

| Field | Value |
|---|---|
| **Status** | Proposed — implemented in the Phase 1 corrective pass (implements the existing `09_SECURITY.md` §3 requirement); awaiting owner review |
| **Date** | 2026-10-01 |

## Decision
**1. Tenant roles and MFA.** `09_SECURITY.md` §3 already required MFA for "merchant owner / admin / finance"; Phase 1 had not implemented it. Now:

| Role | MFA-verified session required | Why |
|---|---|---|
| TENANT_OWNER | **Yes** | Payment configuration, payout destination, staff roles, refunds, exports |
| TENANT_ADMIN | **Yes** | Staff and security management (`staff.manage`), refunds, captures, exports |
| TENANT_FINANCE | **Yes** | Finance data, refunds, exports, audit |
| TENANT_MANAGER | No | Catalogue, orders and delivery. No money movement, staff management or exports |
| TENANT_STAFF | No | Day-to-day fulfilment |

The set lives in `rbac/catalogue.py:MFA_REQUIRED_TENANT_ROLES`. Without an MFA-verified session:
- Permissions that come *only* from those roles are withheld (`rbac/service.py:load_tenant_grants` returns `(usable, withheld)`). Permissions also held through another role stay usable.
- A withheld permission answers `403 mfa-required-for-scope`, never 404, since the caller is a member.

`tests/unit/test_rbac_catalogue.py::test_sensitive_tenant_permissions_exist_only_in_mfa_required_roles` fails if a manager or staff role ever gains:
- a money permission: `payments.*`, `finance.*` or `orders.refund`;
- `staff.manage`;
- an export: `customers.export`;
- `audit.read` or `ai.configure`.

The switch is `require_mfa_for_privileged_tenant_roles` (default `true`; production refuses `false`). "A per-tenant policy can require MFA for staff" (09 §3) is still Planned.

**2. Session rotation.** A token is never upgraded in place. `POST /v1/me/mfa/totp/confirm`, the only transition from password-only to MFA-verified, now does four things (`identity/sessions.py:rotate`):
1. It revokes the calling session (`revoked_reason = 'rotated: mfa verified'`).
2. It issues a new MFA-verified session in the same transaction, capped at the old session's **absolute** expiry, so rotation never extends a lifetime.
3. It returns the new token: 200 with the same body as login. Before this pass it returned 204.
4. It audits both session ids in `mfa.totp_confirmed`.

The old token fails every request (401). A logout that lands first makes the rotation fail (401).

## Context
The source audit found two gaps:
- tenant owner, admin and finance roles worked without MFA, contrary to 09 §3;
- `confirm_totp` marked the existing session MFA-verified, so a token observed before MFA (log, shared device, fixation) became a privileged token. That contradicts the "rotated on privilege change" rule in 09 §3 and threat T4.

## Alternatives
- **MFA for every tenant role.** 09 §3 makes it optional for staff, and it would add friction to fulfilment staff for no money-, staff- or security-level gain.
- **Per-permission MFA flags instead of per-role.** More granular, but the role is what an owner assigns and understands. The catalogue test pins the sensitive permissions to MFA roles instead.
- **Rotating by rewriting the token hash on the same session row.** It keeps the session id, but it mutates a credential record in place and loses the forensic record of the pre-MFA session.

## Reason
It implements what the security design already required, and it closes session fixation on the one privilege-raising transition that exists.

## Consequences
- **API change:** `POST /v1/me/mfa/totp/confirm` returns 200 with `{access_token, token_type, expires_at, mfa_verified}`, and clients must switch to the new token. There are no clients yet besides the tests and the walkthrough script, both of which are updated.
- A newly invited owner, admin or finance member must enrol TOTP before using the tenant. The walkthrough shows the step-up.
- Tests:
  - `tests/api/test_tenant_mfa.py`;
  - `tests/api/test_identity.py::test_mfa_confirmation_rotates_the_session` and three related tests;
  - `tests/security/test_authentication.py::test_pre_mfa_token_never_gains_privileged_access`.
- Sabotage check (an empty `MFA_REQUIRED_TENANT_ROLES`): 3 tests fail.
- Step-up re-authentication for individual actions, passkeys, TOTP reset or recovery, and device management are still Planned (ADR-025, ADR-029).
- **Authentication rate limiting is REQUIRED BEFORE PUBLIC EXPOSURE** (register item B4). Every login attempt costs one argon2id verification (64 MiB, time cost 3), including attempts for unknown usernames, which verify against a dummy hash so their timing matches, which makes it a resource-exhaustion vector. Per-account lockout exists; per-IP and global limits do not.
