# Phase 2 — Telegram foundation: design review and implementation plan

| Field | Value |
|---|---|
| **Status** | **Design APPROVED by the owner (2026-10-01) as the working plan, including its non-goals. Implementation BLOCKED by B5** until the official Telegram docs are verified. Nothing in this document is implemented. |
| **Date** | 2026-10-01 |
| **Baseline** | Phase 1 approved by the owner at `4896f60ad3d159e3a487e1aa56631ead0ed319ba` |
| **Inputs** | `04_TELEGRAM_ARCHITECTURE.md`, `02_TENANCY.md` §6, `17_API_CONTRACTS.md`, `19_ACCEPTANCE_TESTS.md`, ADR-011, ADR-012, ADR-017, ADR-024, ADR-029, ADR-034, ADR-035, register `20_DECISIONS.md` |

> **Verification gap (register B5).** This plan was written in an environment whose network policy blocks `core.telegram.org` and `telegram.org`, including archived copies. The Telegram behaviour below therefore comes from the repository's own record of the official docs (register K6 and K7, checked 2026-09-26; `04` §5), **not** from a fresh check. Every point marked **[verify]** must be confirmed against the official Mini Apps documentation before the validator is called conformant.

## 1. Current relevant architecture (as built in Phase 1)

| Concern | What exists | Where |
|---|---|---|
| Tenant from Host | `resolve_by_host`: Host → `control.resolve_storefront_host` (SECURITY DEFINER) → active tenant. **No route uses it yet.** | `tenancy/service.py`, migration 0009 |
| Tenant context | Transaction-local `app.tenant_id`, set by `Database.transaction(tenant_id=…)`; FORCE RLS on every `tenant_id` table, with a lint that fails CI otherwise | `kernel/db.py`, `tests/security/test_rls_coverage.py` |
| Identity | Global `persons`; `identities(provider, subject)` with `UNIQUE (provider, subject)`. `provider` already allows `'telegram'`. `arada_app` has SELECT and INSERT on identities | migration 0003 |
| Sessions | Staff-only, opaque tokens (SHA-256 stored), idle and absolute expiry, rotation on privilege change; **no tenant binding** | `identity/sessions.py`, ADR-029, ADR-035 |
| Authorisation | Scoped RBAC for platform, vertical and tenant staff. There is **no customer principal** | `rbac/`, `access/scopes.py` |
| Secrets | Envelope encryption (AES-256-GCM, versioned KEK) with AAD bound to `table|row|tenant|purpose` | `kernel/crypto.py`, ADR-017 |
| Correlation | `request_id` (always server-generated), W3C trace, and contextvars carried into every log line | `api/middleware.py`, `kernel/context.py` |
| Telegram | **Nothing.** No module, table, route or dependency | — |

## 2. Exact Phase 2 scope (the owner's ten items)

1. A Telegram integration boundary: a new `arada.telegram` module whose validator is pure (no DB, no HTTP), behind an import-linter contract.
2. Server-side `initData` validation: HMAC-SHA256, the Ed25519 `signature`, bot binding and freshness (ADR-012).
3. Telegram identity → `persons` and `identities('telegram', <user id>)` → a per-tenant `customers` row (ADR-024).
4. Merchant/bot/tenant resolution: Host → tenant (server-side) → **that tenant's** registered bot. A tenant has at most one active bot, and a Telegram bot belongs to exactly one tenant.
5. Authorisation **after** identity and tenant resolution: a customer principal with audience `customer`, a tenant-bound session, and no staff permissions.
6. Replay and expiry handling: maximum age, a future-skew bound, and a per-`initData` reuse window.
7. Separation of layers: authentication (`telegram`) → tenant resolution (`tenancy`) → identity mapping (`identity`) → authorisation (`access`) → business logic. Each layer is enforced by an import contract and tests.
8. Audit and correlation: request id and trace on every attempt, a machine reason code on every failure, and audit rows for customer and session creation and bot registration.
9. Negative tests: forged, malformed, expired, replayed, cross-tenant and unauthorised requests.
10. `initDataUnsafe` is never used: the endpoint accepts only the raw string, and a static test enforces it (AUTH-4).

