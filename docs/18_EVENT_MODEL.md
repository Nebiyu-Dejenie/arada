# 18 — Event Model

Status: **Proposed** · Related: ADR-016 · Directive §24–25

## 1. Envelope

Every domain event, whether stored in `ops.outbox` or delivered to consumers, uses one envelope:

```json
{
  "event_id": "0192f0c4-7d7e-7a31-9b8e-3f0a5c1d2e4f",
  "type": "orders.OrderCreated",
  "version": 1,
  "occurred_at": "2026-09-26T14:28:55.123Z",
  "tenant_id": "0192f0c4-…",                 // null only for platform-scoped events
  "aggregate": { "type": "order", "id": "0192f0c4-…", "version": 1 },
  "actor": { "type": "person|system|provider", "id": "…" },
  "correlation_id": "…",                      // the business flow (e.g. checkout)
  "causation_id": "…",                        // the event or command that caused this one
  "trace": { "traceparent": "00-…-…-01" },
  "payload": { … }                            // versioned schema per (type, version)
}
```

- **Versioned:** `type` + `version`. The payload schemas are JSON Schema files in `backend/src/arada/**/events/*.v{n}.json`. Consumers declare which versions they accept. A new incompatible payload means a new version, and producers dual-publish during migration.
- **Traceable:** `correlation_id`, `causation_id` and the W3C trace context.
- **Tenant-aware:** `tenant_id` is mandatory for tenant events. Consumers re-establish `RequestContext` from it (`02` §4).
- **No PII in payloads** beyond ids. Consumers fetch details through module interfaces under authorization.

## 2. Reliable publication: the transactional outbox

```
BEGIN
  UPDATE/INSERT business rows …
  INSERT INTO ops.outbox (event_id, type, version, tenant_id, payload, …)
COMMIT
dispatcher:  SELECT … FROM ops.outbox WHERE published_at IS NULL ORDER BY event_id
             FOR UPDATE SKIP LOCKED LIMIT 100
             → deliver to each subscribed consumer's queue (ops.jobs) → set published_at
```

- A business change and its events commit **atomically**. There is no "write the database, then separately publish" (directive §25).
- **Delivery is at least once.** Consumers must be idempotent: `ops.inbox (consumer, event_id)` is inserted in the consumer's own transaction, and a duplicate is skipped.
- **Ordering:** within a single aggregate, consumers see events in `aggregate.version` order. The dispatcher partitions by `aggregate.id`, and consumers check the version and park out-of-order events for retry. There is no global ordering guarantee, and no consumer may assume one.
- **Retries and dead letters:** exponential backoff up to 24 h, then a `dead_letter` status with an alert. Replay is an explicit admin action.
- **Broker later (ADR-016):** when throughput or fan-out outgrows Postgres (a measured signal: dispatcher lag or outbox write contention), an `EventBus` adapter publishes from the outbox to NATS JetStream or RabbitMQ. Producers and consumers do not change.

## 3. Event catalogue (initial)

| Event | Producer | Key consumers | Notes |
|---|---|---|---|
| `tenancy.TenantCreated` | tenancy | provisioning, audit, analytics | |
| `tenancy.TenantStateChanged` | tenancy | edge, telegram, payments, notifications | Suspension cascades to channel behaviour |
| `provisioning.MerchantProvisioned` | provisioning | notifications (owner welcome), analytics | Emitted on activation |
| `blueprint.BlueprintVersionPublished` | blueprint | provisioning (new default), console notifications | Platform-scoped (`tenant_id` null) |
| `blueprint.TenantBlueprintMigrated` | blueprint | catalog (projection rebuild), search, analytics | |
| `edge.DomainActivated` / `DomainFailed` | edge | provisioning, health | |
| `telegram.BotConnected` / `BotDegraded` / `BotOwnerChanged` | telegram | health, security alerts | Owner change is a security signal |
| `catalog.ProductCreated` / `ProductPublished` / `ProductUpdated` | catalog | search, AI (embeddings later), analytics | |
| `inventory.StockReserved` / `StockReleased` / `StockAdjusted` | inventory | catalog availability, analytics | |
| `orders.OrderCreated` | orders | payments, notifications, analytics, risk | |
| `orders.OrderStateChanged` | orders | notifications, delivery, reviews (on completed), payouts eligibility | Carries from/to state |
| `orders.OrderCancelled` | orders | payments (refund if paid), inventory (release) | |
| `payments.PaymentInitiated` | payments | analytics | |
| `payments.PaymentAuthorized` | payments | orders | Providers with auth/capture |
| `payments.PaymentCompleted` | payments | **orders** (→ paid), notifications, analytics, risk | Ledger posted in the same transaction as this event |
| `payments.PaymentFailed` / `PaymentExpired` | payments | orders (release stock), notifications, risk | |
| `payments.RefundCreated` / `RefundCompleted` / `RefundFailed` | payments | orders, notifications, ledger (posting rule), risk | |
| `ledger.TransactionPosted` | ledger | finance read models, analytics | Platform-internal |
| `payouts.PayoutCreated` / `PayoutCompleted` / `PayoutFailed` | payouts | notifications (merchant), finance | |
| `reconciliation.ItemOpened` / `ItemResolved` | reconciliation | finance console, alerts | |
| `delivery.ShipmentCreated` / `ShipmentDelivered` | delivery | orders, notifications, reviews | |
| `reviews.ReviewSubmitted` | reviews | trust, moderation, analytics | |
| `promotions.CampaignCreated` / `CouponRedeemed` | promotions | analytics, finance (discount accounting) | |
| `referrals.AttributionRecorded` / `RewardQualified` | referrals | promotions, finance, risk | |
| `ai.ActionProposed` / `ActionConfirmed` | ai | audit, analytics | Confirmation is by a human |
| `risk.SignalRaised` | risk | review queue, notifications (ops) | Signals, not punishments |

Naming: `<module>.<PastTenseEvent>`. The directive's names (`OrderCreated`, `PaymentCompleted`, …) are preserved as the event name.

## 4. Analytics feed

The `analytics` consumer writes **facts** (`analytics.fact_*`, partitioned, tenant-scoped with RLS) from events: page views and searches from client beacons, plus funnel steps, orders, payments, refunds and revenue from the ledger. Merchant dashboards query facts under RLS, and platform dashboards use the platform reader. Heavy analytics can move to a columnar store (for example ClickHouse) later by adding a consumer, not by changing producers.
