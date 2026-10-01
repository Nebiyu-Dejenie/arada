# Phase 2 — Telegram foundation: design review and implementation plan

| Field | Value |
|---|---|
| **Status** | **Design APPROVED by the owner (2026-10-01) as the working plan, including its non-goals.** B5 (documentation verification) was **completed on 2026-10-01** against core.telegram.org (§14). The verified specification confirms the design without architectural change; four details are corrected (§5). **No code is written yet:** implementation starts only after the owner has received the verification report. |
| **Date** | 2026-10-01 |
| **Baseline** | Phase 1 approved by the owner at `4896f60ad3d159e3a487e1aa56631ead0ed319ba` |
| **Inputs** | `04_TELEGRAM_ARCHITECTURE.md`, `02_TENANCY.md` §6, `17_API_CONTRACTS.md`, `19_ACCEPTANCE_TESTS.md`, ADR-011, ADR-012, ADR-017, ADR-024, ADR-029, ADR-034, ADR-035, register `20_DECISIONS.md` |

> **Verification (register B5, resolved 2026-10-01).** This plan was first written in a cloud environment whose network policy blocked `core.telegram.org`. The Telegram behaviour in §5 was then **verified directly against the live official pages on core.telegram.org**, fetched over verified TLS from the developer workstation on 2026-10-01 at 13:26 UTC (§14). No memory, tutorial, archive, blog, framework code or repository record was used as the specification. Where the official text is silent, §5 says so and records the implementation assumption. Those points are confirmed only by the live test-environment sample (§4).

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
| Official Mini Apps docs (algorithm, key values, field list) | **Verified 2026-10-01** (B5 resolved; §5, §14) |
| Ed25519 and HMAC | `cryptography` 50 (already a dependency) and the standard library. **No new package** |
| Telegram public keys (production and test) | Configuration only (ADR-012). Never hard-coded; validated as 32-byte hex at startup; required in production |
| Bot ownership (U5) | Proposed assumption A7: **bring-your-own, merchant-owned bots** for Phase 2 (`04` §2b baseline). Managed bots wait for U6 |
| Live conformance | One `initData` sample from a **test** bot in Telegram's **test** environment, checked locally by the owner. Never committed: it contains personal data and the repository is public |

## 5. Telegram behaviour this design relies on (verified 2026-10-01)

**Sources** (full record in §14):
- **[MA-V]** <https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app>
- **[MA-3P]** `…/bots/webapps#validating-data-for-third-party-use`
- **[MA-ID]** `…#webappinitdata`
- **[MA-U]** `…#webappuser`
- **[MA-I]** `…#initializing-mini-apps`
- **[MA-T]** `…#using-bots-in-the-test-environment`
- **[API]** <https://core.telegram.org/bots/api#authorizing-your-bot> and `#getme`
- **[LW]** <https://core.telegram.org/widgets/login-legacy#checking-authorization>
- **[TL]** <https://core.telegram.org/bots/telegram-login#validating-id-tokens>. `/widgets/login` now redirects here.

**Status labels:**
- **VERIFIED:** the official text states it.
- **VERIFIED (implied):** it follows necessarily from the official text.
- **NOT STATED:** the official text is silent, so the implementation assumption is recorded and the live test sample confirms it.
- **NOT DOCUMENTED:** the plan's assumption has no official basis and is replaced.

