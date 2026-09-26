# 10 — RBAC

Status: **Proposed** · Related: ADR-025 · Phase 1

## 1. Model: scoped roles

```
role_assignment = (person, role, scope_type, scope_id)
scope_type ∈ { platform, vertical, tenant }
authorize(principal, permission, target_scope) → allow | deny (+ reason)
```

- A **permission** is a string `resource.action`, for example `orders.refund`. The permission catalogue is defined in code and seeded by migration.
- A **role** is a named set of permissions, valid at one scope type. System roles are immutable. Tenants may define **custom tenant roles** later, but only from permissions allowed at tenant scope.
- **Scope containment:** a platform-scoped assignment applies to all verticals and tenants. A vertical-scoped assignment applies to tenants in that vertical. A tenant-scoped assignment applies only to that tenant. There is **no implicit containment beyond this**: a vertical admin of Phones has no rights in Cars.
- **There is no god-mode bypass.** `SUPER_ADMIN` is simply the role that holds every permission, and it is checked through the same `authorize` function as every other role, as in the proven Bingo RBAC.
- Authorization is evaluated **server-side on every request**. The UI hides what a user cannot do, for usability only.

## 2. System roles

| Role | Scope | Summary |
|---|---|---|
| `SUPER_ADMIN` | platform | Everything, including platform configuration, finance approval and security settings |
| `PLATFORM_ADMIN` | platform | Verticals, blueprints, tenants, bots, domains and flags; no finance approvals and no security settings |
| `PLATFORM_FINANCE` | platform | All finance: read, reconcile, payouts (maker), commission proposals |
| `PLATFORM_SUPPORT` | platform | Tickets, read-only tenant overview; tenant data only through JIT grants (`02` §7) |
| `PLATFORM_OPS` | platform | Deployments, health, infrastructure views; no business data |
| `VERTICAL_ADMIN` | vertical | That vertical's blueprints, categories, attributes, merchants, analytics and rules |
| `VERTICAL_FINANCE` | vertical | Finance for tenants in the vertical (read and export) |
| `TENANT_OWNER` | tenant | Everything in the tenant, including staff, payment configuration and payout destination |
| `TENANT_ADMIN` | tenant | Everything except ownership transfer, payout destination and the payment provider |
| `TENANT_FINANCE` | tenant | Finance read and export, refunds (with limits), payout history |
| `TENANT_MANAGER` | tenant | Catalog, inventory, orders, promotions, reviews, delivery |
| `TENANT_STAFF` | tenant | Orders (fulfil), inventory adjustments, customer messages |
| `CUSTOMER` | tenant (implicit) | Own profile, carts, orders, reviews; granted implicitly by a customer session, never assigned by hand |
| `DELIVERY_AGENT` | tenant or platform | Assigned deliveries only: status and proof of delivery |
| `SERVICE_PROVIDER` | tenant | Assigned bookings or jobs (beauty, services, construction) |

Blueprints can add vertical-specific tenant roles, such as `INSPECTOR` for Cars, drawn only from tenant-scope permissions.

## 3. Permission catalogue (initial)

| Area | Permissions |
|---|---|
| Platform | `platform.settings.manage`, `security.manage`, `audit.read`, `infra.read`, `deploy.manage`, `flags.manage` |
| Verticals and blueprints | `vertical.manage`, `blueprint.read`, `blueprint.manage`, `blueprint.publish`, `blueprint.migrate`, `attribute_library.manage` |
| Tenants | `tenant.create`, `tenant.read`, `tenant.manage`, `tenant.suspend`, `tenant.archive`, `tenant.impersonate_support` (JIT only) |
| Edge | `domain.manage`, `bot.manage`, `bot.rotate_token` |
| Staff | `staff.read`, `staff.invite`, `staff.manage_roles` |
| Catalog | `catalog.read`, `catalog.write`, `catalog.publish`, `inventory.adjust` |
| Orders | `orders.read`, `orders.create`, `orders.fulfil`, `orders.cancel`, `orders.refund` |
| Payments | `payments.read`, `payments.configure`, `payments.refund` |
| Finance | `finance.read`, `finance.export`, `finance.reconcile`, `finance.adjust`, `finance.commission.manage`, `payouts.create`, `payouts.approve`, `payouts.destination.manage` |
| Customers | `customers.read`, `customers.contact`, `customers.export` |
| Engagement | `promotions.manage`, `reviews.moderate`, `notifications.send`, `campaigns.manage`, `ads.manage` |
| Delivery | `delivery.read`, `delivery.update`, `delivery.assign` |
| Support | `support.read`, `support.respond`, `disputes.manage` |
| AI | `ai.use`, `ai.configure`, `ai.budget.manage` |
| Analytics | `analytics.read`, `analytics.export` |

The full role × permission matrix lives in code (`control/rbac/catalogue.py`) with a generated table in the docs. CI fails if the documented matrix and the code disagree.

## 4. Policy checks beyond RBAC

Some rules depend on the *resource*, not just the role. These checks live in module policy functions:

- **Ownership:** a `CUSTOMER` can read an order only if `order.customer.person_id == principal`.
- **Assignment:** a `DELIVERY_AGENT` can update only deliveries assigned to them.
- **Limits:** a `TENANT_FINANCE` refund is limited to a per-refund and per-day amount (tenant-configurable), and anything above the limit requires `TENANT_OWNER`.
- **State:** refunds are allowed only on `succeeded`/`partially_refunded` intents.
- **Plan:** entitlements, for example the staff seat limit, are checked by `plans`, not by roles.

## 5. Sensitive actions: step-up re-authentication and approvals (directive §54, §87)

| Action | Step-up | Second approver (maker–checker) | Audited |
|---|---|---|---|
| Create or suspend a tenant | ✓ | — | ✓ |
| Archive a tenant | ✓ | ✓ | ✓ |
| Publish or migrate a blueprint (bulk) | ✓ | configurable | ✓ |
| Change commission rules | ✓ | ✓ above threshold | ✓ |
| Change payment provider or credentials | ✓ | ✓ (platform scope) | ✓ |
| Refund above the tenant limit | ✓ | tenant owner | ✓ |
| Create or approve a payout batch | ✓ | ✓ (different person) | ✓ |
| Change a payout destination | ✓ + 24 h cool-off | owner only | ✓ + notify on all channels |
| Change roles or permissions | ✓ | ✓ for platform roles | ✓ |
| Rotate bot or provider credentials | ✓ | — | ✓ |
| Disable a merchant or security settings | ✓ | ✓ | ✓ |

**Single-operator mode.** While only one platform admin exists, second-approver requirements are satisfied by step-up re-authentication, a 10-minute delay with an Ops-bot notification, and a daily digest of such actions. The mode switches off automatically once a second `SUPER_ADMIN` or `PLATFORM_FINANCE` exists. This keeps the controls in place without blocking a solo founder.

## 6. Implementation

```python
@router.post("/t/{tenant_slug}/refunds")
async def create_refund(ctx: RequestContext = Depends(tenant_ctx), body: RefundIn = …):
    await authz.require(ctx, "orders.refund")                 # role check at tenant scope
    await authz.require_step_up(ctx, max_age=timedelta(minutes=5))
    return await refunds.create(ctx, body)                    # policy checks inside the module
```

- `tenant_ctx` resolves the tenant **only** from membership plus the path slug, and 404s if the principal has no membership (so it does not reveal that the tenant exists).
- An effective-permission cache in Redis, keyed by `(person, scope, assignments_version)`, is invalidated on any assignment change.
- Every `deny` is logged with a reason code. A rising deny rate for one principal feeds the risk engine.
