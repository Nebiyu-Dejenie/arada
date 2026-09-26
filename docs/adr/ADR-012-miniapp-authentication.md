# ADR-012: Mini App authentication: HMAC + Ed25519 signature + bot binding + freshness

| Field | Value |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-09-26 |

## Decision
The server validates `initData` with Telegram's documented HMAC-SHA256, **and** the Ed25519 `signature` field against Telegram's published public key, checks that `bot_id` equals the resolved tenant's bot, and enforces `auth_date` freshness. It then issues short-lived, tenant-bound tokens.

## Context
Never trust `initDataUnsafe` (Master §11; Permanent §11). HMAC alone can be forged by anyone who holds the bot token.

## Alternatives
HMAC-only validation.

## Reason
Closes impersonation by bot-token holders; ties each session to one merchant.

## Consequences
Telegram's public keys are environment configuration (production and test).
