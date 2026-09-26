# 08 — Ledger and Finance

Status: **Accepted in principle** (ADR-013, ADR-014 are mandated by the charter); details Proposed · Phase 4

The ledger is the **authoritative accounting trail** for every financial movement the platform controls or tracks. Historical finance is **never** recomputed from mutable order rows (directive §28).

## 1. Invariants (enforced by the database, not only by code)

1. **Balanced.** For each `ledger_transaction`, the sum of `amount_minor` over its entries is **0 for each currency**. This is enforced by a `DEFERRABLE INITIALLY DEFERRED` constraint trigger, checked per currency.
2. **Append-only.** Triggers reject `UPDATE`/`DELETE` on `ledger_transactions` and `ledger_entries`, and `arada_app` has only `INSERT, SELECT`. Corrections are made with **reversing transactions** that link to the original (`reverses_transaction_id`).
3. **Integer minor units.** ETB is stored in santim (exponent 2). There are no floats anywhere, and currency is explicit on every entry and account.
4. **Idempotent.** `idempotency_key UNIQUE`, and a key reused for a different `kind` raises an error.
5. **Single-currency accounts.** An entry's currency must equal its account's currency. Currency conversion, if ever needed, goes through an explicit FX account pair.
6. **Non-negative where required.** Accounts flagged `no_overdraft` (for example `merchant_payable` in some models) are checked under a row lock on `account_balances` at post time.
7. **Rebuildable cache.** `account_balances` is a cache. A nightly job recomputes balances from entries and **alerts on any difference**.

## 2. Posting API

```python
await ledger.post(
    conn,
    kind="payment_captured",
    idempotency_key=f"pay:{intent.id}:captured",
    tenant_id=intent.tenant_id,
    source=("payment_intent", intent.id),
    entries=[Entry(account, +amount_minor), …],    # signed: + debit, − credit
    memo="Order ORD-26-000123",
)
```

Only `finance` modules call `post`. Other modules emit events, and posting rules in `finance.posting` translate business events into entries. Each posting rule is a pure function with unit tests that assert balance and expected account deltas.

## 3. Chart of accounts (templates, instantiated per owner and currency)

| Account type | Owner | Normal side | Meaning |
|---|---|---|---|
| `provider_clearing` | platform × provider config | Debit (asset) | Money the provider holds for us and has not yet settled |
| `platform_bank` | platform | Debit (asset) | The platform's settlement bank or wallet |
| `payout_in_transit` | platform | Debit (asset) | Payouts sent but not yet confirmed |
| `merchant_payable` | tenant | Credit (liability) | What the platform owes the merchant (Model C) |
| `merchant_receivable_commission` | tenant | Debit (asset) | Commission the merchant owes the platform (Model A) |
| `delivery_payable` | courier or partner | Credit (liability) | Owed for delivery |
| `customer_refund_payable` | tenant | Credit (liability) | Refunds approved but not yet executed |
| `platform_commission_revenue` | platform | Credit (revenue) | |
| `platform_subscription_revenue` / `ads_revenue` / `delivery_margin_revenue` | platform | Credit (revenue) | Other revenue lines (directive §74) |
| `payment_processing_expense` | platform | Debit (expense) | Provider fees borne by the platform |
| `merchant_gross_sales_memo` / `_contra` | tenant | Memo pair | Tracks gross sales that never touch platform accounts (Models A and B) |
| `suspense` | platform | Either | Unidentified money. Must be cleared, and alerts when non-zero for more than 48 hours. |

## 4. Worked example: Model C (platform collect)

The order totals **10,200.00 ETB**: goods 10,000.00 plus delivery 200.00. Commission is 5% of goods (500.00). The provider fee is 3.5% of the gross (357.00) and, by contract, is borne by the merchant.

