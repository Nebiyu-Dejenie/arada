# ADR-005: Frontend: one TypeScript runtime, two bundles

| Field | Value |
|---|---|
| **Status** | Assumed — documented assumption per Permanent Command §53 |
| **Date** | 2026-09-26 |

## Decision
React + TypeScript + Vite in a pnpm workspace. A `customer` bundle (Mini App + web storefront) and a `console` bundle (super admin, vertical admin, merchant portal, finance). Both render from a server-resolved Runtime Manifest. The SDK is generated from OpenAPI.

## Context
One configurable runtime must render every merchant and vertical (Master §9, §81; Permanent §37).

## Alternatives
Per-vertical or per-merchant apps (forbidden); Next.js SSR (extra server runtime for a manifest-driven SPA).

## Reason
One codebase; a small customer bundle suited to the Telegram WebView; storefront content never shares an origin with staff sessions.

## Consequences
If storefront SEO needs grow, add pre-rendering for public listing pages.

## History
| Date | Change |
|---|---|
| 2026-09-26 | No frontend code in Phase 1 (platform kernel only). Compatibility evidence recorded: `@telegram-apps/sdk-react` 3.3.9 for Mini Apps. Verification with real code in Phase 2. |
