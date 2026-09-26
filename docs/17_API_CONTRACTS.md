# 17 — API Contracts

Status: **Proposed** · OpenAPI 3.1 is generated from the code (FastAPI + Pydantic). The committed spec is diffed in CI, and breaking changes without a version bump fail the build.

## 1. Conventions

| Topic | Rule |
|---|---|
| Style | REST + JSON over HTTPS, resource-oriented. Actions that are really commands use `POST /…/{id}:action` (e.g. `POST /orders/{id}:cancel`). |
| Versioning | URL major version `/api/v1`. Additive changes need no bump. Removals and semantic changes bump to `/v2`, with a ≥ 6-month overlap. |
| Origin | Same-origin `/api/*` on each surface host (`05` §3). `api.ROOT_DOMAIN` serves webhooks and the partner/mobile API. |
| Tenant | **Never** a request field for authorization. It is implied by host (storefront) or path slug + membership (console). |
| IDs | UUIDv7 strings. Human `ref` values (`ORD-26-000123`) are for display and search. |
| Money | `{"amount_minor": 1020000, "currency": "ETB"}`. **Never** a JSON float for money. Rates are `rate_bps` integers. |
| Time | RFC 3339 UTC (`2026-09-26T14:28:55Z`). |
| Localisation | `Accept-Language` (`am`, `en`); localised fields as `{"am": "…", "en": "…"}` in management APIs. |
| Pagination | Cursor: `?limit=50&cursor=…` → `{"items": [...], "next_cursor": "…"}`. `limit` ≤ 200. |
| Filtering | `?filter[price][gte]=10000&filter[attr.storage_gb][in]=128,256&sort=-published_at`. Only blueprint-declared filters are accepted. |
| Concurrency | `ETag: "v7"` on reads; `If-Match` **required** on updates of versioned aggregates → 412 on mismatch. |
| Idempotency | `Idempotency-Key` **required** on `POST`s that create orders, payments, refunds or payouts, or send messages. Stored 24 h, scoped to principal + route (`07` §5). |
| Errors | RFC 9457 `application/problem+json` with `type`, `title`, `status`, `detail`, `instance`, `request_id`, and `errors` (field → messages) for validation. No stack traces, SQL or internal hostnames. |
| Rate limits | `429` + `Retry-After`; `RateLimit-*` headers. |
| Not found vs forbidden | Cross-tenant or non-member access returns **404**, never 403, so the response does not reveal that a resource exists. |

## 2. Surfaces and authentication

| Surface | Base | Auth | Consumers |
|---|---|---|---|
| Runtime | `{host}/api/v1/runtime/*` | none / any | Both bundles at start-up |
| Customer | `{slug}.ROOT_DOMAIN/api/v1/*` | Bearer (tenant-bound customer token, `04` §5) | Mini App + web storefront |
| Merchant console | `merchant.ROOT_DOMAIN/api/v1/t/{tenant_slug}/*` | Session cookie + CSRF | Merchant staff |
| Platform console | `admin.ROOT_DOMAIN/api/v1/platform/*`, `…/v1/verticals/{key}/*` | Cloudflare Access + session + CSRF | Platform and vertical roles |
| Finance console | `finance.ROOT_DOMAIN/api/v1/finance/*` | Cloudflare Access + session + CSRF | Finance roles |
| Telegram webhooks | `api.ROOT_DOMAIN/tg/wh/{route_key}` | Secret header | Telegram |
| Payment webhooks | `api.ROOT_DOMAIN/pay/wh/{provider}/{config_key}` | Provider signature | Providers |
| Partner API (future) | `api.ROOT_DOMAIN/api/v1/partner/*` | Hashed API keys, scoped | Integrations |

## 3. Key endpoints by phase (initial contract)

### Runtime and auth (staff in Phase 1; Telegram in Phase 2)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/runtime/manifest` | Resolved tenant/vertical/blueprint/theme/flags/locales/permissions. `ETag` = hash(tenant.config_version, blueprint content_hash, release). |
| POST | `/api/v1/auth/telegram` | Body `{ "init_data": "<raw string>" }` → `{access_token, expires_in, refresh_handle}` |
| POST | `/api/v1/auth/refresh` | Rotates the refresh handle |
| POST | `/api/v1/auth/staff/login` · `/webauthn/*` · `/totp/verify` · `/step-up` | Staff |
| POST | `/api/v1/auth/logout` | Revokes the session |