Bot registration is included only as far as item 4 needs it: a platform-admin path to bind a **bring-your-own** bot (token sealed with ADR-017) to a tenant.

## 3. Explicit non-goals

The roadmap's Phase 2 row is broader than the owner's ten items. The following are **deferred to a later, separately approved Phase 2 increment** (or a later phase), not silently dropped:

- Webhook ingress and multiplexer, `ops.inbox`/outbox, the aiogram dispatcher, worker processes (AUTH-5).
- Any outbound Telegram call: `getMe`, `setWebhook`, commands, menu button, messages and notifications.
- Deep links and `start_param` resolution (ISO-8). `start_param` is accepted inside a valid `initData` but is never interpreted or trusted.
- Managed bots and the Factory bot (U6 is unverified), and the ops bot.
- The Mini App frontend, React, the manifest and the theme.
- Redis, Kafka, Kubernetes, OpenSearch, microservices, and any new infrastructure.
- Commerce beyond the minimal `customers` row, payments, Merchant Factory, and new verticals.
- **Authentication rate limiting (B4).** It stays **REQUIRED BEFORE PUBLIC EXPOSURE**. Phase 2 must not be described as production-ready while it is missing.
- Deployment, DNS, Cloudflare, real or production bot tokens, and production Telegram keys.

## 4. Dependencies

| Dependency | Status |
|---|---|
| Official Mini Apps docs (algorithm, key values, field list) | **BLOCKED in this environment (B5)**: `core.telegram.org` is denied by network policy |
| Ed25519 and HMAC | `cryptography` 50 (already a dependency) and the standard library. **No new package** |
| Telegram public keys (production and test) | Configuration only (ADR-012). Never hard-coded; validated as 32-byte hex at startup; required in production |
| Bot ownership (U5) | Proposed assumption A7: **bring-your-own, merchant-owned bots** for Phase 2 (`04` §2b baseline). Managed bots wait for U6 |
| Live conformance | One `initData` sample from a **test** bot in Telegram's **test** environment, checked locally by the owner. Never committed: it contains personal data and the repository is public |

## 5. Telegram behaviour this design relies on

All of these points are taken from K7 and `04` §5, and every one is marked **[verify]**:

- The secret key is `HMAC_SHA256(key="WebAppData", msg=bot_token)`. The data-check-string is every field except `hash`, sorted by key, formatted `key=value` and joined with `\n`; `hash` is the lowercase hex HMAC of it.
- Whether the values in the data-check-string are the **URL-decoded** values.
- The Ed25519 data-check-string is `"<bot_id>:WebAppData\n"` followed by every field except `hash` and `signature`, sorted and joined the same way. `signature` is base64url without padding.
- The production and test public key values, which go to configuration.
- That the bot id equals the numeric prefix of the bot token, `<bot_id>:<secret>`.
- The `WebAppUser` fields used here: `id`, `first_name`, `last_name`, `language_code`, `is_bot`, and whether `is_bot` can appear in Mini App data.
- That Telegram defines no maximum age for `auth_date`, so the maximum age is our policy.

## 6. Security boundaries

```
Client (untrusted)                       Server
 raw initData ──► POST /v1/storefront/auth/telegram
                  Host ──► tenancy.resolve_by_host ──► tenant (or 404)
                  tenant context ──► control.telegram_bots (RLS) ──► bot_id + sealed token
                  telegram.verify_init_data(raw, bot_id, token, keys, now)  ← pure; no I/O
                  replay check (RLS table)
                  identity.find_or_create_telegram_person(user_id)  ← no tenant input
                  customers.find_or_create(tenant, person)          ← tenant context
                  customer_sessions.issue(tenant, customer)         ← tenant context
```

