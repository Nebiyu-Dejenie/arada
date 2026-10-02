# Phase 2 — Telegram foundation: implementation report

| Field | Value |
|---|---|
| **Status** | **Implemented, independently audited and hardened (2026-10-02); awaiting owner review.** Phase 2 is **not complete** until two owner actions are done: the live test-environment sample (A8) and the pre-completion docs re-check (§9). **Not production-ready and not safe for public exposure:** B4 (authentication rate limiting) and the other production gates are open |
| **Date** | 2026-10-01; audit and hardening 2026-10-02 |
| **Baseline** | `89bdfd6` (verified Telegram specification; B5 resolved) on top of Phase 1 approved at `4896f60` |
| **Plan** | `PHASE_2_PLAN.md` (approved), owner decisions D1–D6 |

## 0. Independent audit and hardening (2026-10-02)

The owner authorised implementation on 2026-10-02. A first implementation already existed on branch `claude/laughing-knuth-aqzv3i` (commits `75743a5` and `c1f4427`, built directly on `89bdfd6`). It was treated as an **unreviewed draft**, not as evidence. The audit:

1. **Baseline.** `89bdfd6` is an ancestor of the work, so the approved documentation is incorporated unchanged.
2. **Line-by-line review against the verified specification** (`PHASE_2_PLAN.md` §5):
   - HMAC key `HMAC_SHA256("WebAppData", token)`;
   - the HMAC string excludes only `hash`, so it includes `signature` and unknown fields;
   - the Ed25519 string is `<bot_id>:WebAppData\n` followed by every field except `hash` and `signature`;
   - base64url with optional padding, and exactly 64 bytes;
   - `hash` is compared as 32 bytes in constant time;
   - crypto is checked before freshness;
   - the two key fingerprints were recomputed from the documented hex keys and match.
3. **Every gate re-run**, then **13 sabotage proofs run independently** (table below).
4. **Defects found and fixed, test-first.** Each new test was observed failing before the fix:

| Finding | Severity | Fix | Test (failed first, then passed) |
|---|---|---|---|
| A Telegram-signed `auth_date` beyond year 9999 raised an unhandled `ValueError`, so the client got a 500, not the generic 401 | Low: only reachable with Telegram-signed data | It is `malformed` | `test_stale_future_and_non_integer_auth_date` (2 new cases) |
| Replay rows are pruned by the database clock, but freshness uses the application clock. With clock drift, a row could be pruned while its `initData` was still fresh, reopening a reuse window | Low | `expires_at = auth_date + max_age + future_skew + 5 min` | `test_replay_rows_outlive_the_freshness_window` |
| The runtime role's column grants allowed un-revoking a customer session, reactivating a disabled bot or resetting a replay counter. Only service code prevented it | Defence in depth (ADR-033) | Migration **0011**: forward-only triggers that bind every role | `test_revocation_disabling_and_replay_counts_only_move_forward` |
| Staging accepted any Ed25519 key, so it could run with a non-Telegram key | Configuration safety | Only `development` and `test` may use a throwaway key; staging and production need a key Telegram publishes, matching `telegram_environment` | `test_staging_accepts_only_telegrams_published_keys` |
| A Phase 1 test read only the first audit page (50 events), so more tenant-A events from storefront tests made it fail depending on order | Test fragility; the product behaved correctly | The test reads every page; the assertion is unchanged | `test_tenant_a_admin_manages_tenant_a` |

**Independent sabotage proofs (2026-10-02).** Each break was applied by a script, then the Telegram, storefront, RLS and tenant-isolation suites were run and the code restored. `git status` was clean after each run.

