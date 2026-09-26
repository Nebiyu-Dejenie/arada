# 07 — Payment Architecture

Status: **Proposed; the settlement model is blocked on Q8 (provider contracts and legal review)** · Related: ADR-013, ADR-015 · Phase 7

**Payment state is not accounting state** (directive §96). `payments` tracks what a provider says happened. `ledger` (`08`) records what it means financially. They are linked by events and reconciled daily.

## 1. Regulatory position: read this first

The platform **must not hold or move customer funds on its own account** until the applicable Ethiopian framework has been reviewed by counsel. That framework is published by the National Bank of Ethiopia: the National Payment System Proclamation No. 718/2011 as amended in 2023, and its implementing directives on payment instrument issuers and payment system operators. Other laws may also apply, including electronic-transaction and personal-data-protection law; the current texts must be confirmed by counsel.

The architecture therefore supports three **settlement models**, chosen per payment configuration:

| Model | Money flow | Platform's legal exposure | Default |
|---|---|---|---|
| **A. Direct** | The customer pays the **merchant's own** provider account. The platform invoices its commission separately. | Lowest; the platform is a software provider | **Default until Q8 is resolved** |
| **B. Split** | The provider splits at source: the merchant's share goes to the merchant's sub-account and the commission goes to the platform's account (where the provider supports sub-accounts or split settlement, per contract) | Low to medium; confirm with the provider and counsel | Preferred once contracted |
| **C. Platform collect** | The customer pays the platform, and the platform pays out to merchants | **High:** likely requires a licence, or operating under a licensed partner | Only with written legal clearance; a feature flag guards it |

The ledger records every model faithfully (`08` §5), so changing model later is a configuration change, not a redesign.

## 2. Provider interface

A generalisation of the proven Bingo protocol:

```python
class PaymentProvider(Protocol):
    key: str                                   # "chapa", "telebirr", "santimpay", "arifpay", "cbebirr", "mpesa_et", "manual"
    capabilities: frozenset[Capability]        # CHECKOUT, REFUND, PARTIAL_REFUND, PAYOUT, SPLIT, STATUS_QUERY, STATEMENT

    async def create_checkout(self, cfg: ProviderConfig, req: CheckoutRequest) -> CheckoutResult
    def verify_webhook(self, cfg: ProviderConfig, headers: Mapping[str, str], raw_body: bytes) -> VerifiedEvent   # raises InvalidSignature
    async def fetch_status(self, cfg: ProviderConfig, our_ref: str) -> ProviderStatus
    async def refund(self, cfg: ProviderConfig, req: RefundRequest) -> RefundResult
    async def create_payout(self, cfg: ProviderConfig, req: PayoutRequest) -> PayoutResult
    async def fetch_statement(self, cfg: ProviderConfig, day: date) -> Statement
```

- `ProviderConfig` carries **decrypted credentials for one merchant or platform configuration**. It exists only in memory, for the duration of the call.
- `CheckoutRequest` uses the `Money` type (`amount_minor`, `currency`). Adapters convert to the provider's format at the boundary and verify the round trip.
- Adapters are written against each provider's current official documentation and contract, and each adapter has a **contract test suite** replaying recorded sandbox exchanges.
- Candidate adapters, subject to contracts (Q8): Telebirr (merchant API), Chapa, SantimPay, ArifPay, CBE Birr, M-PESA Ethiopia, and manual/bank transfer with proof upload and staff verification.

## 3. Payment intent state machine

```
created ──► pending ──► succeeded ──► partially_refunded ──► refunded
   │           │  ╲
   │           │   ╲──► failed
   │           └─────► expired
   └──► cancelled
```

- **Monotonic.** A state never moves backwards. A late `failed` after `succeeded` does **not** change state. It opens a `reconciliation_item` and alerts, because it indicates provider inconsistency or fraud.
- **Two signals, one truth:** a provider webhook or a status poll can each propose a transition. Before any `→ succeeded`, the platform calls `fetch_status` against the provider API when the provider supports it, and **checks amount, currency and reference** against the intent. A mismatch opens a `reconciliation_item` and the intent is never marked succeeded.
- `expired`: the intent's `expires_at` has passed (default 30 minutes) without success. A late success on an expired intent is still **accepted and recorded**, because the money did move. The order then either resumes, if stock is still reserved, or is auto-refunded according to the tenant's policy.

## 4. Checkout flow (directive §26, §41)

1. The customer confirms the cart in the Mini App. The server re-prices everything from the database: never trust client prices, discounts or fees.
2. `POST /api/v1/checkout` with an `Idempotency-Key` (UUID generated on the client per checkout attempt). The server:
   - creates the order (`created`) and reserves inventory (`reserved += qty`, row-locked, fails on insufficient stock)
   - creates the payment intent
   - writes `OrderCreated` and `PaymentInitiated` to the outbox

   All of this happens in **one transaction**.
