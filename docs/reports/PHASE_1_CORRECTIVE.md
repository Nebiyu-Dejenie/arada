# Phase 1 corrective pass

Date: 2026-10-01 · Scope: only the owner's required fixes after the source-level audit of commit 6e265c1 ("PHASE 1 = APPROVED WITH FIXES") · Status: **implemented; awaiting owner review** · **Phase 2: BLOCKED** until the owner explicitly approves it.

Nothing outside the listed items was built: no Redis, outbox, Telegram, Mini App, frontend, payments, monitoring, backups, deployment, tunnels or DNS. Docker remains development and test only.

## 1. Understanding
The audit found:
1. SUPER_ADMIN revocation was broken.
2. Three tables with a `tenant_id` had no RLS.
3. There was no SQL-level test for `tenant_invitation_roles`.
4. There was no connection-pool isolation test.
5. Sessions were upgraded to MFA in place.
6. Privileged tenant roles had no MFA.
7. Several documents overclaimed.

It also left ADR-030 undecided and rate limiting unrecorded. The owner ordered a fix, test or record for each, without architectural change.

## 2. Current state (before this pass)
The evidence is in the audit.
- `rbac/service.py:revoke_role` used `SELECT … FOR UPDATE` without an UPDATE grant.
- `domains`, `feature_flag_overrides` and `tenant_blueprint_assignments` had no RLS.
- `identity/service.py:confirm_totp` called `sessions.mark_mfa_verified` on the existing token.
- Tenant grants ignored MFA.
- The docs claimed:
  - last-super-admin protection (ADR-025, `10_RBAC.md`);
  - "append-only even for owner and superuser" (PHASE_1.md);
  - a Trivy "critical or high" gate (CI gates CRITICAL only);
  - an RLS lint and Semgrep/Bandit, neither of which existed.

## 3. Impact
| Level | Change |
|---|---|
| Platform | Migration 0008 (SUPER_ADMIN trigger). Migration 0009 (RLS on three tables, host resolver). Session rotation. Configuration flag `require_mfa_for_privileged_tenant_roles` |
| Tenant | MFA required for TENANT_OWNER, TENANT_ADMIN and TENANT_FINANCE |
| API | `POST /v1/me/mfa/totp/confirm` now returns **200 with a new token** instead of 204. `GET /v1/platform/feature-flags` reads through the platform reader |
| Vertical, customer | No change |

## 4. Architectural decisions
- **ADR-033** (Proposed, implemented): the database guards the last SUPER_ADMIN. No new privilege was granted.
- **ADR-034** (Accepted, owner-directed): every table with a `tenant_id` is under FORCE RLS, enforced by an RLS lint test.
- **ADR-035** (Proposed, implemented): MFA for privileged tenant roles (implementing `09` §3), and session rotation on MFA.
- **ADR-030: Deferred** (owner). **B4: authentication rate limiting is REQUIRED BEFORE PUBLIC EXPOSURE.**

## 5. Risks introduced
- **API contract change on TOTP confirmation.** There are no external clients. Tests and the walkthrough are updated.
- **Owners, admins and finance must enrol TOTP before using a tenant.** The walkthrough shows the step-up.
- **The platform reader (BYPASSRLS) gained a second call site** (`flags.list_flags`). It is authorised first, and an allow-list test pins the call sites.
- **The schema owner is now subject to FORCE RLS on three more tables** (no policy), so migrations cannot read or write their rows.

## 6. Plan
The order followed:
1. Inspect.
2. Migrations.
3. Services.
4. Tests.
5. Sabotage checks.
6. Documentation.
7. Full verification.

## 7. Implementation (by owner item)
| # | Item | Where |
|---|---|---|
| 1 | SUPER_ADMIN revocation | `migrations/versions/0008_super_admin_guard.py`; `rbac/service.py:revoke_role`; the misleading test is renamed `test_platform_admin_revocation_is_immediate` |
| 2 | RLS on `domains`, `feature_flag_overrides`, `tenant_blueprint_assignments` | `migrations/versions/0009_control_plane_rls.py`; `tenancy/service.py:resolve_by_host` (resolver); `flags/service.py:list_flags` (reader) |
| 3 | SQL-level `tenant_invitation_roles` isolation | `tests/security/test_rls_coverage.py::test_tenant_invitation_roles_are_isolated_at_sql_level`, plus the per-table parametrised tests |
| 4 | Connection-pool isolation | `tests/security/test_connection_pool_isolation.py` (4 tests; runs in the CI `pytest` job) |
| 5 | MFA session rotation | `identity/sessions.py:rotate`; `identity/service.py:confirm_totp`; `api/routes/auth.py` |
| 6 | MFA policy for tenant roles | `rbac/catalogue.py:MFA_REQUIRED_TENANT_ROLES`; `rbac/service.py:load_tenant_grants`; `access/scopes.py:tenant_scope`; `kernel/config.py` |
| 7 | Documentation overclaims | `09` §3, §11 and new §12; `10`; `06`; `11`; `15`; `16`; `21`; ADR-002/004/025/029 history; PHASE_1.md (corrected inline) |
| 8 | ADR-030 | Status Deferred, with the evidence critique and revisit conditions |
| 9 | Rate limiting | Register B4; `09` §3; ADR-035; `21`; `CLAUDE.md` |

