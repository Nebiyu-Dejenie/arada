# ADR-011: Telegram bot provisioning: managed bots with a BYO-token fallback

| Field | Value |
|---|---|
| **Status** | Proposed — Telegram capability limits must be verified before Phase 2 (Permanent §12, §58) |
| **Date** | 2026-09-26 |

## Decision
A platform Factory bot with bot management enabled in @BotFather asks the merchant owner to create a managed bot (`KeyboardButtonRequestManagedBot`); the platform fetches its token via `getManagedBotToken` and rotates it via `replaceManagedBotToken`. The fallback is the merchant creating a bot in @BotFather and submitting its token. One multiplexed webhook endpoint serves all bots.

## Context
Merchants need their own bot identity. Telegram documents managed bots in the Bot API (added in 9.6). Creation still requires a human tap by the merchant; nothing is created 'magically'.

## Alternatives
BYO tokens only; one shared bot for all merchants.

## Reason
Supported, automated token lifecycle with real merchant involvement.

## Consequences
Unverified: limits on managed bots per manager bot, and whether Main Mini App settings can be configured by API for managed bots. Main Mini App and direct-link apps are configured in @BotFather as a guided, verified step until proven otherwise. Bot ownership (merchant vs platform) is an owner decision at Phase 2.

## History
| Date | Change |
|---|---|
| 2026-09-26 | aiogram 3.31.0 (Bot API 10.3) exposes the managed-bot methods, so the adapter is buildable in Python. Limits remain unverified (U6). |