| Break | Failing tests |
|---|---|
| `signature` excluded from the HMAC string | 76 |
| Ed25519 verification skipped | 6 (forged, wrong bot id, other environment, unsigned, …) |
| `bot_id` left out of the signed message | 73 |
| Login Widget derivation `SHA256(token)` | 76 |
| freshness skipped | 2 |
| only lower-case `hash` accepted | 1 |
| unknown fields dropped from the strings | 1 |
| replay window disabled | 3 |
| failure reason returned to the client | 5 |
| raw `initData` logged | 1 |
| customer-session RLS opened and the tenant check removed | 50, including `test_customer_routes_refuse_missing_bad_and_foreign_tokens` (#15) |
| `initDataUnsafe` planted in server code | 1 |
| part of the bot token logged at registration | 1 |

Each claim below names its evidence. "Test" means an automated test that runs in CI (`uv run pytest`). The important tests were also shown to fail against deliberately broken implementations (§8).

## 1. Authentication flow (as built)

```
POST /v1/storefront/auth/telegram   Host: <merchant host>   {"init_data": "<raw Telegram.WebApp.initData>"}
 1. tenancy.resolve_by_host(Host)            → tenant (active only) or 404          [server-side; no client tenant]
 2. set RLS context = tenant
 3. bots.active_bot_for_login                → that tenant's bot id + token (decrypted in memory)
 4. telegram.miniapp.verify(raw, bot_id, token, configured Telegram key)
      strict parse → HMAC(WebAppData, token) → Ed25519("<bot_id>:WebAppData\n…") → auth_date freshness
 5. bots.record_init_data_use                → replay window (reuse window + use cap)
 6. identity.telegram.find_or_create_person  → identities('telegram', user.id) → person
 7. customers.find_or_create                 → commerce.customers(tenant, person)
 8. customers.sessions.issue                 → opaque token, row bound to (tenant_id, customer_id)
 9. audit: identity.person_created (first time), customer.created (first time), auth.customer_login
Any failure in 3–6 → log telegram.auth_failed reason=<code> → one generic 401 telegram-auth-failed
```

The layers are separated by import-linter contracts (`backend/pyproject.toml`; `lint-imports`: 5 kept, 0 broken):
- `arada.telegram` imports no application module, not even `arada.kernel`.
- Only the customer login uses `arada.telegram`; `kernel`, `identity`, `tenancy`, `rbac`, `audit`, `flags`, `blueprints`, `verticals`, `bots`, `access` and the customer service and sessions modules never do.
- `identity`, `tenancy`, `rbac` and `audit` never import `customers`, `bots` or `access`.

## 2. Files changed

**New:**
- `backend/migrations/versions/0010_telegram_customers.py`
- `backend/migrations/versions/0011_customer_auth_guards.py` (2026-10-02)
- `backend/src/arada/telegram/{__init__,miniapp}.py`: the pure Mini App validator
- `backend/src/arada/bots/{__init__,tables,service}.py`: bot binding and the replay window
- `backend/src/arada/customers/{__init__,tables,service,sessions,telegram_login}.py`
- `backend/src/arada/identity/telegram.py`: Telegram identity mapping
- `backend/src/arada/access/customer.py`: customer scope (host → tenant → session)
- `backend/src/arada/api/routes/storefront.py`
- `scripts/telegram_sample_check.py`: the owner-run live-sample checker; prints verdicts only
- Tests:
  - `backend/tests/unit/test_telegram_miniapp.py`
  - `backend/tests/unit/test_telegram_sample_script.py`
  - `backend/tests/security/test_telegram_auth.py`
  - `backend/tests/api/test_storefront_auth.py`
  - helpers `backend/tests/telegram_kit.py` and `backend/tests/storefront.py`
- `docs/adr/ADR-036-tenant-bound-customer-sessions.md` and this report

**Changed:**
- `kernel/config.py`: Telegram environment and key, freshness, replay and customer-session settings, plus the production guards.
- `kernel/context.py`: `CustomerPrincipal`. `kernel/scope.py`: `CustomerScope`.
- `kernel/logging.py`: an optional output stream, used by tests to inspect the real redacting pipeline.
- `api/auth.py`: shared bearer parsing; the staff dependency is unchanged in behaviour.
- `api/routes/platform.py`: the bot-binding routes. `main.py` and `schema.py`: wiring.
- `pyproject.toml`: import contracts.
- Tests:
  - `conftest.py`: throwaway Telegram key and storefront fixtures.
  - `test_rls_coverage.py`: schema-qualified, scans every application schema, four new tables and table-specific tests.
  - `test_authentication.py`: the login route added to `PUBLIC`.
  - `test_input_and_disclosure.py`: production settings now need Telegram's production key.
  - `test_migrations.py`: downgrade removes `commerce`.
- Docs:
  - `04` §5, `17`, `19` (ISO-4, AUTH-1…4)
  - `20` (ADR index, A8, A9/D6)
  - `21`
  - ADR-012 (**Accepted**)
  - `runbooks/local-development.md` §6

## 3. Migration 0010

All four tables carry `tenant_id` and have **ENABLE + FORCE RLS** with policies keyed on `control.current_tenant_id()`. Children use composite `(tenant_id, …)` keys, and the runtime role has only column-level UPDATE grants that never include `tenant_id`.

| Table | Purpose | Key constraints | `arada_app` |
|---|---|---|---|
| `control.telegram_bots` | BYO bot per tenant; token envelope-encrypted (AAD = table, row, tenant, purpose) | one active per tenant; one active row per Telegram bot | SELECT, INSERT, UPDATE(status, disabled_at) |
| `commerce.customers` (new schema; USAGE for `arada_app` only) | person as seen by one tenant | UNIQUE(tenant_id, person_id), UNIQUE(tenant_id, id) | SELECT, INSERT |
| `control.customer_sessions` | opaque tenant-bound sessions (SHA-256 of token) | FK (tenant_id, customer_id) → customers; UNIQUE(token_hash) | SELECT, INSERT, UPDATE(last_seen_at, idle_expires_at, revoked_at, revoked_reason) |
| `control.telegram_init_data_uses` | replay window | PK (tenant_id, hash_digest); DELETE policy only for expired rows | SELECT, INSERT, DELETE, UPDATE(use_count) |

**Evidence:**
- `test_schema_builds_from_zero_and_round_trips`: zero → head → base → head, and downgrade removes `control` and `commerce`.
- `test_code_table_declarations_match_migrated_schema`: no drift.
- A fresh database migrated from zero served the Phase 1 walkthrough on a real uvicorn server, 10/10 steps (§7).

**Migration 0011 (2026-10-02).** It adds three `BEFORE UPDATE OF …` triggers whose functions run with a pinned `search_path` and have EXECUTE revoked from PUBLIC:
- a revoked customer session keeps its `revoked_at` and `revoked_reason`;
- a disabled bot cannot be reactivated, and its `disabled_at` cannot change;
- a replay `use_count` only increases.

There are no new tables, grants or SECURITY DEFINER functions. The rollback is `downgrade()` to 0010, which drops the triggers and functions with no data loss.

**Rollback.** `downgrade()` drops the four tables and the schema. The data lost is only Phase 2 data: bots, customers, customer sessions and replay rows.

## 4. API changes

| Method | Path | Auth | Behaviour |
|---|---|---|---|
| POST | `/v1/storefront/auth/telegram` | none (public; tenant from Host) | Body `{init_data}` only (extra fields → 422). → `{access_token, expires_at}`. Any validation failure → generic 401; unknown host → 404 |
| GET | `/v1/storefront/me` | customer token, same host | the caller's own customer record |
| POST | `/v1/storefront/auth/logout` | customer token, same host | revokes the session (204) |
| PUT | `/v1/platform/tenants/{tenant_id}/telegram-bot` | staff, `bots.manage` (MFA-gated platform scope) | Body `{bot_id, bot_token}` (D6). Replaces any active bot and revokes the tenant's customer sessions. Same active bot on another tenant → 409. The token is never returned |
| GET / DELETE | same | staff, `bots.manage` | status (never the token) / disable (revokes sessions); 404 if no active bot |

There is no JWT and no refresh endpoint (ADR-036).

## 5. Tenant isolation evidence

- **The tenant comes only from Host.** `test_client_supplied_tenant_hints_never_choose_the_tenant` sends `X-Tenant-ID`, `X-Forwarded-Host`, `?tenant_id=` and a body `tenant_id` (422).
- **Cross-tenant `initData` (ISO-4).** Tenant B's genuine data at A's host gets the generic 401: `test_every_rejection_is_the_same_generic_401_with_a_logged_reason`, case "cross-tenant".
- **Foreign sessions.** A's customer token at B's host, or at an unknown host, gets 401: `test_customer_routes_refuse_missing_bad_and_foreign_tokens`.
- **SQL level, as `arada_app` with no service code** (`test_rls_coverage.py`):
  - the RLS lint now scans **every application schema** and fails on a new schema;
  - per-table reads (`test_tenant_a_reads_only_its_own_rows`) and writes (`test_tenant_a_cannot_write_tenant_b_rows`) cover all 13 tenant tables, including the four new ones;
  - `test_bot_tokens_and_bindings_cannot_be_rewritten_by_the_runtime_role`;
  - `test_customer_sessions_bind_to_their_own_tenant_and_customer` (composite FK, column grants);
  - `test_replay_rows_can_only_be_deleted_once_expired`;
  - `test_commerce_schema_is_closed_to_everyone_but_the_runtime_role`.
- **One person at two merchants** gets two unlinked customer rows: `test_one_person_two_merchants_two_unlinked_customers`.
- **Phase 1 isolation suites unchanged and green:** tenant isolation 16, connection-pool isolation 4.

## 6. RBAC evidence

- **Bot binding needs `bots.manage` with MFA.** `test_bot_binding_is_platform_only_mfa_gated_and_validated`:
  - anonymous gets 401;
  - tenant owner, admin and staff get 403;
  - a PLATFORM_ADMIN with a password-only session gets 403 `mfa-required-for-scope`;
  - after TOTP: 200;
  - validation errors get 422, an unknown tenant 404 and a bot clash 409;
  - the action is audited with the actor and the request id.
- **A customer session grants nothing staff-side.** `test_customer_tokens_are_refused_by_every_staff_operation` enumerates OpenAPI: every non-storefront operation, at the merchant host and the default host, gets 401. `test_customer_authentication_grants_no_business_permission`.
- **Staff tokens are refused on customer routes:** `test_customer_routes_refuse_missing_bad_and_foreign_tokens`.
- **Phase 1 RBAC and MFA suites unchanged and green (44).** That includes SUPER_ADMIN revocation and session rotation.

## 7. Test results (re-run 2026-10-02, after the hardening)

| Gate | Result |
|---|---|
| Full suite | **314 passed, 0 failed** (Phase 1 ended at 214; 311 before the hardening) |
| Coverage | **91%** lines (`--cov=arada`); new modules 87–98% |
| ruff check + format | clean (backend and `scripts/`) |
| mypy (strict) | no issues, 124 source files |
| lint-imports | 5 contracts kept, 0 broken |
| pip-audit | no known vulnerabilities; **no new runtime dependency** (Ed25519 comes from `cryptography`, already present) |
| Migrations | from zero to 0011, round trip, no drift |
| Database used | PostgreSQL **16.14** on loopback in the agent sandbox (no Docker daemon there). The compose stack pins 17, and CI runs against the compose version |
| Fresh-stack walkthrough | new database migrated from zero, real uvicorn, CLI bootstrap, `scripts/phase1_walkthrough.py`: **10/10** |
| Container image scan | **not run here**: the sandbox cannot pull the base image (ghcr.io denied) or Trivy's database. CI runs it on pull requests and pushes to `main`; it has not run for these commits yet |

**Phase 2 suites:**
- validator unit 56 (two cases added inside an existing test)
- sample-checker unit 2
- Telegram security 17
- storefront API and integration 12
- RLS 36 (was 23)
- all security tests 96

## 8. Security tests: the owner's list, with evidence

| # | Requirement | Test |
|---|---|---|
| 1 | forged initData | `test_every_rejection…` ("forged"); unit `test_hmac_valid_but_unsigned_data_forged_with_the_token_fails` |
| 2 | malformed | `test_every_rejection…`; unit `test_structurally_malformed_input_fails` (12 shapes), `test_user_must_be_a_documented_webappuser` (14) |
| 3 | invalid HMAC | `test_every_rejection…`; unit `test_tampering_with_any_signed_field_fails`, `test_hash_made_with_another_bot_token_fails` |
| 4 | invalid Ed25519 | `test_every_rejection…`; unit `test_signature_padding_alphabet_and_length` |
| 5 | expired / auth_date policy | `test_every_rejection…` (stale, future); unit `test_stale_future_and_non_integer_auth_date` |
| 6 | replay | `test_replayed_init_data_is_refused_after_the_use_cap` (30 concurrent uses of one initData: exactly 20 accepted); `test_reloads_within_the_window_work_and_stop_when_it_closes`; `test_replay_rows_outlive_the_freshness_window`; `test_revocation_disabling_and_replay_counts_only_move_forward` |
| 7 | cross-tenant bot mismatch | `test_every_rejection…` ("cross-tenant") |
| 8 | wrong bot_id | `test_wrong_registered_bot_id_fails_closed`; unit `test_signature_for_another_bot_id_fails` |
| 9 | wrong environment / public key | `test_signature_from_the_other_telegram_environment_is_refused`; `test_production_refuses_the_test_key_and_any_mismatch`; `test_staging_accepts_only_telegrams_published_keys`; unit `test_test_environment_signature_is_refused_under_the_production_key` |
| 10 | missing required fields | `test_every_rejection…`; unit `test_missing_required_fields_fail`, `test_duplicate_fields_fail` |
| 11 | other Telegram mechanisms | `test_every_rejection…` (Login Widget, OIDC id_token); unit `test_login_widget_mechanism_never_validates_mini_app_data`, `test_an_openid_connect_id_token_is_not_init_data` |
| 12 | unauthorized customer access | `test_customer_routes_refuse_missing_bad_and_foreign_tokens`; `test_customer_authentication_grants_no_business_permission` |
| 13 | customer token on staff routes | `test_customer_tokens_are_refused_by_every_staff_operation` (OpenAPI-driven) |
| 14 | staff token on customer routes | `test_customer_routes_refuse_missing_bad_and_foreign_tokens` |
| 15 | session at another tenant | same test (A's token at B's host and at an unknown host) |
| 16 | raw initData never in logs | `test_raw_init_data_bot_tokens_and_personal_data_never_reach_the_logs` (also hash, signature, query_id, names, Telegram id, access token) |
| 17 | bot token never in logs | same test, plus `test_bot_token_is_never_returned_or_audited` |
| 18 | initDataUnsafe never used | `test_init_data_unsafe_is_never_used_by_server_code`: AST-based, with a planted-use check proving it is not vacuous; `test_login_body_accepts_only_the_raw_init_data_string` |

**Also tested:**
- the generic 401 body is identical for every reason;
- an unknown host gets 404, and a tenant without a bot gets 401;
- no key configured fails closed;
- a disabled person cannot log in, and their sessions die;
- a suspended tenant stops logins and sessions;
- expiry and idle timeout;
- bot replacement and disabling revoke sessions;
- concurrent first logins converge on one person, identity and customer;
- failed attempts write no audit rows.

**Sabotage proofs.** Each break below was made, run, observed failing, and reverted:

| Break | Failures |
|---|---|
| validator: `signature` left out of the HMAC string | 25 |
| validator: Ed25519 skipped | 3 |
| validator: Login-Widget key derivation | 25 |
| validator: freshness skipped | 1 |
| validator: duplicates allowed | 4 |
| validator: `bot_id` not in the signed message | 23 |
| FORCE RLS removed from `commerce.customers` | RLS lint failed |
| `customer_sessions` isolation policy removed | 8 failed, 32 errors |
| the reason returned to the client | 5 |
| raw initData logged under an unredacted key | 1 |
| replay window not recorded | 2 |
| bot replacement keeping sessions | 1 |
| disabled person allowed to log in | 1 |

## 9. Live test-environment sample and docs re-check

- **Live sample: NOT DONE (owner action).** It needs a Telegram test-environment account and bot, which this environment does not have, and the sample must never be committed. Run `cd backend && uv run python ../scripts/telegram_sample_check.py` (runbook §6), preferably with an Amharic name containing a space. The checker reports whether Telegram's hash and signature match the A8 reading or an alternative reading. **Until it reports A8 MATCH for both, conformance with Telegram is unverified.**
- **Official docs re-check: NOT DONE here.** `core.telegram.org` is still denied by this environment's network policy; the proxy answered `403` on 2026-10-01 and again on 2026-10-02. The last check is the owner's B5 verification (`PHASE_2_PLAN.md` §14, page hashes recorded). Re-check from the workstation before accepting Phase 2.

## 10. ADR changes

- **ADR-012: Accepted** (owner directive), with an implementation section: validator, order, keys and fingerprints, D6, A8.
- **ADR-036 (new, Proposed):** opaque, server-side customer sessions bound to tenant and customer. Approved in principle (D4); awaiting final review. Once accepted it supersedes the JWT and refresh text in `04` §5 and `17`, which are now annotated.
- **Register:** A8 implemented but **not yet confirmed**; A9 approved (D6); B4 unchanged.

## 11. Known limitations and remaining risks

- **B4: AUTHENTICATION RATE LIMITING = REQUIRED BEFORE PUBLIC EXPOSURE.** `/v1/storefront/auth/telegram` is unauthenticated. A rejected request costs a host lookup, one envelope decryption (two AES-GCM operations), one HMAC and at most one Ed25519 verification, and commits no writes. An accepted one writes rows, but needs a Telegram signature.
- **A8 unconfirmed** until the live sample passes (§9).
- **Failure metrics are logs only.** There is no metrics backend (deferred with monitoring).
- **Telegram key rotation** makes production fail closed until the docs are re-verified and the fingerprint is updated (ADR-012). This is intended, but it is an operational dependency.
- **Wrong `bot_id` or revoked token.** If the admin registers the wrong `bot_id`, or a merchant revokes the token in @BotFather, logins fail closed until the bot is re-registered. There is no `getMe` check (D6).
- **Keyboard-button and inline-mode launches** carry no `initData`, so they cannot log in (Telegram behaviour, `PHASE_2_PLAN.md` §5 row 15).
- **Re-verify the Host header trust** at the first deployment (edge configuration); nothing is deployed.
- **The replay window is per tenant and in PostgreSQL**, pruned opportunistically. There is no scheduler.
- **Timing is not uniform across failure reasons.** A host with no bot answers faster than a crypto failure, so response timing can reveal whether a merchant host has a bot bound. The body is identical. This is low impact, since bot binding is not secret, and it is bounded by B4.
- **Staff sessions (Phase 1) do not have the forward-only revocation trigger** that migration 0011 gives customer sessions. Their revocation is enforced by service code and column grants, as approved in Phase 1. Adding the same trigger to `control.sessions` would be a separate, owner-approved Phase 1 hardening; it was deliberately not changed here.
- **CI has not run on these commits:** the workflow triggers on pull requests and `main` only. The container scan likewise (§7).

## 12. Status

| Item | Status |
|---|---|
| Mini App validator (HMAC + Ed25519 + bot binding + freshness) | **Implemented, verified by test** against our reading of the verified spec |
| Conformance with live Telegram data (A8) | **Not verified**: owner's live sample outstanding |
| Tenant resolution integration, identity mapping, BYO bot binding | **Implemented, verified by test** |
| Customer model and tenant-bound sessions, customer endpoints | **Implemented, verified by test** (ADR-036 awaiting final review) |
| Authorization integration and credential separation | **Implemented, verified by test** |
| Audit and correlation | **Implemented, verified by test**; failure metrics are logs only |
| Database and RLS changes | **Implemented, verified by test** (SQL-level, as the runtime role) |
| Official docs re-check before completion | **Blocked here** (network policy); owner action. Compare the page hashes with `PHASE_2_PLAN.md` §14 |
| Forward-only database invariants (migration 0011) | **Implemented, verified by test** (2026-10-02) |
| Authentication rate limiting (B4) | **Open: REQUIRED BEFORE PUBLIC EXPOSURE** |
| Webhooks, deep links, notifications, managed bots, frontend, Redis, payments, Merchant Factory, deployment | **Not implemented** (non-goals) |
| Production readiness | **No** |