Also added:
- The RLS policy lint and a runtime-role attribute test.
- A platform-reader allow-list test.
- An audit test renamed to what it proves (`…_plain_dml_cannot_modify_audit`), plus a test demonstrating the known owner and superuser bypass.

## 8. Verification

### Sabotage checks (each new suite shown to fail against a broken implementation)
| Deliberate break | Result |
|---|---|
| Original `revoke_role` from 6e265c1 | 5 of 9 invariant tests fail (`permission denied for table platform_role_assignments`) |
| Trigger without its advisory lock | 3 fail (overlapping, racing and raw concurrent deletes) |
| No trigger at all | 6 fail |
| Migration 0009 not applied | 9 fail (the three tables' tests, the lint, the flag and domain rules) |
| Session-level (`is_local => false`) tenant context | 2 pool tests fail (checkout and transaction-local) |
| Session-level context plus no reset for context-free transactions (tiny pool only) | 2 pool tests fail (interleaved and checkout) |
| Session-level context applied globally | The shared fixture itself fails: logins refused with 403, because the audit insert policy rejects a stale tenant (fails closed) |
| `MFA_REQUIRED_TENANT_ROLES` empty | 3 fail |

### Results (local, 2026-10-01, on the tree that was committed)
| Check | Result |
|---|---|
| Tests | **214 passed, 0 failed** (164 before this pass). The full run took 142 s on the shared developer VM |
| Coverage | **89%** of lines and branches (2,827 statements, 560 branches), measured greenlet-aware |
| Per area | RLS 30 · pool and concurrency 4 · route isolation 16 · RBAC 35 · SUPER_ADMIN revocation 13 · MFA rotation 6 · blueprint 37 · audit 10 · security (all) 66 · migrations 3, all passing |
| Migrations | Single head `0009_control_plane_rls`. Linear chain 0001 → 0009. The zero → head → base → head round trip passes. No code/schema drift |
| Lint and types | ruff clean; format clean; mypy `--strict` clean (103 files); import-linter 2 of 2 contracts kept |
| Dependencies | pip-audit (runtime lockfile): no known vulnerabilities |
| Secrets | gitleaks over the working directory: the 4 findings are all in `.env`, the git-ignored local dev secrets file (generated, mode 600, never tracked). Full-history scan: see the owner's report |
| Container | Trivy 0.74.0 on the image (Debian 12.15). `--severity CRITICAL --ignore-unfixed` (the CI gate): 0 findings, exit 0. `--severity CRITICAL,HIGH --ignore-unfixed`: 0 findings, exit 0 |
| Fresh stack | `scripts/phase1_demo.sh`: a fresh compose project, migrated 0001 → 0009, bootstrapped, walkthrough **10/10** (including the owner and admin MFA step-up and the token rotation check), then torn down |

Honesty notes from the verification runs:
- **Two earlier full runs and one demo run failed while the machine was saturated** (load average 30–43 on 4 vCPUs, shared with other workloads).
  - Two of the failures were my new tests putting 500 and 120 simultaneous jobs on 2- and 10-connection pools, so waiters passed SQLAlchemy's 30 s checkout timeout. Both tests now bound in-flight work to 3× and 2× the pool. Re-running the tiny-pool sabotage confirmed the bounded test still fails against a stale context.
  - The other failures are the defect in §10.
- **Trivy's first two runs exited 1 because of scanner timeouts** while it downloaded its database, not because of findings. They were re-run with `--timeout 30m`.

## 9. Result
All nine owner items are addressed. The concrete defect (SUPER_ADMIN revocation) is fixed and guarded by the database. Every table with a `tenant_id` is under forced RLS, with a lint. Pool reuse is tested under interleaving and failure. Sessions rotate on MFA. Privileged tenant roles require MFA. The documents now match the code and CI.

## 10. Remaining
See `21_IMPLEMENTATION_STATUS.md` and register items B2 and B4. Found during verification, not fixed (it is outside the owner's list):
- **Password hashing inside an open transaction.** `identity/service.py:create_person_with_password` (used by invitation acceptance with a new account, and by the CLI bootstrap) runs argon2id while a database transaction is open. On a saturated machine the hash outlived `idle_in_transaction_session_timeout` (30 s), and PostgreSQL terminated the session: one test and one demo run failed with `connection is closed`, confirmed in the server log. Under normal load the hash takes well under a second. It is still a pool-holding DoS amplifier and should move before the transaction, together with rate limiting (B4).
