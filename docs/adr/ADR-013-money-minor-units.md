# ADR-013: Money as integer minor units with explicit currency

| Field | Value |
|---|---|
| **Status** | Accepted — mandated by Master Directive §27 |
| **Date** | 2026-09-26 |

## Decision
Amounts are `bigint` minor units plus an ISO 4217 currency. Rates are integer basis points. Splits use largest-remainder allocation.

## Context
No floating point for money; exactness is required.

## Alternatives
`NUMERIC` decimals.

## Reason
Exact arithmetic with no conversion hazards at API boundaries.

## Consequences
A per-currency exponent table; JSON carries `amount_minor` integers, never floats.