| # | Point | Official text (abridged; quotes are verbatim) | Status | Design consequence |
|---|---|---|---|---|
| 1 | Input | Send "the data from the *Telegram.WebApp.initData* field to the bot's backend. The data is a query string, which is composed of a series of field-value pairs" [MA-V]. `initDataUnsafe`: "WARNING: Data from this field should not be trusted. You should only use data from initData on the bot's server and only after it has been validated" [MA-I] | VERIFIED | Unchanged: raw string only; AUTH-4 |
| 2 | HMAC secret key | "the secret key, which is the HMAC-SHA-256 signature of the bot's token with the constant string `WebAppData` used as a key" [MA-V] | VERIFIED | `secret_key = HMAC_SHA256(key=b"WebAppData", msg=bot_token)` |
| 3 | HMAC check | "comparing the received *hash* parameter with the hexadecimal representation of the HMAC-SHA-256 signature of the **data-check-string** with the secret key" [MA-V] | VERIFIED | `hash` must equal `HMAC_SHA256(key=secret_key, msg=dcs)` in hex. **Letter case is not stated**, so decode `hash` as exactly 64 hex characters and compare the 32 bytes in constant time |
| 4 | HMAC data-check-string | "a chain of all received fields, sorted alphabetically, in the format `key=<value>` with a line feed character (0x0A) used as separator". `hash` is "a hash of all passed parameters" [MA-V, MA-ID] | VERIFIED; exclusion of `hash` **VERIFIED (implied)** | Every received field **except `hash`**, **including `signature`** and any field unknown to us (Bot API 10.1 added `chat_join_request_query_id` in June 2026), sorted by key in code-point order, joined with `\n`. The parser must never drop unrecognised fields |
| 5 | Value form | The data is a query string. The data-check-string uses `key=<value>`; "Complex data types are represented as JSON-serialized objects" [MA-V] | **NOT STATED** whether values are percent-decoded, how `+` is treated, or the byte encoding | **Assumption A8:** decode the query string once, strictly; use the decoded values verbatim (not re-serialised JSON); compute HMAC and Ed25519 over the **UTF-8** bytes. Confirm with the live sample, including a non-ASCII (Amharic) display name and a name containing a space |
| 6 | Ed25519 | "the received *signature* parameter, which is the base64url-encoded representation of the Ed25519 signature of the **data-check-string**. The verification is performed using the public key provided by Telegram" [MA-3P] | VERIFIED | Ed25519 verify with the configured Telegram key. **Padding is not stated**, so accept base64url with or without `=` padding, reject any other alphabet, and require exactly 64 decoded bytes. *Corrects §5 of the first draft*, which said "without padding" |
| 7 | Ed25519 data-check-string | "1. Prepend the *bot_id*, followed by `:` and the constant string `WebAppData`. 2. Add a line feed character (0x0A). 3. Append all received fields (except *hash* and *signature*), sorted alphabetically, in the format `key=<value>`. 4. Separate each key-value pair with a line feed character (0x0A)." Example: `'12345678:WebAppData\nauth_date=<auth_date>\nquery_id=<query_id>\nuser=<user>'` [MA-3P] | VERIFIED | `f"{bot_id}:WebAppData\n" + "\n".join(sorted k=v, excluding hash and signature)` |
| 8 | Public keys | "Test environment: `40055058a4ee38156a06562e52eece92a771bcd8346a8c4615cb7376eddf72ec` (hex). Production: `e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d` (hex)" [MA-3P] | VERIFIED (public values) | Configuration, not code. One environment per deployment (`telegram_environment`: `production` or `test`). Production settings refuse the test key. The test environment "is completely separate from the main environment", with its own user accounts and bots [MA-T] |
| 9 | Public key and bot relationship | The keys are Telegram-wide, one per environment, not per bot. The bot is bound by the *bot_id* inside the signed string: give the third party "the data … and your *bot_id*" [MA-3P] | VERIFIED | Unchanged: the resolved tenant's `bot_id` goes into the signed string, and HMAC uses that tenant's token |
| 10 | bot_id versus the token | Tokens are shown only by example ("looks something like `123456:ABC-…`", an illustrative value) [API]. A bot's identity is returned by `getMe` as a `User` object [API] | **NOT DOCUMENTED** that the numeric prefix is the bot id | **Changed:** never derive `bot_id` from the token. The platform admin supplies `bot_id` explicitly when registering a bot (assumption A9; the alternative, calling `getMe`, is an outbound call and a Phase 2 non-goal). A wrong `bot_id` fails closed: the Ed25519 check rejects every login, and no forged data is accepted |
| 11 | Fields | `auth_date` (Integer, "Unix time when the form was opened"), `hash` and `signature` ("A signature of all passed parameters (except hash)") are listed **without** "Optional". `user` is **Optional** [MA-ID] | VERIFIED | `hash`, `signature` and `auth_date` are required. A missing `user` gives `malformed` (there is no one to authenticate) |
| 12 | User fields | `id`: "at most 52 significant bits". `first_name` is required. `last_name`, `username`, `language_code` and `photo_url` are optional. **`is_bot`: "Returns in the receiver field only"** [MA-U] | VERIFIED | Accept `id` only as a positive integer < 2^53, stored as the identity subject (text). *Corrects the draft:* `is_bot` never appears in `user`. A `true` there is treated as `malformed` (defensive), not as a documented case. `receiver` and `chat` are never used for identity |
| 13 | Freshness | "To prevent the use of outdated data, you can additionally check the *auth_date* field" [MA-V]; a third party "should additionally validate" it [MA-3P]. **No maximum age is defined** | VERIFIED | The maximum age (1 h) and future skew (60 s) are **our policy**, as planned |
| 14 | Replay | The official text documents only `auth_date` freshness. `query_id` is optional and exists for `answerWebAppQuery`; it is not a nonce [MA-ID] | VERIFIED (absence) | The reuse window and use cap in §9 are **our policy**; `query_id` is not used for replay control |
| 15 | Launch modes | WebAppInitData "is empty if the Mini App was launched from a keyboard button or from inline mode" [MA-ID] | VERIFIED | Storefront login works only for launches that carry `initData`: menu button, main Mini App, inline button, direct link, attachment menu. Keyboard-button and inline-mode launches get the generic 401. This constrains the later bot-configuration work (a non-goal here) |
| 16 | Other Telegram mechanisms | Legacy Login Widget: `secret_key = SHA256(<bot_token>)` [LW]. New Telegram Login: OpenID Connect, an authorization-code flow (PKCE), and an `id_token` JWT validated against JWKS with `iss = https://oauth.telegram.org` and `aud` = Bot ID [TL] | VERIFIED | **Different derivations; never mix them.** The validator implements only the Mini App algorithm (key `WebAppData`). The JWKS and OIDC flows are for web and app login, not Mini Apps, and are out of scope. A future web storefront login would be a separate ADR |
| 17 | Test vectors | The official pages publish **no** test vectors; the examples are placeholders | VERIFIED (absence) | Unit vectors are generated in-test (throwaway Ed25519 key, fake token). They prove our logic matches *our reading*. **Conformance with Telegram is proven only by the live test-environment sample** (§4), which is never committed |

