# ADR-028: Reference vertical: Phones

| Field | Value |
|---|---|
| **Status** | Assumed — documented assumption per Permanent Command §53; confirm before Phase 5 |
| **Date** | 2026-09-26 |

## Decision
Phones is the Phase 5 reference vertical.

## Context
One vertical must prove blueprint, tenant, Mini App, portal, catalog, checkout, payment, finance, orders, notifications, audit and analytics end to end.

## Alternatives
Food (needs delivery earlier), Cars (inquiry-led, weak checkout proof), Fashion (variant-heavy).

## Reason
A standard retail checkout with a clear order workflow, strong structured attributes (brand, storage, RAM, condition) and one vertical extension (IMEI validation), which exercises the whole stack without a courier network.

## Consequences
Delivery for the reference vertical is merchant-handled (pickup or self-delivery) until the Phase 8 delivery engine.

## History
| Date | Change |
|---|---|
| 2026-09-26 | Phones 1.0.0, 1.1.0 and 2.0.0 exist as seed data in `blueprints/phones/`. A test forbids vertical names in platform code. |