- **The tenant always comes from Host.** No `tenant_id` from the client is read anywhere. A spoofed Host only chooses which tenant's bot the data must verify against, so it gains nothing.
- **Bot binding is cryptographic.** The HMAC uses the resolved tenant's own token, and the Ed25519 string embeds the resolved tenant's own `bot_id`. Tenant A's `initData` therefore fails verification at tenant B's host.
- **The Ed25519 signature is mandatory.** A BYO merchant, or anyone who leaks a token, can forge HMAC-valid data for any Telegram user. Only Telegram can produce the signature.
- **One generic answer to the client.** Every validation failure returns the same `401 urn:arada:problem:telegram-auth-failed`. The specific reason code (`malformed`, `bad_hash`, `bad_signature`, `stale`, `future`, `replayed`, `no_bot`, `bot_inactive`, `user_rejected`) goes to logs and a low-cardinality metric only. **This changes acceptance tests ISO-4 and AUTH-1…3,** which currently expect the reason in the response.
- **Customer and staff credentials are disjoint.** They live in separate tables, use separate dependencies and never overlap. A customer token is never accepted by staff, platform or tenant-console routes, and a staff token is never accepted by storefront routes.
- **Customer sessions are bound to their tenant by the database.** `customer_sessions` is under FORCE RLS and is looked up only inside the Host-resolved tenant's context, so tenant A's token is invisible at tenant B's host.
- **Bot tokens are never exposed.** They are sealed with AAD `telegram_bots|<row>|<tenant>|bot_token`, decrypted only in memory for the HMAC check, never returned, logged or put in an error, and covered by a log-redaction test.
- **Raw `initData` is never logged or stored.** Only a SHA-256 digest of its `hash` is stored, for replay control.
- **Input limits.** The body limit already applies. `init_data` is capped at 4 KiB; duplicate keys, non-UTF-8 and invalid percent-encoding are rejected; `auth_date` must be an integer; and `user` must be a JSON object with an integer `id`.

## 7. Database changes (migration 0010; raw SQL, FORCE RLS, composite FKs)

| Table | Purpose | Key constraints | `arada_app` grants |
|---|---|---|---|
| `control.telegram_bots` | BYO bot bound to a tenant | `UNIQUE (telegram_bot_id)`; one `active` per tenant (partial unique); sealed-token columns as in `totp_factors`; status `active` or `disabled` | SELECT, INSERT, UPDATE(status, disabled_at) |
| `commerce.customers` (new schema `commerce`) | A person as seen by one tenant (ADR-024, `02` §6). Minimal columns only: `tenant_id, id, person_id, first_seen_at` | `UNIQUE (tenant_id, person_id)`; `UNIQUE (tenant_id, id)` | SELECT, INSERT |
| `control.customer_sessions` | Opaque, tenant-bound customer sessions | `UNIQUE (token_hash)`; FK `(tenant_id, customer_id)` → customers | SELECT, INSERT, UPDATE(last_seen_at, idle_expires_at, revoked_at, revoked_reason) |
| `control.telegram_init_data_uses` | Replay window per `initData` | PK `(tenant_id, hash_digest)`; `first_used_at`, `use_count`, `expires_at` | SELECT, INSERT, UPDATE(use_count), DELETE (expired rows only, by policy) |

All four tables carry `tenant_id`, so the RLS lint and the per-table SQL isolation suite (`TENANT_TABLES`) cover them automatically. Each must be added to the isolation tests and to the platform-reader allow-list review. `identities` needs no change. The downgrade drops everything in reverse.