**Ed25519 is required for every login.** The official text frames it for third-party use and makes HMAC sufficient for the bot's own backend. Requiring both is **stricter** than the documented minimum, which the official text permits. It closes forgery by anyone holding the token (a BYO merchant, or a leaked token). Because `signature` is not marked optional, every conforming client sends it.

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
- **Input limits.** The body limit already applies. `init_data` is capped at 4 KiB. Duplicate keys, non-UTF-8 and invalid percent-encoding are rejected. `auth_date` must be an integer. `user` must be a JSON object with an integer `id` (0 < id < 2^53) and a `first_name`. `hash` must be exactly 64 hex characters. `signature` must be base64url (padding optional) that decodes to exactly 64 bytes (§5 rows 3, 6, 12).

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
| PUT | `/v1/platform/tenants/{tenant_id}/telegram-bot` | staff, `bots.manage` (MFA-gated platform scope) | Body `{bot_id, bot_token}`. Binds or replaces the BYO bot. **`bot_id` is supplied explicitly** (a positive integer), because the official docs do not state that the token prefix is the bot id (§5 row 10, A9). Audited; never echoes the token. Replacing a bot revokes the tenant's customer sessions |
| GET / DELETE | same path | staff, `bots.manage` | Status (id, username if known, status) / disable |

**Deviation from `04` §5 and `17` (proposed ADR-036).** These are opaque, server-stored, tenant-bound customer sessions (idle 30 min, absolute 12 h, configurable), **not** an EdDSA JWT plus refresh handle. The reasons:
- They reuse the reviewed ADR-029 and ADR-035 session mechanics.
- They are revocable immediately.
- Their tenant binding is enforced by RLS rather than by a claim.
- There is no signing key to manage.
- The paths use the existing `/v1` prefix, not `/api/v1`.

All new routes enter the ADR-032 OpenAPI security sweep. New tenant-scoped routes get `SAMPLE_BODIES` entries.

## 9. Validation and replay policy

1. **Parse strictly.** Any of these gives `malformed`:
   - a missing `hash`, `signature`, `auth_date` or `user`, which includes the empty `initData` of keyboard-button and inline-mode launches (§5 row 15);
   - a duplicate key or a bad encoding;
   - a malformed `hash` or `signature`.

   Every received field is kept, known or not, for the data-check-strings (§5 row 4).
