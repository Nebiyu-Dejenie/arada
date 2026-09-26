# ADR-016: Events via a transactional outbox in PostgreSQL

| Field | Value |
|---|---|
| **Status** | Accepted — mandated by Permanent Command §18; Master Directive §25 |
| **Date** | 2026-09-26 |

## Decision
Domain events are written to `ops.outbox` in the same transaction as the business change. A dispatcher delivers them with `FOR UPDATE SKIP LOCKED`, and consumers deduplicate through `ops.inbox`. There is no message broker initially.

## Context
Events must be reliable, versioned, traceable, idempotent and tenant-aware, without premature distributed infrastructure.

## Alternatives
Kafka, NATS or RabbitMQ from day one.

## Reason
Atomicity with zero extra infrastructure.

## Consequences
A broker adapter is added behind `EventBus` only when dispatcher lag or outbox contention is measured.
