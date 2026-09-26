# 14 — Cost Model

Status: **Proposed** · Master Directive §61, §88–90; Permanent Command §45 · **This document contains no invented resource figures.** Every number is either measured (§3) or set by the owner as a business decision (§5).

The target is not the cheapest possible platform. It is **maximum business capability per unit of infrastructure cost without sacrificing reliability or security** (Permanent Command §45). The key metric is **cost per active merchant**.

## 1. Cost structure

| Category | Driver | Shared or per merchant |
|---|---|---|
| Compute (VMs) | Request volume, worker jobs | Shared (step costs as hosts are added) |
| PostgreSQL storage | Rows × average width + indexes | Grows per merchant |
| Object storage | Images and documents | Grows per merchant (likely dominant; confirm by measurement) |
| Backups (off-host) | Database + media + WAL retention | Grows per merchant |
| Cloudflare | Plan tier; DNS records per zone (`05` §5) | Plan-dependent |
| Telegram | Bot API | No per-message fee for standard bot messages |
| SMS / email | Messages sent | Per merchant (metered; pass-through or plan-limited) |
| AI | Tokens × model price | Per merchant (**must be budgeted**, §6) |
| Payment fees | Provider rate × volume | Per transaction (merchant-borne or priced into commission) |
| Delivery | Per delivery | Per order |
| Support | Tickets × handling time | Per merchant |

## 2. Unit-cost formulas (the values come from measurement)

```
db_bytes(tenant)      = Σ_tables rows(tenant, table) × avg_row_bytes(table) × (1 + index_overhead(table))
media_bytes(tenant)   = Σ_assets Σ_variants bytes(variant)          (originals are not retained by default)
backup_bytes(tenant) ≈ db_bytes × retention_factor_db + media_bytes × versions_factor
compute_share(tenant) = tenant_requests / total_requests × shared_compute_cost
                      + tenant_worker_seconds / total_worker_seconds × worker_cost
```

- `avg_row_bytes` and `index_overhead` come from `pg_stat_user_tables`, `pg_total_relation_size` and `pgstattuple`.
- Variant sizes come from the media pipeline's own output metrics.
- Media-pipeline policy (`09` §8) is the main cost lever: no originals, a maximum dimension, modern formats.

## 3. Measuring instead of guessing

- `usage_counters(tenant_id, meter, period, value)` is written by `scheduler` from events and storage scans. Meters: `listings`, `media_bytes`, `db_bytes_est`, `orders`, `api_requests`, `worker_seconds`, `notifications_{channel}`, `ai_tokens_{in,out}`, `ai_cost_minor`, `payment_volume_minor`, `support_tickets`.
- **Monthly cost allocation:** `cost_per_merchant = Σ direct metered cost + shared fixed cost × weighted share (requests + storage)`. This is shown in the Super Admin console next to the merchant's revenue contribution (commission + subscription + ads), giving a **contribution margin per merchant**.
- **Capacity numbers** (requests/s per `api` replica, jobs/s per worker, merchants per host) are produced by:
  - the Phase 1 local profile, which is indicative only because a dev machine is not production
  - **k6 load tests on the real machines at Phase 5**

  They are recorded in `11` §3 and an ADR. They are never assumed.

## 4. Cost controls built into the architecture

- One shared stack. There is no per-merchant VM, database, Redis or deployment by default (Master §61).
- Isolation tiers let expensive isolation be **sold** (Pro and Enterprise plans), not given away.
- The media pipeline stores no originals, re-encodes images and uses immutable-key caching at Cloudflare.
- Partitioning and retention: outbox pruning, and log and metric retention sized to measured storage.
- No premature infrastructure: no Kubernetes, message broker or search cluster until metrics justify it (ADR-016/018/020).
- Cloudflare plan upgrades are triggered by documented events, such as the DNS record count nearing the zone limit or a needed feature. They are never pre-emptive.

## 5. Plans and entitlements (Master §90)

Plans are **data**: `plans` and `plan_entitlements(plan_id, key, limit, overage_policy)`. They are enforced in one place, `plans.check(ctx, key, increment)`, called by modules at the point of creation. No `if plan == "PRO"` appears anywhere.

| Entitlement | FREE | STARTER | PRO | BUSINESS | ENTERPRISE |
|---|---|---|---|---|---|
| Active listings | TBD | TBD | TBD | TBD | custom |
| Staff seats | TBD | TBD | TBD | TBD | custom |
| Orders / month | TBD | TBD | TBD | TBD | custom |
| Media storage | TBD | TBD | TBD | TBD | custom |
| AI credits / month | TBD | TBD | TBD | TBD | custom |
| Analytics level | TBD | TBD | TBD | TBD | custom |
| Integrations / API keys | TBD | TBD | TBD | TBD | ✓ |
| Automation | TBD | TBD | TBD | TBD | ✓ |
| Isolation tier | Starter | Starter | Starter | Starter or Pro (TBD) | Enterprise |
| Support level | TBD | TBD | TBD | TBD | dedicated |

The limits and prices are **business decisions for the owner**, informed by the §3 cost-per-merchant data once it exists. The **mechanism** is what gets built. Overage policies per entitlement: `block`, `allow_and_bill` or `soft_warn`.

## 6. AI cost control (Master §89)

- **Gateway only.** All model calls go through `intelligence.ai.gateway`, which provides:
  - a provider abstraction and a model-routing table (the cheapest capable model by default)
  - per-tenant **monthly budgets** in money (`ai_cost_minor`)
  - **rate limits** per principal
  - a **response cache** for deterministic tasks (translations, descriptions)
  - token accounting per call, attributed to the tenant and the feature
  - fallbacks: on budget exhaustion, a degraded mode (templates or search-only), and the merchant is notified
- **Structured intent, not free text.** Customer queries, including Amharic (Master §73), are converted into a schema-validated **search intent**, and the commerce engine executes it. This keeps model output small and keeps business logic out of the model.

## 7. Revenue mechanisms supported (Master §74)

Each of these is a separate **revenue account** in the ledger (`08` §3), so profitability is measurable per line:

- commission (rule precedence, `08` §6)
- subscriptions (plans)
- featured listings and ads (`advertising`)
- lead fees (inquiry-only verticals)
- delivery margin
- service and ticket fees
- B2B transaction fees
- AI and analytics add-ons
- verification services
