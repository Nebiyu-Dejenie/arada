# 14 — Cost Model

Status: **Proposed** · Directive §61, §88–90 · All figures are **planning estimates** to be replaced by measurements (§3)

The metric that matters is **cost per active merchant**, not total infrastructure cost.

## 1. Cost structure

| Category | Driver | Shared or per merchant |
|---|---|---|
| Compute (VMs) | Request volume, worker jobs | Shared (fixed step costs) |
| PostgreSQL storage | Rows × indexes | Grows per merchant |
| Object storage | Images and documents | Grows per merchant (**dominant**) |
| Backups (off-site) | ≈2× DB + media | Grows per merchant |
| Cloudflare | Plan tier; DNS record count (`05` §5) | Free at launch; step cost at scale |
| Telegram | Bot API | **Free** (paid broadcast only if ever used) |
| SMS / email | Messages sent | Per merchant (metered, pass-through or plan-limited) |
| AI | Tokens per request × model price | Per merchant (**must be budgeted**, §6) |
| Payment fees | % of GMV per provider | Per transaction (merchant-borne or priced into commission) |
| Delivery | Per delivery | Per order (priced to the customer or merchant) |
| Support | Tickets × time | Per merchant (tracked by ticket tenant) |

## 2. Unit estimates (to validate)

A "typical Starter merchant": 500 listings, 3 images each, 300 orders per month, 1,500 customers.

| Resource | Estimate per merchant per year | Notes |
|---|---|---|
| Postgres rows | ≈ 50k (listings, projections, orders, transitions, ledger lines, events) | |
| Postgres size incl. indexes | **≈ 50–150 MB** | Ledger and audit dominate over time |
| Media | 500 × 3 × (full ≈150 KB WebP + card 40 KB + thumb 10 KB) ≈ **0.3 GB** | Enforced by the pipeline: originals are **not** kept by default (max 1600 px, re-encoded) |
| Backup footprint | ≈ 2× (DB + media) ≈ **0.8 GB** | Deduplicated and compressed by pgBackRest |
| Notifications | ≈ 1,500 Telegram messages/month (free); SMS only on opt-in | |
| AI | Plan-dependent (§6) | |

**Capacity of the Stage-1 topology** (`11` §2), to validate by load test: several hundred active Starter merchants and roughly 20–50 req/s of sustained API traffic. Storage, not CPU, is the first constraint (≈ 1 TB covers roughly 1,000 merchants' media and backups).

## 3. Measuring instead of guessing

- `usage_counters(tenant_id, meter, period, value)` is written by `scheduler` from events and storage scans. Meters: `listings`, `media_bytes`, `db_bytes_est` (rows × average width), `orders`, `api_requests`, `worker_seconds`, `notifications_{channel}`, `ai_tokens_{in,out}`, `ai_cost_minor`, `payment_volume_minor`, `support_tickets`.
- **Cost allocation** each month:

  ```
  cost_per_merchant = Σ(direct metered cost)
                    + shared_fixed × (merchant's weighted share by requests + storage)
  ```

  This is shown in the Super Admin console next to the merchant's revenue contribution (commission + subscription + ads), which gives a **contribution margin per merchant**.
- **Phase 1 exit includes a load test** (k6) that measures requests/s per `api` replica and the queue throughput per worker. Its results replace §2's guesses.

## 4. Cost controls built into the architecture

- One shared stack. No per-merchant VM, database, Redis or deployment by default (directive §61).
- Placement tiers let expensive isolation be **sold**, not given away (Pro and Enterprise plans).
- Media pipeline: no originals, WebP/AVIF, an immutable-key CDN cache at Cloudflare (egress from origin minimised).
- Aggressive partitioning and retention (outbox pruned after 14 days, logs 14–30 days, traces 7 days).
- Cloudflare Free plan until a documented trigger: DNS record count > 80% of the limit (→ wildcard mode, or upgrade), or a need for advanced WAF, image optimisation or rate-limiting features.

## 5. Plans and entitlements (directive §90)

Plans are **data**: `plans`, `plan_entitlements(plan_id, key, limit, overage_policy)`. Enforcement lives in **one place**, `plans.check(ctx, key, increment)`, which is called by modules at the point of creation. No `if plan == "PRO"` appears anywhere.

| Entitlement | FREE | STARTER | PRO | BUSINESS | ENTERPRISE |
|---|---|---|---|---|---|
| Active listings | 50 | 500 | 5,000 | 25,000 | custom |
| Staff seats | 1 | 3 | 10 | 30 | custom |
| Orders / month | 100 | 1,000 | 10,000 | 50,000 | custom |
| Media storage | 1 GB | 5 GB | 25 GB | 100 GB | custom |
| AI credits / month | minimal | small | medium | large | custom |
| Analytics | basic | basic | advanced | advanced + export | custom |
| Integrations / API keys | — | — | ✓ | ✓ | ✓ |
| Automation (workflows, campaigns) | — | basic | ✓ | ✓ | ✓ |
| Isolation tier | Starter | Starter | Starter | Pro | Enterprise |
| Support | community | standard | priority | priority | dedicated |

The numbers are placeholders for the business to set. The **mechanism** is what matters. Overage policies are `block`, `allow_and_bill` or `soft_warn`, per entitlement.

## 6. AI cost control (directive §89)

- **Gateway only.** All model calls go through `intelligence.ai.gateway`, which has:
  - a provider abstraction and a model-routing table (cheap model by default; a larger model only for tasks that need it)
  - per-tenant **monthly budgets** in money (`ai_cost_minor`) and **rate limits** (requests per minute per principal)
  - a **response cache** keyed on normalised input for deterministic tasks (translations, descriptions)
  - token accounting per call, attributed to the tenant and the feature
  - fallbacks: on budget exhaustion, a degraded mode (templates or search-only) rather than an error, and the merchant is notified
- **Structured intent, not free text:** customer queries (including Amharic, directive §73) are converted into a **structured search intent** (JSON Schema-validated), and the commerce engine executes it. This keeps model output small and cheap, and keeps business logic out of the model.

## 7. Revenue mechanisms supported (directive §74)

Commission (per rule precedence, `08` §6), subscriptions (plans), featured listings and ads (`advertising` module), lead fees (inquiry-only verticals: fee per qualified inquiry), delivery margin, service and ticket fees, B2B transaction fees, AI and analytics add-ons, and verification services. Each is a separate **revenue account** in the ledger (`08` §3), so profitability is measurable per line.
