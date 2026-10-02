# ADR-012: Mini App authentication: HMAC + Ed25519 signature + bot binding + freshness

| Field | Value |
|---|---|
| **Status** | **Accepted** (owner, 2026-10-01, Phase 2 implementation step 1). Specification verified against core.telegram.org on 2026-10-01; implemented in Phase 2 |
| **Date** | 2026-09-26 |

## Decision
The server validates `initData` with Telegram's documented HMAC-SHA256, **and** the Ed25519 `signature` field against Telegram's published public key, checks that `bot_id` equals the resolved tenant's bot, and enforces `auth_date` freshness. It then issues a session bound to that tenant and customer: opaque and server-side (ADR-036), not a JWT.

## Context
Never trust `initDataUnsafe` (Master §11; Permanent §11). HMAC alone can be forged by anyone who holds the bot token.

## Alternatives
HMAC-only validation.

## Reason
Closes impersonation by bot-token holders; ties each session to one merchant.

## Consequences
Telegram's public keys are environment configuration (production and test).

## Implementation (Phase 2, 2026-10-01)
- **Validator.** `backend/src/arada/telegram/miniapp.py` is pure: no database, network or application imports, enforced by an import-linter contract. It implements only the Mini App mechanism. The legacy Login Widget (`SHA256(token)` as the key) and Telegram Login (OIDC and JWT) are different mechanisms; tests prove that neither validates.
- **Order.** Strict parse, then HMAC, then Ed25519, then content and freshness. A forged request is therefore always counted as forged. Every failure is one generic `401 telegram-auth-failed`; the reason goes to logs only (owner decision D5).
- **Keys.** The verification key comes only from configuration (`telegram_environment`, `telegram_public_key_hex`). The code holds the SHA-256 **fingerprints** of Telegram's two documented keys (`kernel/config.py:TELEGRAM_KEY_FINGERPRINTS`), only to refuse mismatched configuration:
  - a known key must match `telegram_environment`;
  - production requires `telegram_environment = production` and Telegram's production key, so the test key is refused at startup;
  - staging, like production, accepts only a key Telegram publishes. A throwaway key, needed because Telegram publishes no private key for test vectors, is allowed only in the `development` and `test` environments (added 2026-10-02).

  A fingerprint cannot verify anything. If Telegram rotates its key, production fails closed until the docs are re-verified and the fingerprint is updated.
- **Bot id.** The platform admin supplies it (decision D6, assumption A9) and it is never parsed from the token. A wrong value fails closed.
- **Assumption A8 is an implementation assumption, not a Telegram-documented guarantee.** Form decoding and UTF-8 are implemented as written in `PHASE_2_PLAN.md` §5 row 5 and documented in the validator. So is the strict parse that goes with them: the raw string may contain only URL-safe characters and `%XX` escapes, and field names must match `[A-Za-z0-9_]{1,64}`. A decoded value may not contain a line feed, because that is the data-check-string separator and would give the signed string more than one parse (deep audit F1). Anything else fails closed. A8 is confirmed only by the owner's live test-environment sample (`scripts/telegram_sample_check.py`, never committed).

## Verified specification (2026-10-01)
Checked against the live official pages, never memory or copies. The full table and the page hashes are in `docs/reports/PHASE_2_PLAN.md` §5 and §14. Sources:
- <https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app>
- <https://core.telegram.org/bots/webapps#validating-data-for-third-party-use>
- <https://core.telegram.org/bots/webapps#webappinitdata>

| Rule | Verified detail |
|---|---|
| HMAC key | `HMAC_SHA256(key="WebAppData", msg=bot_token)`. Not the Login Widget's `SHA256(bot_token)`, which is a different mechanism |
| HMAC string | All received fields except `hash`, so it **includes `signature`** and any unknown field. Sorted alphabetically, `key=<value>`, separated by `\n`. `hash` is the hex HMAC, compared as decoded bytes (the docs don't state the letter case) |
| Ed25519 string | `<bot_id>:WebAppData\n` then all fields except `hash` and `signature`, sorted, `key=<value>`, separated by `\n`. `signature` is base64url (padding not specified, so both forms are accepted) |
| Public keys | One per environment, Telegram-wide. Test: `40055058a4ee38156a06562e52eece92a771bcd8346a8c4615cb7376eddf72ec`. Production: `e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d`. They are **configuration** and never in code |
| Bot binding | Through the `bot_id` in the Ed25519 string, and through the tenant's own token in the HMAC. **The docs do not state that the token prefix is the bot id**, so `bot_id` is registered explicitly (A9) |
| Freshness and replay | The docs define no maximum age and no replay mechanism, so both are our policy |
| Not stated | Whether values are percent-decoded before signing, and the byte encoding. Assumption A8 is decoded values over UTF-8 bytes, confirmed by the owner's live test-environment sample |

Requiring Ed25519 in addition to HMAC is **stricter than the documented minimum**. The docs frame Ed25519 for third parties, but list `signature` as a non-optional field.

## History
| Date | Change |
|---|---|
| 2026-09-26 | Proposed (Phase 0). |
| 2026-10-01 | **Accepted** by the owner and implemented in Phase 2 (see Implementation). |
| 2026-10-01 | B5 resolved. The specification was verified against core.telegram.org and the decision is confirmed. Corrections: `bot_id` is not derived from the token; `signature` padding is accepted either way; `hash` is compared as bytes; `signature` is included in the HMAC string. Ed25519 stays mandatory. The JWT and refresh-token wording in the Decision is superseded, once adopted, by ADR-036's opaque tenant-bound sessions (owner D4). |
| 2026-10-02 | Acceptance re-confirmed in the owner's Phase 2 implementation authorization. After an independent audit: a signed `auth_date` beyond year 9999 is `malformed` (it used to raise a 500), staging refuses throwaway keys, and A8 is labelled as an implementation assumption, together with its strict-parse rules. |
| 2026-10-02 | Deep audit F1 (HIGH, conditional): a decoded value containing `\n` let the holder of genuinely signed data move field boundaries without changing a signed byte, possibly making `user` someone else. Such values are now refused. The protocol reading and A8 decoding are unchanged (`docs/reports/PHASE_2_DEEP_AUDIT.md`). |
