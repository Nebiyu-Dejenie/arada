# Phase 2 — deep independent code audit

| Field | Value |
|---|---|
| **Scope** | Code-only audit of the Phase 2 Telegram foundation, treated as untrusted again (owner directive 2026-10-02, while the two external completion gates are pending) |
| **Commit audited** | `a496061` on `claude/elegant-lovelace-52pep5` |
| **Date** | 2026-10-02 |
| **Result** | **One HIGH (conditional) defect found and fixed (F1):** a parser ambiguity around the line-feed field separator that could allow impersonation. **Real-world exploitability: UNVERIFIED.** No other confirmed vulnerability: F2 was a test gap, F3 is a LOW residual, and F4–F9 are informational or deferred items. Phase 2 is **not complete** (§0) |
| **Evidence revision** | 2026-10-02: F1 classification, exact evidence (§0.1), F4 lifecycle (§F4) and gate statuses (§0) made explicit. Documentation only; code identical to `98dd1b7` |
| **Not done** | Nothing was merged, deployed or configured. Phase 1 behaviour is unchanged. No B4 work. No Telegram network access (core.telegram.org is denied by the environment), so nothing here changes or confirms the protocol reading. **A8 remains unverified** |

## 0. Status (2026-10-02)

| Item | Status |
|---|---|
| B4, authentication rate limiting | **REQUIRED BEFORE PUBLIC EXPOSURE** (not implemented) |
| Gate 1, live Telegram test-environment sample (A8) | **OPEN** |
| Gate 2, fresh official Telegram documentation verification | **OPEN** (core.telegram.org is denied by this environment's network policy) |
| Phase 3 | **BLOCKED** |
| Production exposure | **NOT APPROVED** |
| Merge into `main` | **NOT AUTHORIZED** |

### 0.1 Evidence record

| Evidence | Exact reference |
|---|---|
| Commit audited | `a496061` |
| Commit containing the F1 fix | `98dd1b7` `fix(telegram): refuse the line-feed separator inside initData values`. It touches `backend/src/arada/telegram/miniapp.py` (the fix), `scripts/telegram_sample_check.py` (diagnostic) and four test files |
| Commit containing this report | `49f8896`; this evidence revision is a later documentation-only commit. `git diff 98dd1b7 HEAD -- backend scripts` is empty |
| F1 unit regression test | `backend/tests/unit/test_telegram_miniapp.py::test_a_value_containing_the_line_feed_separator_is_refused` |
| F1 end-to-end identity and session test | `backend/tests/security/test_telegram_auth.py::test_a_resplit_signed_string_cannot_impersonate_another_user`. Before the fix, the API returned 200 and a customer session for the victim's Telegram id. After it: generic 401, logged reason `malformed`, and no `telegram` identity row for the victim |
| F1 checker diagnostic | `backend/tests/unit/test_telegram_sample_script.py::test_a_strict_parse_rejection_names_the_rule_never_the_value` (7 parametrised cases, one of them F1) |
| F2 RBAC test | `backend/tests/api/test_storefront_auth.py::test_bot_management_refuses_cross_tenant_actors_archived_tenants_and_dead_bots` |
| Regression tests failed first | The three F1 tests failed before the fix (3 failed, 82 passed in the affected files). The F2 test failed with the archived-tenant guard removed |
| Full suite | `cd backend && uv run pytest -q` → **325 passed, 0 failed** (re-run on the current head, 2026-10-02) |
| Security suite | `uv run pytest -q tests/security` → **97 passed** |
| The four F1/F2 tests above | **10 passed** (10 test cases, counting the parametrised ones) |
| Static gates | `ruff check . ../scripts` clean; `ruff format --check` clean; `mypy` (strict) no issues in 124 files; `lint-imports` 5 kept, 0 broken |
| Test database | **PostgreSQL 16.14** (Ubuntu package), on loopback in the agent sandbox, which has no Docker daemon |
| Stack database | **PostgreSQL 17** (`compose.yaml`: `postgres:17-alpine`). CI starts that service (`docker compose up -d --wait postgres`), but **CI has not run on these commits**: the workflow triggers on pull requests and `main` only. Results on 17 are therefore **not yet observed** |

## 1. Method

- **Read in full:**
  - `telegram/miniapp.py`, `customers/{telegram_login,sessions,service,tables}.py`, `bots/{service,tables}.py`, `identity/telegram.py`, `access/customer.py`
  - `api/routes/{storefront,platform}.py`, `api/{auth,errors,middleware}.py`, `kernel/{config,db,context,scope,logging}.py`
  - `tenancy/service.py` (`resolve_by_host`, `enter_tenant`), `audit/service.py`
  - migrations 0001 (context functions), 0009 (host resolver), 0010 and 0011
  - `scripts/telegram_sample_check.py`, and the Phase 2 tests and test kit
- **Live catalog dump** of a database migrated from zero to `0011_customer_auth_guards`: privileges per role, RLS and FORCE flags, policies, triggers, SECURITY DEFINER functions and schema usage (§5).
- **Dynamic probes** against the real stack (PostgreSQL 16.14 on loopback, real app over ASGI): parser re-splitting, encoding variants, a replay race with the use cap set to 1, failure-path timing, bot transfer between tenants, deeply nested signed JSON and configuration bounds. The probe file was temporary; what proved worth keeping became regression tests.
- **Sabotage:** for every new test, and for one new boundary question (the RLS policy on `telegram_bots`).
- The earlier 13 sabotage proofs (`PHASE_2.md` §0) cover code this audit left unchanged.

## 2. Findings

| ID | Severity | Finding | Status |
|---|---|---|---|
| F1 | **HIGH (conditional)** | Parser ambiguity: a decoded value could contain the line-feed field separator, so the signed data-check-string had more than one parse, which enables impersonation. Real-world exploitability **UNVERIFIED** | **Fixed** in `98dd1b7` (defensive; correct either way) |
| F2 | LOW | No tests for bot management by a cross-tenant actor, on an archived tenant, or after a bot is disabled (behaviour was correct) | **Fixed** (test added, sabotage-proven) |
| F3 | LOW | Response timing differs by failure path (no bot ≈ 1 ms faster than a crypto failure, in-process) | Accepted residual; bounded by B4 |
| F4 | INFORMATIONAL | Replay state is per tenant, so after a bot moves to another tenant, the same fresh `initData` can be used once more there | Accepted |
| F5 | INFORMATIONAL | Bot lookup and bulk revocation rely on RLS alone, with no explicit tenant predicate | Accepted (ADR-034); proven covered by tests |
| F6 | INFORMATIONAL | Session lifetime settings have no upper bound (staff and customer alike) | Accepted (operator configuration; Phase 1 parity) |
| F7 | INFORMATIONAL | An unauthenticated request triggers host resolution, a bot read and a token decryption before the cheap structural parse | B4 input |
| F8 | INFORMATIONAL | Failed logins are logged with a reason but are not in the audit trail, and there are no metrics | By design (B4); later work |
| F9 | INFORMATIONAL | Phase 1 staff sessions have no forward-only revocation trigger | Not changed (Phase 1 boundary); proposal only |

**Only F1 is a confirmed defect in code.** F2 was a missing test; the behaviour was correct. F3 is a LOW residual, not a vulnerability. **F4–F9 are informational or deferred items. None is a confirmed vulnerability**, and no exploit path was demonstrated for any of them.

### F1 — HIGH (conditional): ambiguous data-check-string allows impersonation

**Classification.**
- **Cause:** parser ambiguity around the line-feed field separator. Both data-check-strings join fields with `\n`, and `parse()` accepted a decoded value containing `\n`. The mapping from fields to signed bytes was therefore not one-to-one.
- **Fix:** defensive, and correct whether or not Telegram currently permits a line feed in `start_param` or in any other value. With the separator refused inside values, the parse is unique by construction. Nothing a correct Telegram client sends without a line feed in a value is affected.
- **Real-world exploitability: UNVERIFIED.** It depends on whether Telegram will sign an attacker-chosen value containing a line feed and JSON characters (in practice `start_param`). That stays unverified until the official documentation check (Gate 2) and the live sample (Gate 1) are done. Neither gate can **disprove the need for the fix**; they can only settle whether the defect was ever exploitable.

**Symptom.** The validator accepted `initData` whose fields differ from the ones Telegram signed, with the same signature and hash.

**Evidence.** Both data-check-strings join `key=<value>` pairs with a line feed (verified spec, `PHASE_2_PLAN.md` §5 rows 4 and 7). `parse()` percent-decodes values and accepted a decoded value containing `\n`. A string such as `start_param=x\nuser={victim}\nuserz=\nuser={attacker}` therefore has two parses that produce **byte-identical** signed strings:
- Telegram's parse: `start_param` = `x\nuser={victim}\nuserz=`, and `user` = the attacker.
- The holder's re-split: `start_param` = `x`, `user` = **the victim**, and `userz` = `\nuser={attacker}`.

The keys stay sorted, none is duplicated, and `user` is valid JSON.

**Reproduction (before the fix).**
- `tests/unit/test_telegram_miniapp.py::test_a_value_containing_the_line_feed_separator_is_refused`: the forged vector verified as user `424242`, although the signer's user was `1111`.
- End to end, `tests/security/test_telegram_auth.py::test_a_resplit_signed_string_cannot_impersonate_another_user`: `POST /v1/storefront/auth/telegram` returned **200 with a customer session** for the victim's Telegram id.

**Root cause.** The signed format uses `\n` as its separator, and the parser allowed the separator inside values, so the mapping from fields to signed bytes was not injective. Neither HMAC nor Ed25519 can detect a re-split, because the bytes are identical.

**Precondition (why "conditional").** The attack needs Telegram to sign a value that the attacker controls and that contains a line feed plus JSON characters. In practice the candidate is `start_param`, which comes from the link the user opens. JSON-serialised fields (`user`, `receiver`, `chat`) cannot carry a raw line feed. **Whether Telegram permits these characters in `start_param` is not verified here**, because the official docs are unreachable from this environment and memory is not evidence. If Telegram does, the impact is **CRITICAL**: any user of a merchant's Mini App could log in as any other Telegram user at that merchant. If Telegram restricts the character set, it is not exploitable. It is rated HIGH, not CRITICAL, for that reason, and it is fixed regardless. A future Telegram field carrying user text would reopen the risk without the fix.

**Architecture impact.** None. The change is local to the pure validator; there is no schema, API or protocol change. A8 decoding is unchanged (`+`, `%XX`, UTF-8). Only one thing changes: a decoded value containing a line feed is refused.

**Fix.** `miniapp.parse()` refuses any decoded value containing `\n` (`_SEPARATOR`) as `malformed`, which gives the generic 401. Keys could not contain it already (`[A-Za-z0-9_]{1,64}`). With the separator excluded from values, every `\n` in a check string is a field boundary and every key ends at its first `=`, so the parse is unique. A carriage return is not the separator and stays allowed (tested). The live-sample checker reports this rule by field name: `field '<name>': contains a line feed`.

**Regression tests.** Each failed before the fix and passes after it:
- the unit test above: forged and genuine vectors, `\n` in `query_id`, `start_param` and `chat_instance`, and `\r` still accepted;
- the end-to-end API test above: generic 401, reason `malformed`, and **no identity created** for the victim;
- `test_telegram_sample_script.py`: the new diagnostic.

**Verification.** Full suite 325 passed; security 97 passed; ruff, format, mypy (strict) and lint-imports (5/5) clean.

**Gate impact.** Gate 1 (A8) is unaffected unless a genuine Telegram sample contains a line feed in a value. The checker would then say so by field name, without the value, and that would itself be evidence for the owner to weigh.

### F2 — LOW: RBAC test gaps for bot management

Behaviour was correct, but these cases had no test: staff of another tenant (B's owner and admin) on tenant A's bot routes; a disabled bot (management 404, login 401); and an archived tenant (binding 404, host login 404). The new test `test_bot_management_refuses_cross_tenant_actors_archived_tenants_and_dead_bots` covers them, and it **fails when the archived-tenant guard in `bots.register` is removed** (sabotage run, then restored).

### F3 — LOW: timing differences between failure paths

Medians of 60 in-process requests: malformed 8.6 ms, bad hash 8.0 ms, no bot 7.0 ms, unknown host 4.8 ms (404, an approved distinct status). The response body and headers are identical for every 401. The no-bot path skips a token decryption, so timing can hint whether a merchant host has a bot bound. Merchant hosts and their existence are already public (`GET /v1/storefront/merchant`), and nothing secret is compared in non-constant time (`hmac.compare_digest`). An application-level equaliser (dummy work on `no_bot`) is possible but would not remove database and network variance. **Recommendation:** accept, and revisit with B4 (rate limiting bounds probing).

### F4 — INFORMATIONAL: replay state after a bot moves between tenants

**Observed behaviour (probe, 2026-10-02).**
1. Bot X is active for tenant A.
2. A Telegram user opens X's Mini App and logs in at A's host with `initData` D. A replay row `(A, hash(D))` is written.
3. A platform admin disables X at A, which revokes A's customer sessions, and binds X (same `bot_id`, same token) to tenant B.
4. Within D's freshness window (`auth_date` + 1 h), D is presented at B's host. HMAC passes (same token) and Ed25519 passes (same `bot_id`). There is no replay row `(B, hash(D))`, so it is a first use at B. A customer and a session are created at **B** for that Telegram user.
5. D at A's host gets 401 (A has no bot).

**The lifecycle question.** Is `initData` bound to the **bot** (Telegram's binding: `bot_id` in the signed string, the token in the HMAC) or to the **tenant that owned the bot when the user opened the Mini App** (ARADA's mapping)? The implementation binds it to the bot, and to the tenant only through the bot's *current* binding. Replay state is per tenant (`PRIMARY KEY (tenant_id, hash_digest)`, as approved in `PHASE_2_PLAN.md` §7), so it does not follow a bot across tenants.

**Invariant check: no violation found.**
- Tenant from Host: holds (B's host gives B).
- Bot bound to one tenant: holds (X belongs only to B at that moment).
- Identity: genuine (the Telegram user of bot X).
- No staff or cross-tenant privilege is gained; A's sessions were revoked.
- The use cap at B still applies.

What happens is that a user whose Mini App was opened while X served A is admitted at B, the bot's current owner, at most once per replay window, within one hour of `auth_date`. Reopening the Mini App after the transfer would give the same result. **Not a confirmed vulnerability. No implementation change.**

**Open for a future bot-transfer feature (owner decision, not Phase 2):** whether `initData` with an `auth_date` before the current binding's `created_at` should be refused. That would make the tenant at Mini App launch authoritative. Bot transfer is not a Phase 2 feature; it is reachable only by a platform admin through disable then re-bind.

### F5 — INFORMATIONAL: bot lookup relies on RLS alone (not a vulnerability)

`bots.active_bot_for_login`, `_active`, `_disable_active` and `customer_sessions.revoke_all_in_tenant` have no explicit `tenant_id` predicate; they rely on FORCE RLS under the Host-resolved context, as ADR-034 intends. Without any context, RLS returns zero rows (fail closed). **Sabotage evidence:** with a permissive policy added to `telegram_bots`, the suite fails massively (logins fail, and every per-table RLS test errors). Removing FORCE RLS is caught by the RLS lint. **No change**: adding predicates would be purity without new evidence.

### F6 — INFORMATIONAL: unbounded session lifetime settings (configuration hygiene; deferred)

`Settings(customer_session_absolute_timeout_hours=10**6)` is accepted, and so is the Phase 1 staff equivalent. These are operator configuration, not client input. **No change**: the staff bound would touch Phase 1. Recommend an upper bound in a future configuration review.

### F7 — INFORMATIONAL: cost of an unauthenticated request (input to B4; deferred)

A rejected login costs host resolution (2 queries), setting the context (1), the bot read (1), one envelope decryption (2× AES-GCM) and one HMAC. It commits no writes. `Ed25519` runs only after a valid HMAC. The request body may be up to `max_request_body_bytes` (1 MiB), and the 4 KiB `init_data` cap applies after JSON parsing. **Input for B4:** consider a structural pre-parse before database work, and a per-route body limit. Not done here.

### F8 — INFORMATIONAL: failed logins are not audited, and there are no metrics (by design; deferred)

Failures go only to `telegram.auth_failed` log events with `reason`, `request_id`, `trace_id` and `tenant_id`. That is deliberate: an unauthenticated endpoint commits no writes on failure (register B4). Investigation is possible from logs (§8). Alerting later needs a metrics backend: counters by `reason` and tenant, and rates of `bad_signature` and `replayed`.

### F9 — INFORMATIONAL: staff-session revocation parity (defence in depth; deferred)

`control.sessions` (Phase 1) has no database trigger against un-revoking. Its column grants would allow it, but **no code path does so**: revocation is enforced by code, as approved in Phase 1. This is a defence-in-depth difference, not a vulnerability. Per the owner's boundary, **not changed**. A proposal for a separate decision: the same `BEFORE UPDATE OF revoked_at` guard as migration 0011, in its own migration with its own tests.

## 3. Cryptographic trace (raw `initData` → verified identity)

| Step | Where | Assumption | Invariant | Tests |
|---|---|---|---|---|
| Body | `api/routes/storefront.py:TelegramAuthIn` | Only the raw string is accepted | One field (`extra="forbid"`); no `initDataUnsafe` | `test_login_body_accepts_only_the_raw_init_data_string`; AST check `test_init_data_unsafe_is_never_used_by_server_code` |
| Tenant | `customers/telegram_login.login` → `tenancy.resolve_by_host` | Host is server-side (edge-trusted at deployment) | Active tenants only; no client tenant input | `test_client_supplied_tenant_hints_never_choose_the_tenant`, `test_unknown_host_and_unbound_tenant` |
| Bot | `bots.active_bot_for_login` | RLS context = Host tenant | One active bot per tenant and per bot id (DB); token opened with AAD `telegram_bots\|row\|tenant\|bot_token` | `test_bot_tokens_and_bindings_cannot_be_rewritten_by_the_runtime_role`; F5 sabotage |
| Parse | `miniapp.parse`, `_decode_component` | **A8** (form decoding, UTF-8): **unverified** | ≤ 4096 characters, ≤ 64 fields; URL-safe raw characters; strict escapes and UTF-8; unique keys `[A-Za-z0-9_]{1,64}`; **no `\n` in values (F1)**; unknown fields kept | `test_structurally_malformed_input_fails`, `test_duplicate_fields_fail`, `test_unknown_fields_are_covered_by_hash_and_signature`, `test_non_ascii_spaces_and_plus_follow_assumption_a8`, F1 tests |
| Required fields | `miniapp.verify` | `hash`, `signature` and `auth_date` are not optional; `user` is needed for identity | Missing → `malformed` | `test_missing_required_fields_fail` |
| HMAC key | `miniapp.hmac_secret_key` | Verified: `HMAC_SHA256(key="WebAppData", msg=token)` | Never `SHA256(token)` (Login Widget) | `test_login_widget_mechanism_never_validates_mini_app_data`; sabotage (76 failures) |
| HMAC string | `miniapp.expected_hash` → `data_check_string(exclude={"hash"})` | Verified: includes `signature` and unknown fields, sorted, `\n`-joined | Sorted by code point (keys are ASCII) | `test_signature_is_in_the_hmac_string_but_not_in_the_signed_message`; sabotage |
| Hash compare | `miniapp.verify` | Letter case not stated | Exactly 64 hex characters → 32 bytes; `hmac.compare_digest` | `test_hash_letter_case_and_length`; sabotage |
| Signature decode | `miniapp.decode_signature` | Padding not stated | base64url only, 86 characters with optional `==`, exactly 64 bytes | `test_signature_padding_alphabet_and_length` |
| Ed25519 message | `miniapp.signed_message` | Verified: `<bot_id>:WebAppData\n` + fields except `hash` and `signature` | `bot_id` is the tenant's registered id, never parsed from the token (A9) | `test_signature_for_another_bot_id_fails`, `test_wrong_registered_bot_id_fails_closed`; sabotage (73) |
| Public key | `telegram_login._public_key` ← `Settings.telegram_public_key_hex` | One key per deployment | Validated as 32-byte Ed25519 at startup; none configured → fail closed | `test_without_a_configured_key_every_login_fails_closed` |
| Environment | `kernel/config.py` validators, `TELEGRAM_KEY_FINGERPRINTS` | Fingerprints of the two published keys (recomputed in this audit: match) | A known key must match `telegram_environment`; production needs the production key; staging needs a published key; a throwaway key only in development and test | `test_production_refuses_the_test_key_and_any_mismatch`, `test_staging_accepts_only_telegrams_published_keys`, `test_signature_from_the_other_telegram_environment_is_refused` |
| Order | `miniapp.verify` | — | Parse → HMAC → Ed25519 → `auth_date` → `user`, so a forgery is always counted as forged | `test_every_rejection_is_the_same_generic_401_with_a_logged_reason` |
| Freshness | `miniapp.verify` | Policy (Telegram defines none) | 1 h maximum age, 60 s future skew; at most 12 digits; beyond year 9999 → `malformed` | `test_stale_future_and_non_integer_auth_date` |
| User | `miniapp.parse_user` | Verified field rules | JSON object, no duplicate keys or NaN; integer `id` with 0 < id ≤ 2^53−1; non-blank `first_name`; `is_bot` true → refused; only `user` is identity | `test_user_must_be_a_documented_webappuser`, `test_receiver_and_chat_are_never_used_for_identity` |

## 4. Parser and normalisation review

| Concern | Behaviour | Evidence |
|---|---|---|
| Duplicate parameters, including repeated `hash` or `signature` | `malformed` (before and after decoding a key, e.g. `au%74h_date`) | unit tests |
| Parameter order | Irrelevant: sorted by key for both strings | by construction |
| Percent encoding and `+` | Decoded once (A8); variants of one `initData` (`%20` or `+`, encoded key, hash case) all verify, and they **share one replay key**, because replay is keyed on the decoded 32-byte hash, not the raw string | probe P2 |
| Unicode and invalid UTF-8 | Decoded bytes must be strict UTF-8; raw non-ASCII is refused | unit tests |
| Malformed escapes | `%` without two hex digits → `malformed` | unit tests |
| Empty values | Allowed for unknown fields; required fields fail their own checks | unit tests |
| Unknown fields | Kept and covered by both checks | unit test; sabotage |
| Control characters | Raw: refused (character class). Decoded `\n`: **refused (F1)**. Other decoded controls are covered by both checks and never used for identity except inside JSON, where strict `json.loads` refuses raw controls | F1 tests |
| Oversized | > 4096 characters → `malformed`; a deeply nested signed `user` cannot exceed the parser's recursion depth within 4 KiB | probe P5 |
| Integers and timestamps | `auth_date` is ASCII digits only, ≤ 12; beyond year 9999 → `malformed` (no 500); `user.id` excludes bools and floats, and ≤ 2^53−1 | unit tests |
| Same bytes, different meaning | **Was possible (F1); now impossible**: the parse is injective | F1 tests |

## 5. Database (live catalog at `0011_customer_auth_guards`)

| Table | RLS / FORCE | Owner | `arada_app` | Column UPDATE | reader / resolver / PUBLIC | Triggers |
|---|---|---|---|---|---|---|
| `control.telegram_bots` | yes / yes | `arada_owner` | SELECT, INSERT | `status`, `disabled_at` | none / none / none | `tr_guard_telegram_bot_disabling` |
| `commerce.customers` | yes / yes | `arada_owner` | SELECT, INSERT | none | none / none / none | — |
| `control.customer_sessions` | yes / yes | `arada_owner` | SELECT, INSERT | `last_seen_at`, `idle_expires_at`, `revoked_at`, `revoked_reason` | none / none / none | `tr_guard_customer_session_revocation` |
| `control.telegram_init_data_uses` | yes / yes | `arada_owner` | SELECT, INSERT, DELETE | `use_count` | none / none / none | `tr_guard_init_data_use_count` |

- **Policies.** All are bound to `arada_app` and keyed on `tenant_id = control.current_tenant_id()`. On the replay table, DELETE also requires `expires_at < now()`.
- **Schema and functions.**
  - Only `arada_app` has USAGE on `commerce`.
  - SECURITY DEFINER functions are unchanged from Phase 1 (`memberships_of_current_person`, `resolve_invitation`, `resolve_storefront_host`).
  - The guard functions are SECURITY INVOKER with a pinned `search_path` and no EXECUTE for PUBLIC.
- **FORCE RLS everywhere.** All 13 tables with a `tenant_id` are under FORCE RLS.
- **The BYPASSRLS reader** has no grant on any Phase 2 table, and there are no default privileges.

**Can application code with valid credentials accidentally violate an invariant?**

| Invariant | Enforced by | Verdict |
|---|---|---|
| Session bound to tenant and customer | composite FK, no UPDATE on binding columns, RLS | Database |
| Session cannot be resurrected | trigger (0011) | Database |
| Session expiry not extended past absolute | CHECK `idle_expires_at <= expires_at`, no UPDATE on `expires_at` | Database |
| One active bot per tenant and per bot id | partial unique indexes | Database |
| Bot binding immutable; disabled is terminal | column grants and trigger | Database |
| Token encrypted at rest | application (envelope encryption, AAD) | Application; accepted (the DB cannot verify ciphertext) |
| Replay window cannot be reset early | DELETE policy (expired only), trigger (count only increases), no UPDATE on `first_used_at` | Database |
| Session issued to the right customer | application (`find_or_create` → `issue` in one transaction) | Application; accepted |
| Session lifetime bounded | configuration | Accepted (F6) |

**Migration safety.**
- Alembic runs `transaction_per_migration=True`, so 0010 commits atomically. Its grants follow ENABLE and FORCE RLS, so no grant is ever visible without RLS.
- Between the 0010 and 0011 commits, the code's own guards still apply. That is no regression, since the triggers are defence in depth.
- Old application code ignores the new tables. New code needs 0010, and without it requests fail with errors (fail closed).
- The zero → head → base → head round trip and the drift check pass (`test_migrations.py`).
- Rollback: 0011 → 0010 drops triggers only, with no data loss. 0010 → 0009 drops Phase 2 data.

## 6. Replay protection

| Check | Result |
|---|---|
| Atomicity | One `INSERT … ON CONFLICT (tenant_id, hash_digest) DO UPDATE SET use_count = use_count + 1 WHERE first_used_at > now() - window AND use_count < cap RETURNING`. Under READ COMMITTED the conflicting row is locked and the `WHERE` is re-evaluated on its latest version, so there is no read-then-write gap |
| **TOCTOU probe** | Cap set to 1, 25 concurrent identical requests: **exactly 1 success** in each of 3 rounds (probe P3). With the default cap, 30 concurrent requests give exactly 20 (`test_replayed_init_data_is_refused_after_the_use_cap`) |
| Rollback | A later failure (`user_rejected`, an error) rolls the use back with the transaction |
| Pruning and clock drift | Rows live until `auth_date + max_age + future_skew + 5 min` (database clock), beyond any moment the data can pass freshness (application clock) | 
| Reset | Impossible for the runtime role: trigger, DELETE policy, column grants (`test_revocation_disabling_and_replay_counts_only_move_forward`) |
| Binding | Per tenant; across a bot transfer, see F4 |

## 7. Customer sessions compared with Phase 1 staff sessions

| Property | Staff (`identity/sessions.py`, Phase 1) | Customer (`customers/sessions.py`) |
|---|---|---|
| Token | `secrets.token_urlsafe(32)` (256 bits) | same |
| Stored | SHA-256 only | SHA-256 only, `UNIQUE`, `CHECK octet_length = 32` |
| Lifetime | idle 30 min sliding, absolute 12 h | same (separate settings) |
| Tenant binding | none (staff scope comes from roles) | composite FK plus FORCE RLS; looked up only in the Host tenant |
| Revocation | code and column grants | code, column grants **and a forward-only trigger** |
| Privilege change | rotation (ADR-035) | not applicable: a customer session carries no privilege |
| Enumeration | one 401 for every state | one 401 for every state, including an unknown host on `/me` |
| Transport | `Authorization: Bearer` only | same; the token is never in a URL or a log |

## 8. Disclosure, audit and observability

- **Client.** Every failed Telegram login gets the same problem document (`type`, `title`, `status`, `instance`, `request_id`) and the same headers (probe P4). The reason is never returned (sabotage: 5 failures).
- **Approved distinct answers.** An unknown host gets 404 (plan §8). A body with extra fields gets 422, and validation errors never echo input (`api/errors.py`).
- **Tracebacks.** The 500 handler logs the exception class and traceback, never locals. Of the Telegram path's exception messages, none carries input: parse errors are caught; `auth_date` and the JSON depth are bounded.
- **Logs.**
  - `telegram.auth_failed` carries `reason`, `request_id`, `trace_id` and `tenant_id`.
  - `telegram.auth_succeeded` adds `customer_id`.
  - Raw `initData`, tokens, `hash`, `signature`, `query_id`, names and Telegram ids are absent (`test_raw_init_data_bot_tokens_and_personal_data_never_reach_the_logs`; sabotage).
- **Audit.** Each row has `tenant_id`, the actor person, `request_id`, `trace_id`, IP, user agent and outcome:
  - `identity.person_created`, `customer.created`, `auth.customer_login` (with `session_id`), `auth.customer_logout`;
  - `telegram.bot_registered` (bot id and revoked count; never the token), `telegram.bot_disabled`.

  Failures are in logs only (F8).
- **Bot token exposure.**
  - It is never in a response (`test_bot_token_is_never_returned_or_audited`), a log, an audit row or a `repr` (`LoginBot.token` has `repr=False`).
  - Fixtures generate fake tokens at runtime.
  - AAD binds each ciphertext to its row and tenant, so a copied ciphertext cannot be opened under another tenant.

## 9. Route boundaries

| Route | Authentication | Tenant source | Authorisation | Sensitive data | Negative tests |
|---|---|---|---|---|---|
| `POST /v1/storefront/auth/telegram` | `initData` (HMAC + Ed25519 + freshness + replay) | Host only | Creates only the caller's own customer and session | Returns a new token once | Generic-401 suite, cross-tenant, hints ignored, replay, F1 |
| `GET /v1/storefront/me` | customer bearer, looked up in the Host tenant | Host, then RLS | Own record only (`tenant_id`, `customer_id` and `person_id` all matched) | Display name | Foreign, staff and bad tokens; unknown host; expired, idle, disabled |
| `POST /v1/storefront/auth/logout` | customer bearer | Host, then RLS | Own session only | — | Same as `/me`; logout at another tenant revokes nothing |
| `PUT /v1/platform/tenants/{id}/telegram-bot` | staff bearer | path id via `enter_tenant` (platform scope) | `bots.manage` (MFA-gated) checked **before** any tenant read | Token write-only | Anonymous, tenant roles, cross-tenant roles, no MFA, 422, 404, 409, archived (F2) |
| `GET`/`DELETE` same | staff bearer | same | `bots.manage` first | Bot id only | same; disabled bot → 404 (F2) |
| `GET /v1/storefront/merchant` (Phase 1) | none | Host | Public profile | — | Phase 1 |
| Every other route | staff bearer | — | Phase 1 RBAC | — | OpenAPI sweep: a customer token gets 401 on every non-storefront operation, at both hosts |

No route authenticates without authorising, or authorises after a tenant read.

## 10. Test quality

| Invariant | Happy path | Negative | Cross-tenant | Malformed | Concurrency | Fails if protection is removed? |
|---|---|---|---|---|---|---|
| HMAC (key, string, compare) | yes | yes | yes | yes | — | yes (sabotage 76, 76, 1) |
| Ed25519 and bot binding | yes | yes | yes | yes | — | yes (6, 73) |
| Parse injectivity (F1) | yes | yes | — | yes | — | yes (failed before the fix) |
| Freshness | yes | yes | — | yes | — | yes (2) |
| Replay | yes | yes | per tenant | — | yes (30 → 20; probe 25 → 1) | yes (3) |
| Generic 401 | — | yes | yes | yes | — | yes (5) |
| Tenant-bound sessions | yes | yes | yes | — | — | yes (50, including #15) |
| Credential separation | yes | yes | yes | — | — | OpenAPI sweep, structural |
| Bot RBAC | yes | yes | yes (F2) | yes | — | yes (F2 sabotage) |
| Forward-only DB guards | yes | yes | — | — | — | yes (failed before migration 0011) |
| Log redaction | — | yes | — | — | — | yes (1, 1) |
| `initDataUnsafe` absent | — | yes | — | — | — | yes (planted use, 1) |
| Identity and customer convergence | yes | — | yes | — | yes | race test |

**Weak spots.**
- The sabotage proofs patch source text, so they depend on exact strings. That makes them a one-time proof, not a CI gate.
- The tests that matter assert behaviour (status codes, reason logs, database rows), not implementation details.

## 11. Performance and DoS (no optimisation made)

- **Successful login.** About 13 statements in one transaction, plus three inserts and one audit row on a first login. It costs one envelope decryption, two HMACs and one Ed25519 verification.
- **Rejected login.** 4 statements, no writes, one decryption, at most two HMACs; Ed25519 is skipped without a valid HMAC.
- **Customer request.** About 7 statements; the session touch is at most one UPDATE per 30 s.
- **Replay contention.** Only identical `initData` contends, on one row. Pruning is per tenant and index-backed.
- **Attacker-controlled cost:**
  - a body of up to 1 MiB, parsed as JSON before the 4 KiB cap;
  - a token decryption per request at a host with a bot (F7).

All of this is bounded by B4.

## 12. Changes made in this audit

| File | Change |
|---|---|
| `backend/src/arada/telegram/miniapp.py` | F1: a decoded value containing `\n` is `malformed` |
| `scripts/telegram_sample_check.py` | Names the line-feed rule by field when the strict parse rejects |
| `backend/tests/unit/test_telegram_miniapp.py` | F1 unit regression |
| `backend/tests/security/test_telegram_auth.py` | F1 end-to-end regression (no victim identity is created) |
| `backend/tests/unit/test_telegram_sample_script.py` | Checker diagnostic case |
| `backend/tests/api/test_storefront_auth.py` | F2 RBAC test |
| Docs | this report; ADR-012 (implementation and history), register A8, `PHASE_2.md`, `21_IMPLEMENTATION_STATUS.md`, CLAUDE.md rule |

**Verification after the changes:**
- **Full suite:** 325 passed, 0 failed (321 before). Coverage is 91%; `miniapp.py` is at 98%.
- **Security suite:** 97 passed.
- **Static checks:** ruff and format clean; mypy (strict) clean on 124 files; lint-imports 5/5 kept.
- **Database:** PostgreSQL 16.14 in the agent sandbox; the stack and CI use PostgreSQL 17, not yet observed for these commits (§0.1).

## 13. Recommendation

**Accept the F1 fix as part of the Phase 2 candidate.** It removes an impersonation path whose exploitability depends on unverified Telegram behaviour. It changes nothing else, and it is covered by regression tests that failed before it. The other findings are LOW or INFORMATIONAL and need no code change now.

When the owner re-checks the docs (Gate 2), confirm in addition whether the official text states the allowed characters of `start_param`. That records whether F1 was ever exploitable; the fix stays either way.

**Status (see §0):**
- live Telegram test-environment sample (A8): **OPEN**;
- fresh official Telegram documentation verification: **OPEN**;
- **B4: AUTHENTICATION RATE LIMITING = REQUIRED BEFORE PUBLIC EXPOSURE** (F3 and F7 are inputs to it);
- Phase 3: **BLOCKED**;
- production exposure: **NOT APPROVED**;
- merge into `main`: **NOT AUTHORIZED**.

**Deferred:**
- the F9 proposal, for a separate decision on Phase 1;
- a metrics backend (F8);
- an upper bound on lifetime settings (F6);
- a structural pre-parse and a per-route body limit (F7, with B4).

Do not merge, and do not start Phase 3, until both gates pass and the final completion report is accepted.
