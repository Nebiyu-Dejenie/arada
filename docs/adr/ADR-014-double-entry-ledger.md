# ADR-014: Double-entry, append-only ledger as the financial source of truth

| Field | Value |
|---|---|
| **Status** | Accepted — mandated by Permanent Command §14; Master Directive §28 |
| **Date** | 2026-09-26 |

## Decision
The finance plane holds a double-entry ledger: zero-sum per currency enforced by a deferred database trigger, append-only through triggers and grants, idempotent posting, corrections only by reversal, and a nightly balance rebuild with comparison.

## Context
Payment records are not accounting records; historical finance must not come from mutable orders.

## Alternatives
Balances on order or payment rows.

## Reason
Mathematically balanced, auditable and traceable money movement.

## Consequences
Only finance modules post. Other modules emit events that posting rules translate.