2. **HMAC.** Build the data-check-string from every field except `hash` (so `signature` is included), compute it with the tenant's token, and compare the 32 decoded bytes in constant time. Failure gives `bad_hash`.
3. **Ed25519.** Build the string as `<bot_id>:WebAppData\n` plus every field except `hash` and `signature`, then verify it with the deployment's configured key and the tenant's registered `bot_id`. Failure gives `bad_signature`.
4. **Freshness.** `auth_date` must be no older than `TELEGRAM_INIT_DATA_MAX_AGE` (default 1 h), otherwise `stale`. It must be no more than 60 s in the future, otherwise `future`.
5. **Replay.** The first use of a given `hash` records the use. Later bootstraps are allowed only within `TELEGRAM_INIT_DATA_REUSE_WINDOW` (default 10 min) of that first use (Mini App reloads) and only up to `TELEGRAM_INIT_DATA_MAX_USES` (default 20); otherwise `replayed`. Concurrent first uses are settled by the primary key (`INSERT … ON CONFLICT`). Expired rows are pruned opportunistically on insert, so there is no scheduler.
6. **User checks.** A disabled person gives `user_rejected`. A `user.is_bot` that is true is treated as `malformed`: the docs say `is_bot` appears only in `receiver` (§5 row 12). Only `user` is ever used for identity, never `receiver` or `chat`.

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
- Extra unknown fields stay covered by the hash. A vector containing `chat_join_request_query_id` (added in Bot API 10.1) is validated without code changes.
- Removing `signature` from the HMAC string breaks the HMAC (it is covered), and including it in the Ed25519 string breaks the signature.
- Upper- and lower-case `hash` both verify; a 63- or 65-character `hash` fails.
- `signature` with and without `=` padding verifies; a standard-alphabet (`+` or `/`) or 63-byte signature fails.
- Non-ASCII values (an Amharic `first_name`) and values containing a space or a `+`: the encoding assumption (A8) is checked against our own reading and **confirmed only by the live sample**.
- A missing `user`, empty `initData`, and a `user.id` of 2^53 or more fail.
- The Login Widget derivation (`SHA256(token)` as the key) never validates Mini App data (§5 row 16).

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
| Algorithm or key details differ from current Telegram docs | **B5 resolved:** verified against core.telegram.org on 2026-10-01 (§5, §14). The NOT STATED points (value decoding, UTF-8, hex case, padding) are confirmed only by the owner's live test-environment sample. Keys are configuration. Re-check the docs before Phase 2 is declared complete, because the page changes often (four Mini App updates in 2026) |
| Captured `initData` is replayed within its window | The short reuse window and use cap; sessions are tenant-bound; TLS in transit; no logging |
| The unauthenticated endpoint creates persons and customers | Only after HMAC **and** a Telegram signature, so an attacker needs real Telegram accounts. **B4 rate limiting is still required before exposure** |
| A BYO bot token leaks | The Ed25519 requirement blocks impersonation. Replacement revokes sessions. Rotation is a merchant task |
| A merchant revokes or regenerates the token in @BotFather (the docs say a token "can also be revoked at any time") | The HMAC no longer matches, so logins fail closed with the generic 401 until the platform admin re-registers the bot. Existing customer sessions are unaffected until they expire, or are revoked by re-registration |
| Clock skew | A 60 s future tolerance; host NTP is an ops requirement |
| Privacy of Telegram data | Only the user id (as an identity subject) and a display name are stored. Username, photo and phone are not. Merchants see only their own customer rows |
| `customers` is the first `commerce` table | Kept minimal; Phase 3 extends it through a new migration |
| Host header trust in production | Depends on the tunnel and Traefik config (Phase 1 design); not deployed in Phase 2 |

## 12. Implementation order (after approval)