### Platform (Phase 1 foundations; Business Factory and migrations in Phase 6)

| Method | Path |
|---|---|
| GET/POST | `/api/v1/platform/verticals` |
| GET/POST | `/api/v1/platform/attributes` |
| GET/POST | `/api/v1/platform/blueprints`, `/blueprints/{id}/versions` |
| POST | `/api/v1/platform/blueprints/{id}/versions/{v}:publish` (step-up) |
| POST | `/api/v1/platform/blueprint-migrations:preview` → plan + impact report |
| POST | `/api/v1/platform/blueprint-migrations` (apply; step-up) · `…/{run}:rollback` |
| POST | `/api/v1/platform/businesses` **Create Business** → `provisioning_run` (202 + `Location`) |
| GET | `/api/v1/platform/provisioning-runs/{id}` (steps and status) · `POST …/{id}:retry` |
| GET | `/api/v1/platform/tenants?filter[status]=…&filter[vertical]=…` |
| POST | `/api/v1/platform/tenants/{id}:suspend` · `:activate` · `:archive` (step-up) |
| GET | `/api/v1/platform/tenants/{id}/health` · `/deployment` |
| GET/POST | `/api/v1/platform/roles`, `/role-assignments`, `/access-grants` |
| GET | `/api/v1/platform/audit-events` |

### Merchant console (Phases 3–4; production-grade in Phase 5)

| Method | Path |
|---|---|
| GET/POST | `/api/v1/t/{slug}/listings` · `PATCH /listings/{id}` (If-Match) · `POST /listings/{id}:publish` |
| POST | `/api/v1/t/{slug}/media/uploads` → pre-signed PUT |
| GET/POST | `/api/v1/t/{slug}/inventory/adjustments` |
| GET | `/api/v1/t/{slug}/orders` · `/orders/{id}` |
| POST | `/api/v1/t/{slug}/orders/{id}/transitions` `{ "to": "packed" }` (validated against the workflow) |
| POST | `/api/v1/t/{slug}/refunds` (Idempotency-Key, step-up) |
| GET | `/api/v1/t/{slug}/finance/summary?period=…` · `/finance/ledger-lines` · `/finance/payouts` · `/finance/export` |
| GET/POST | `/api/v1/t/{slug}/staff` · `/staff/{id}/roles` |
| GET/PUT | `/api/v1/t/{slug}/settings/payments` (step-up) · `/settings/branding` · `/settings/delivery` |

### Customer (Phases 2–4)

| Method | Path |
|---|---|
| GET | `/api/v1/catalog/search?q=…&filter[...]` · `/catalog/listings/{id}` · `/catalog/categories` |
| GET | `/api/v1/deeplinks/{start_param}` → resolved target (within the tenant only) |
| GET/PUT | `/api/v1/cart` |
| POST | `/api/v1/checkout` (Idempotency-Key) → `{order, payment: {checkout_url | instructions}, confirmation_required}` |
| POST | `/api/v1/checkout/{id}:confirm` `{confirmation_token}`, the explicit human confirmation step |
| GET | `/api/v1/orders` · `/orders/{id}` (own orders only) |
| POST | `/api/v1/orders/{id}/reviews` (eligibility-checked) |

## 4. Example: problem response

```json
{
  "type": "https://docs.ROOT_DOMAIN/problems/insufficient-stock",
  "title": "Insufficient stock",
  "status": 409,
  "detail": "Only 1 unit of 'Galaxy A55 256GB' is available.",
  "instance": "/api/v1/checkout",
  "request_id": "01J8Z6Q3M7X2R4T5V6W7Y8Z9AB",
  "errors": { "items[0].qty": ["exceeds_available"] }
}
```

## 5. Frontend SDK

A typed TypeScript client (`frontend/packages/sdk`) is **generated from the OpenAPI spec** in CI. Handwritten fetch calls against `/api` are disallowed by lint, so frontend and backend cannot drift silently.
