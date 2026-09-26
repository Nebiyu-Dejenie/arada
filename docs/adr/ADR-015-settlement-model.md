# ADR-015: Settlement model defaults to merchant-direct

| Field | Value |
|---|---|
| **Status** | Accepted as the safety default — Permanent Command §16; the final model is blocked on legal and provider facts at Phase 4 |
| **Date** | 2026-09-26 |

## Decision
Model A (the customer pays the merchant's own provider account) is the default; Model B (provider split) once contracted; Model C (platform collects and pays out) only with written legal clearance, behind a feature flag.

## Context
The platform must not assume it may legally hold or settle funds under the National Bank of Ethiopia framework.

## Alternatives
Platform-collect by default.

## Reason
Avoids operating as an unlicensed payment intermediary.

## Consequences
The ledger supports all three models, so switching is configuration.