3. The server calls `create_checkout` (outside the database transaction) and stores the `payment_attempt` with `provider_ref`. It returns the checkout URL or instructions.
4. The customer pays in the provider flow. The provider sends a callback to `api.DOMAIN/pay/wh/{provider}/{config_key}`.
5. **Webhook processing:**
   1. Verify the signature using that configuration's credentials. Failure returns 401 and increments a metric.
   2. `INSERT INTO finance.provider_events … ON CONFLICT (provider, provider_event_id) DO NOTHING`. A duplicate returns 200 with no further effect.
   3. Return **200 quickly**. The worker processes the event.
6. The worker, in one transaction:
   - locks the intent row
   - verifies status with the provider
   - transitions the intent
   - **posts ledger entries** (`08`)
   - writes `PaymentCompleted` to the outbox

   The `orders` module consumes `PaymentCompleted`, idempotently through the inbox, and the order workflow moves `created → paid`.
7. A **status poller** (`scheduler`) checks every `pending` attempt older than 2 minutes, with backoff, so a lost webhook never strands an order.

**No silent purchase.** AI agents and bots can *prepare* a cart and a checkout, but step 2 requires an explicit confirmation action by the customer in the Mini App UI: a MainButton press bound to a server-issued confirmation token. Tools cannot create one (`09` §9).

## 5. Idempotency (directive §30)

| Layer | Key | Guarantees |
|---|---|---|
| API | `Idempotency-Key` header, stored in `ops.idempotency_keys` (scope = principal + route, request-body hash, response) for 24 hours | A retried request returns the stored response. Reusing a key with a different body returns 422. |
| Intent | `UNIQUE (tenant_id, idempotency_key)` | One intent per checkout attempt |
| Provider call | `our_ref = intent.ref` sent as the provider's merchant reference | Providers that dedupe by reference will not double-charge |
| Callback | `UNIQUE (provider, provider_event_id)`. If a provider lacks an event id, use a hash of the canonical payload plus the provider reference. | Five identical callbacks produce one effect |
| Ledger | `ledger_transactions.idempotency_key UNIQUE` (e.g. `pay:<intent_id>:captured`), and a conflict with a different `kind` raises an error (a lesson carried over from the Bingo ledger audit) | Money is posted exactly once |
| Consumers | `ops.inbox (consumer, event_id)` | Each event handler runs once per consumer |

## 6. Refunds

- `POST /api/v1/merchant/refunds` requires `payments.refund`, step-up re-authentication, and an idempotency key. Refunds above a threshold require a second approver (`10` §5).
- A partial refund must satisfy `sum(refunds) ≤ captured`, enforced with a row lock on the intent and a `CHECK` on the running total.
- A refund after order completion is allowed within policy. The ledger reverses the commission proportionally, according to the commission rule's `refundable` flag.
- In Models A and B, the refund executes through the merchant's or split configuration. **The platform never refunds from its own funds unless Model C is enabled.**

## 7. Reconciliation

A daily job per payment configuration:

1. Fetch the provider statement (via API, or an uploaded CSV where there is no API).
2. Match statement lines to intents, refunds and payouts by provider reference, amount and currency.
3. Classify each line: `matched`, `missing_in_ledger`, `missing_at_provider`, `amount_mismatch`, `currency_mismatch` or `duplicate`.
4. Every unmatched item becomes a `reconciliation_item` with an owner, an SLA and a resolution (adjustment entry with a reason, provider dispute, or write-off). **No automatic ledger fixes.** Adjustments are made by finance staff and audited.
5. Metrics: match rate, unmatched value, and age of the oldest open item. These alert on thresholds.

## 8. Failure and test matrix (tested in `19` §4)

| Scenario | Expected |
|---|---|
| Duplicate webhook ×5 | One `provider_events` row, one ledger transaction |
| Webhook before `create_checkout` returned | Event stored; processed once the intent is known (retries with backoff; matched by `our_ref`) |
| Webhook lost | Status poller resolves it within the SLA |
| Callback out of order (`failed` after `succeeded`) | State stays `succeeded`; a reconciliation item is created and an alert raised |
| Amount or currency mismatch | Intent not succeeded; reconciliation item; alert |
| Provider timeout on create | Attempt `unknown` → poll by `our_ref` before any retry that could double-charge |
| Concurrent checkout for the last unit | Exactly one reservation succeeds; the other returns `409 out_of_stock` |
| Partial refunds summing above captured | Rejected |
| Refund after completion | Allowed per policy; commission reversal posted |
| Late success on an expired intent | Accepted; order resumed or auto-refunded per policy; fully ledgered |