1. ADR-036 (customer sessions); ADR-012 to Accepted; register A7 (U5), A8 and A9 (B5 is already resolved); `04`, `17` and `19` text updates. Add configuration for `telegram_environment` (`production` or `test`) and the matching Ed25519 public key, validated as 32-byte hex at startup; production refuses the test key.
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
| D2 | Telegram documentation | **Fresh verification against core.telegram.org required.** Memory, tutorials, archives, blogs, framework code and the repository's own record (K7) are **not** acceptable substitutes. **Done 2026-10-01** from the developer workstation (§5, §14); B5 resolved |
| D6 | Source of `bot_id` | **Proposed default (A9): the admin supplies `bot_id` with the token**, because the docs do not state that the token prefix is the bot id (§5 row 10). The alternative, calling `getMe` at registration, is an outbound Telegram call, which is a Phase 2 non-goal, so it would need owner approval. Either way, a wrong `bot_id` fails closed |
| D3 | Bot ownership (U5) | **Approved:** merchant-owned, bring-your-own bots for Phase 2 |
| D4 | Customer sessions | **Approved in principle:** opaque, server-side sessions tied to one tenant and one customer, subject to the final ADR-036 review. ADR-036 becomes authoritative over the JWT and refresh-handle text in `04` §5 and `17` once adopted |
| D5 | Failure responses | **Approved:** generic 401 to the client. Reason categories go to controlled logs and metrics only. Raw `initData`, tokens, secrets and sensitive personal data are never logged |

Also approved: the tenant is derived server-side from the merchant host; a client-supplied tenant is never an authorisation boundary; the layers stay separate; customer authentication grants no business authorisation by itself; and every customer session lookup and resource access is tenant-scoped server-side.

**Next step:** the verification report has gone to the owner. Implementation (§12) starts after that, with D6 defaulting to A9 unless the owner decides otherwise. The live test-environment sample (§4) is the conformance check for the NOT STATED points in §5. Nothing is production-ready while B4 is open.

## 14. Verification record (B5)

- **When and how.** 2026-10-01, 13:26 UTC. Pages were fetched with `curl` over TLS, checking the certificate (`CN=*.telegram.org`, issued by GoDaddy, valid until 2027-03-11; the server was 149.154.167.99), then read in full as HTML. No cached, archived, third-party or repository copy was used. **No copy of the pages is stored in the repository**: only the URLs, the anchors used and the SHA-256 of what was read, so a later reader can tell whether a page has changed.
- **No secrets or personal data.** Nothing was sent to Telegram; no bot token, `initData` or account was used.

| Page (official URL) | Sections used | SHA-256 of the HTML read |
|---|---|---|
| <https://core.telegram.org/bots/webapps> (title "Telegram Mini Apps"; latest change entry "June 11, 2026, Bot API 10.1") | `#validating-data-received-via-the-mini-app`, `#validating-data-for-third-party-use`, `#webappinitdata`, `#webappuser`, `#initializing-mini-apps` (`initData` and `initDataUnsafe` rows), launch-mode sections (`#keyboard-button-mini-apps` … `#launching-mini-apps-from-the-attachment-menu`), `#using-bots-in-the-test-environment`, `#recent-changes` | `fa48a6f43201d198c66b174b5b2b0d0f8716c85cda242b3cd9eeae63ba5eb457` |
| <https://core.telegram.org/bots/api> | `#authorizing-your-bot` (token format, by example only), `#getme` | `8cebefd685630192d9921e951b08610e34be4676b0e1b1a9b51abc4b81c43037` |
| <https://core.telegram.org/bots/features> | `#botfather` (token generation; token shown by example only) | `238b0c19aa383c795fe5e86a562a7fedb80f57b45fde2c2dd8e5c3cb565de196` |
| <https://core.telegram.org/bots/tutorial> | `#obtain-your-bot-token` (linked from the validation text) | `da4f395649996fe260d25258c25a1d06406fa79aec946c70c183c94ef4197321` |
| <https://core.telegram.org/widgets/login-legacy> | `#checking-authorization` (legacy widget derivation) | `e4b2690ee928b180884e93f4e1a762a5d3e669b408644e5a31194e3a01f71ba2` |
| <https://core.telegram.org/widgets/login> → redirects to <https://core.telegram.org/bots/telegram-login> | `#openid-connect`, `#validating-id-tokens`, `#signing-algorithm` | `ece1bb32541f669d68880e93e30000cd0037b442f07c42b612445b73f143bf75` |

These pages are updated often. Re-verify before the Phase 2 completion report and whenever a Bot API release note touches Mini Apps.