## 8. API changes

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/v1/storefront/auth/telegram` | none (Host-resolved tenant) | Body `{"init_data": "<raw string>"}` → `{access_token, expires_at}`. Unknown host → 404; any validation failure → generic 401 |
| GET | `/v1/storefront/me` | customer token on the same host | Returns the caller's own customer record only. It is the one protected endpoint that proves the whole chain end to end |
| POST | `/v1/storefront/auth/logout` | customer token | Revokes the session |
| PUT | `/v1/platform/tenants/{tenant_id}/telegram-bot` | staff, `bots.manage` (MFA-gated platform scope) | Body `{bot_token}`. Binds or replaces the BYO bot; stores `telegram_bot_id` from the token prefix [verify]; audited; never echoes the token. Replacing a bot revokes the tenant's customer sessions |
| GET / DELETE | same path | staff, `bots.manage` | Status (id, username if known, status) / disable |

**Deviation from `04` §5 and `17` (proposed ADR-036).** These are opaque, server-stored, tenant-bound customer sessions (idle 30 min, absolute 12 h, configurable), **not** an EdDSA JWT plus refresh handle. The reasons:
- They reuse the reviewed ADR-029 and ADR-035 session mechanics.
- They are revocable immediately.
- Their tenant binding is enforced by RLS rather than by a claim.
- There is no signing key to manage.
- The paths use the existing `/v1` prefix, not `/api/v1`.

All new routes enter the ADR-032 OpenAPI security sweep. New tenant-scoped routes get `SAMPLE_BODIES` entries.

## 9. Validation and replay policy

1. **Parse strictly.** A missing `hash`, `signature`, `auth_date` or `user`, a duplicate key, or a bad encoding gives `malformed`.
2. **HMAC.** Compare in constant time with the tenant's token; failure gives `bad_hash`.
3. **Ed25519.** Verify with the configured key and the tenant's `bot_id`; failure gives `bad_signature`.
4. **Freshness.** `auth_date` must be no older than `TELEGRAM_INIT_DATA_MAX_AGE` (default 1 h), otherwise `stale`. It must be no more than 60 s in the future, otherwise `future`.
5. **Replay.** The first use of a given `hash` records the use. Later bootstraps are allowed only within `TELEGRAM_INIT_DATA_REUSE_WINDOW` (default 10 min) of that first use (Mini App reloads) and only up to `TELEGRAM_INIT_DATA_MAX_USES` (default 20); otherwise `replayed`. Concurrent first uses are settled by the primary key (`INSERT … ON CONFLICT`). Expired rows are pruned opportunistically on insert, so there is no scheduler.
6. **User checks.** A `user.is_bot` that is true, or a disabled person, gives `user_rejected`.

Crypto runs before freshness so a stale but forged request is counted as forged. The client sees the same answer either way.

## 10. Tests required

**Unit (validator; vectors are generated in-test with a throwaway Ed25519 key pair and a fake token):**
- A valid vector passes.
- A tampered `user`, `auth_date` or `start_param` fails.
- Missing or duplicate `hash` or `signature` fails.
- An HMAC-valid but unsigned vector fails (the forged-with-token case, AUTH-2).
- A vector signed with another `bot_id`, or HMAC'd with another token, fails.
- A signature from the test key is rejected under the production key.
- Stale and future `auth_date` fail, and so does a non-integer one.
- Oversized input, bad percent-encoding and non-UTF-8 fail.
- Extra unknown fields stay covered by the hash.
- Hash case and padding variants behave as specified.

**Integration (real PostgreSQL):**
- Concurrent first logins of one Telegram user create one person and one identity.
- One person in tenants A and B gets two distinct customer rows, with no cross-visibility.
- The replay window and use counter hold under concurrency.
- Bot replacement revokes sessions.
- RLS lint and SQL isolation pass for all four new tables.
- The SECURITY DEFINER and reader allow-lists are unchanged or explicitly extended.

**API and security (negative):**
- Forged, malformed, expired, future, replayed, unsigned and tampered requests get a generic 401 with the right logged reason.
- Tenant A's `initData` at B's host gets 401 (ISO-4).
- An unknown host gets 404.
- A suspended or archived tenant, a tenant with no bot, and a disabled bot get 401 or 404.
- Tenant A's customer token at B's host gets 401.
- A customer token on every staff, platform and tenant-console route gets 401 or 403. This is an OpenAPI-driven sweep.
- A staff token on storefront routes gets 401.
- A logged-out or expired customer session is refused immediately.
- Bot registration without `bots.manage`, or without MFA, gets 403.
- The bot token never appears in any response, log line or audit row.
- Raw `initData` never appears in logs (log capture).
- AUTH-4: a static test fails if `initDataUnsafe` appears in `backend/src`.

**Process:**
- Each new suite is shown to fail against a sabotaged implementation, as in Phase 1.
- The full gates run: ruff, mypy, lint-imports, pytest with coverage, pip-audit and CI.

## 11. Risks

| Risk | Mitigation or status |
|---|---|
| Algorithm or key details differ from current Telegram docs | **B5**: verify before calling it conformant; the owner checks a live test-environment sample; keys are configuration |
| Captured `initData` is replayed within its window | The short reuse window and use cap; sessions are tenant-bound; TLS in transit; no logging |
| The unauthenticated endpoint creates persons and customers | Only after HMAC **and** a Telegram signature, so an attacker needs real Telegram accounts. **B4 rate limiting is still required before exposure** |
| A BYO bot token leaks | The Ed25519 requirement blocks impersonation. Replacement revokes sessions. Rotation is a merchant task |
| Clock skew | A 60 s future tolerance; host NTP is an ops requirement |
| Privacy of Telegram data | Only the user id (as an identity subject) and a display name are stored. Username, photo and phone are not. Merchants see only their own customer rows |
| `customers` is the first `commerce` table | Kept minimal; Phase 3 extends it through a new migration |
| Host header trust in production | Depends on the tunnel and Traefik config (Phase 1 design); not deployed in Phase 2 |

## 12. Implementation order (after approval)

1. ADR-036 (customer sessions); ADR-012 to Accepted; register A7 (U5) and B5; `04`, `17` and `19` text updates.
2. Migration 0010 and table mirrors, with the RLS lint and SQL isolation tests for the new tables.
3. `arada.telegram.init_data` (the pure validator) with unit tests, sabotage proof and an import contract.
4. Bot registration (platform, `bots.manage`): sealing, audit and tests.
5. Identity mapping, customers and customer sessions, with integration tests including races.
6. Storefront routes and the customer-auth dependency, with the separation sweep.
7. The replay window, then logging, metrics and audit with redaction tests.
8. Security inventory updates (ADR-032), the AUTH-4 static check, and the full gates.
9. `docs/reports/PHASE_2.md` with evidence per claim; `21_IMPLEMENTATION_STATUS.md` updated.

## 13. Owner decisions (2026-10-01)

| # | Decision | Outcome |
|---|---|---|
| D1 | Plan and non-goals | **Approved** as the working plan |
| D2 | Telegram documentation | **Fresh verification against core.telegram.org required.** Memory, tutorials, archives, blogs, framework code and the repository's own record (K7) are **not** acceptable substitutes. Still blocked (B5): access was re-checked on 2026-10-01 and the network policy still denies the host |
| D3 | Bot ownership (U5) | **Approved:** merchant-owned, bring-your-own bots for Phase 2 |
| D4 | Customer sessions | **Approved in principle:** opaque, server-side sessions tied to one tenant and one customer, subject to the final ADR-036 review. ADR-036 becomes authoritative over the JWT and refresh-handle text in `04` §5 and `17` once adopted |
| D5 | Failure responses | **Approved:** generic 401 to the client. Reason categories go to controlled logs and metrics only. Raw `initData`, tokens, secrets and sensitive personal data are never logged |

Also approved: the tenant is derived server-side from the merchant host; a client-supplied tenant is never an authorisation boundary; the layers stay separate; customer authentication grants no business authorisation by itself; and every customer session lookup and resource access is tenant-scoped server-side.

**Next step:** once `core.telegram.org` is reachable, verify §5 point by point, record the official URLs and sections, update this plan and ADR-012, and report before writing any code.