| # | Event | Debit | Credit | Amount |
|---|---|---|---|---|
| 1 | `PaymentCompleted` | `provider_clearing:chapa` | `merchant_payable:M` | 10,200.00 |
| 2 | Commission (same transaction as #1) | `merchant_payable:M` | `platform_commission_revenue` | 500.00 |
| 3 | Delivery (same transaction as #1) | `merchant_payable:M` | `delivery_payable:courier` | 200.00 |
| 4 | Provider settlement report | `merchant_payable:M` (fee borne by the merchant) | `provider_clearing:chapa` | 357.00 |
| 5 | Provider settles to the bank | `platform_bank` | `provider_clearing:chapa` | 9,843.00 |
| 6 | Payout initiated | `merchant_payable:M` | `payout_in_transit` | 9,143.00 |
| 7 | Payout confirmed | `payout_in_transit` | `platform_bank` | 9,143.00 |

Final balances:

- `provider_clearing` = 10,200 − 357 − 9,843 = **0**
- `merchant_payable:M` = 10,200 − 500 − 200 − 357 − 9,143 = **0**
- `platform_bank` = 9,843 − 9,143 = **700**, which equals commission revenue 500 plus the delivery payable of 200 still owed to the courier

Every transaction balances, and every balance is explainable.

## 5. Models A and B (merchant-direct and split)

- **A (direct):** the platform never touches the money. On `PaymentCompleted`, the platform posts:
  - memo entries recording the merchant's gross sales (`merchant_gross_sales_memo` / `_contra`), for merchant finance reports and reconciliation
  - `merchant_receivable_commission:M` DR / `platform_commission_revenue` CR (500.00), which is invoiced periodically

  Commission collection (invoice paid, or netted against a subscription) clears the receivable.
- **B (split):** the provider splits at source. The platform posts the memo gross, `provider_clearing` DR / `platform_commission_revenue` CR for the commission share, then settlement to `platform_bank`. The merchant's share stays in memo accounts only. The split must reconcile with the provider's statement.

## 6. Commission rules (directive §74)

A rule has a scope, a rate (`rate_bps`), an optional `fixed_minor` fee, optional `min_minor`/`max_minor` bounds, effective dates, and a `refundable` flag.

**Precedence** (most specific wins; the first match in this order is used):

```
1. campaign        (explicit promotional override, time-boxed)
2. product         (listing / variant)
3. merchant × category
4. merchant        (negotiated)
5. plan            (merchant's subscription plan)
6. vertical × category
7. vertical
8. platform default
```

- Rules are **immutable once referenced** by an order. A change creates a new rule version with a new `effective_from`.
- At checkout, the resolved `commission_rule_id` and `commission_bps` are **snapshotted onto each `order_item`**, so historical finance never changes when rules change (directive §96).
- Every rule change is audited and requires `finance.commission.manage`, step-up re-authentication, and (configurably) a second approver.

**Rounding and allocation:**

- `commission = round_half_up(line_total_minor × rate_bps / 10_000)` per line, computed with integer arithmetic.
- When one amount is split across several parties, the remainder in minor units goes by the **largest-remainder method**, so the parts always sum exactly to the whole.
- Tests assert this property with property-based testing over random amounts and rates.

## 7. Payouts (Model C, or commission remittance in A and B)

- Payout schedule per tenant (daily, weekly or manual). A payout is **eligible** when:
  - the order is `completed` and older than the return or dispute window, and
  - there is no open dispute or reconciliation item for it.
- **Payout batch:**
  1. Compute eligible balances (read from the ledger).
  2. Create `payouts`.
  3. Post `merchant_payable → payout_in_transit`.
  4. Call the provider's `create_payout` with an idempotency key.
  5. On confirmation, post `payout_in_transit → platform_bank`.
  6. On failure, reverse step 3 and retry per policy.
- Controls:
  - maker–checker approval for batches above a threshold
  - a payout destination change requires owner re-authentication, a 24-hour cooling-off period, and a notification to the owner on all channels, because a changed destination is the classic account-takeover path
  - a daily platform payout limit

## 8. Finance portals (directive §31)

| Viewer | Scope | Shows |
|---|---|---|
| **Merchant finance** (`merchant.ROOT_DOMAIN/finance`) | Own tenant (RLS) | Gross sales, platform fees, commissions, payment fees, delivery fees, refunds, adjustments, payable or receivable balance, payouts, transaction history with drill-down to ledger lines, reconciliation status, CSV export (formula-injection-safe) |
| **Vertical finance** (`finance.ROOT_DOMAIN`) | Tenants in authorized verticals | The above, aggregated per vertical and per merchant |
| **Platform finance / Super Admin** | Everything (platform reader) | Platform P&L by revenue line, provider clearing positions, suspense, reconciliation queue, payout batches, commission rule history |

Every figure on every finance screen is computed **from ledger entries**. A screen may use cached aggregates, but those aggregates are rebuilt from entries. There are no finance numbers derived from `orders` alone.

## 9. Period close

At month end:

1. A `period_lock(month)` prevents back-dated posting.
2. Corrections after the lock post into the next open period, with a reference to the original.
3. A snapshot report is produced (trial balance per currency, which must total 0), signed with a content hash and stored in the object store.
