# 03 — Blueprint Engine

Status: **Proposed** · Related: ADR-006, ADR-007, ADR-028 · Phases: foundation (versions, publish, pinning, rules) in **1**; order workflows in **3**; production Phones blueprint in **5**; version migrations in **6**; other verticals in **7**

The blueprint engine is the scalability engine. **A new vertical is new data, not new code**, except for genuinely unique logic, which lives in registered extensions (§8).

## 1. What a blueprint defines

| Section | Contents |
|---|---|
| `meta` | Vertical key, name, locales, semantic version, compatibility notes |
| `entities` | Core entity bindings (`listing`, `order`, `customer`) and custom entities (`warranty`, `inspection`, `test_drive`, `viewing`, …) |
| `attributes` | Typed fields per entity, as references to the attribute library plus local definitions |
| `rules` | Validation and conditional logic (JSONLogic): required-if, visible-if, cross-field checks, computed fields |
| `forms` | Ordered sections and fields per entity and per role (create listing, checkout, inquiry) |
| `search` | Searchable fields, filters (facets, ranges), sort options, ranking boosts |
| `workflows` | State machines per entity: states, transitions, guards, required permissions, side-effect events |
| `roles` · `permissions` | Extra tenant roles and permission bundles specific to the vertical (e.g. `inspector`) |
| `navigation` · `pages` | Menus and page layouts (block trees) for the customer and console bundles |
| `commerce` | Checkout mode (prepaid / cash on delivery / inquiry-only / booking), allowed payment method types, delivery on/off |
| `commission` | Default commission rules for the vertical and its categories (`08_LEDGER.md` §6) |
| `notifications` | Template keys and default channel routing per event |
| `ai` | Enabled AI tools, listing-generator hints, attribute extraction prompts, Amharic synonyms |
| `analytics` | KPI definitions (events → metrics) shown in the merchant dashboard |
| `features` | Default feature flags (`reviews`, `trade_in`, `test_drive`, …) |
| `extensions` | Keys of registered code extensions used by this blueprint (`imei.luhn`, `vin.checkdigit`) |

## 2. Storage model (ADR-006)

**There is no per-blueprint DDL.** Creating a vertical never runs `CREATE TABLE`.

| Data | Where |
|---|---|
| Blueprint definition | `control.blueprint_versions.definition` (`jsonb`). It is validated against the **meta-schema** (JSON Schema 2020-12). Published versions are **immutable**, protected by a trigger, and carry a `content_hash`. |
| Core entities | Real tables: `commerce.listings`, `commerce.orders`, `commerce.customers`, … These have fixed platform columns (ids, tenant, price, stock, status) plus `attributes jsonb` for blueprint fields. |
| Custom entities | `commerce.entity_records(tenant_id, id, entity_key, blueprint_version_id, schema_rev, data jsonb, workflow_state, …)` |
| Filterable / sortable attributes | A typed projection, `commerce.attribute_values(tenant_id, record_type, record_id, attr_key, num_value numeric, text_value text, bool_value bool, date_value timestamptz, geo point)`, with B-tree indexes per value column prefixed by `(tenant_id, attr_key)`. The catalog module maintains it transactionally on every write. |
| Full-text search | `commerce.listings.search_doc tsvector` (weighted: title A, key attributes B, description C), built from the blueprint's `search.fields` |
| Fuzzy / typo-tolerant search | `pg_trgm` GIN indexes on a normalised `search_text` (title, brand, model, plus Latin transliteration of Amharic text), so `samsng`, `ሳምሰንግ` and `Samsung` all match (ADR-018) |

Why this model:

- The platform owns every column that money, stock and isolation depend on, so these can never be misconfigured by a blueprint.
- `jsonb` gives flexibility.
- The projection gives indexed range filters (`storage >= 128`, `mileage < 80000`) without EAV joins on the hot path.
- `SearchPort` can later swap the projection for OpenSearch (ADR-018).

## 3. Attribute library and types (directive §36)

`control.attribute_definitions` is a **platform-wide library** of reusable attributes, such as `brand`, `color`, `condition` and `warranty_months`. A blueprint references library attributes by key and can add local ones.

| Type | Stored as | Projection | Notes |
|---|---|---|---|
| `string` / `text` | string | `text_value` | `text` is long-form, not filterable |
| `number` | `{"v": "12.5"}` string decimal, or integer | `num_value` | Has `scale`, `min`, `max` and an optional `unit` |
| `boolean` | bool | `bool_value` | |
| `enum` / `multi_enum` | option key(s) | `text_value` (one row per value) | Options are localised (`en`, `am`) with stable keys |
| `date` / `datetime` | ISO-8601 | `date_value` | |
| `location` | `{lat, lng, area_code, label}` | `geo` + `text_value` for the area | The admin-area tree (region → city → sub-city) is platform data |
| `image` / `document` | Object-store asset id(s) | — | Upload goes through the media pipeline (`09` §8) |
| `money` | `{amount_minor, currency}` | `num_value` (minor units) | Never a float |
| `measurement` | `{value, unit}` | `num_value` normalised to the base unit | Unit conversion table, e.g. `km`/`mi`, `m²` |
| `relation` | Referenced record id(s) | `text_value` | The target must be in the same tenant, enforced by the validator |
| `phone` / `email` / `url` | string | — | Format validators |

Each attribute has these properties: `required`, `searchable`, `filterable`, `sortable`, `unique_within_tenant` (for example IMEI), `pii`, `visibility` (public / staff / owner), `ai_extractable`, and `unit`. `pii` controls redaction in logs, exports and AI context.

## 4. Rules: JSONLogic (ADR-007)

JSONLogic is chosen because it is data (serialisable and diffable), sandboxed (no arbitrary code), and has mature, equivalent evaluators in Python and TypeScript. The browser evaluates rules for UX. **The server re-evaluates them as the authority.**

Directive §37 example: if `condition = used`, then `battery_health` is required.

```yaml
rules:
  - id: used_phone_battery_required
    applies_to: listing
    when: { "==": [ { "var": "condition" }, "used" ] }
    then:
      require: [battery_health]
      show: [battery_health, cosmetic_grade]
  - id: battery_health_range
    applies_to: listing
    assert: { "<=": [0, { "var": "battery_health" }, 100] }
    message: { en: "Battery health must be 0–100%", am: "የባትሪ ጤንነት ከ0–100% መሆን አለበት" }
```

Evaluation order: type validation → rules → extensions (§8) → uniqueness constraints. All errors are returned together, keyed by field.

## 5. Example: Phones v1.0 (abridged)

```yaml
meta:
  vertical: phones
  version: 1.0.0
  name: { en: Phones, am: ስልኮች }
entities:
  listing:
    kind: core
    attributes:
      - ref: brand                 # library enum (Samsung, Apple, Tecno, Infinix, …)
      - ref: model
      - { key: storage_gb, type: enum, options: [32, 64, 128, 256, 512, 1024], filterable: true }
      - { key: ram_gb, type: enum, options: [2, 3, 4, 6, 8, 12, 16], filterable: true }
      - ref: condition             # new | used | refurbished
      - { key: battery_health, type: number, unit: "%", min: 0, max: 100, filterable: true }
      - { key: imei, type: string, visibility: staff, unique_within_tenant: true, pii: false,
          extensions: [imei.luhn] }
      - ref: color
      - { key: warranty_months, type: number, min: 0, max: 36 }
  warranty:
    kind: custom
    attributes:
      - { key: listing, type: relation, target: listing }
      - { key: starts_on, type: date }
      - { key: months, type: number }
  accessory: { kind: custom, attributes: [ … ] }
search:
  text_fields: [title, brand, model, description]
  filters: [brand, storage_gb, ram_gb, condition, price, battery_health, color]
  sorts: [newest, price_asc, price_desc, relevance]
commerce:
  checkout_modes: [prepaid, cash_on_delivery]
  delivery: enabled
workflows:
  order:
    initial: created
    states: [created, paid, seller_confirmed, packed, courier_assigned, picked_up, delivered, completed, cancelled]
    transitions:
      - { from: created, to: paid, trigger: event.PaymentCompleted }            # system-only
      - { from: paid, to: seller_confirmed, permission: orders.fulfil }
      - { from: seller_confirmed, to: packed, permission: orders.fulfil }
      - { from: packed, to: courier_assigned, trigger: event.CourierAssigned }
      - { from: courier_assigned, to: picked_up, permission: delivery.update }
      - { from: picked_up, to: delivered, permission: delivery.update, requires: [proof_of_delivery] }
      - { from: delivered, to: completed, trigger: timer.P3D, guard: { "!": { "var": "dispute_open" } } }
      - { from: [created, paid, seller_confirmed], to: cancelled, permission: orders.cancel,
          effects: [refund_if_paid] }
commission:
  default: { rate_bps: 500 }                          # 5.00% (08_LEDGER §6)
features: { trade_in: false, repair: false, reviews: true }
extensions: [imei.luhn]
```

A Cars blueprint uses the **same engine** with a different definition: entities `vehicle`, `inspection`, `inquiry` and `test_drive`; attributes `make`, `model`, `year`, `mileage` (measurement), `transmission`, `fuel`, `engine_cc`, `vin` (extension `vin.checkdigit`) and `condition`; `commerce.checkout_modes: [inquiry_only, deposit]`; and an inquiry workflow `new → contacted → test_drive_scheduled → negotiation → sold | lost`.

## 5a. Core order lifecycle vs vertical workflow (Permanent Command §17)

Vertical workflows must never corrupt the core order model, so an order carries **two separate state fields**:

| Field | Owner | Values | Changed by |
|---|---|---|---|
| `orders.status` | Platform (`orders` module) | `created → pending_payment → paid → in_progress → completed`, plus `cancelled`. Inquiry-only verticals skip payment: `created → in_progress → completed` / `cancelled`. | Platform commands and events only, such as `PaymentCompleted` → `paid`. Every transition is deterministic and validated. |
| `orders.workflow_state` | Blueprint workflow | Vertical steps, e.g. retail `confirmed → processing → ready → shipped → delivered`, or property `inquiry → viewing_requested → viewing_completed → offer → negotiation → contract` | Workflow transitions with permission and JSONLogic guards |
| `orders.payment_status` | `payments` module (via events) | Mirrors the payment intent: `none`, `pending`, `succeeded`, `partially_refunded`, `refunded`, `failed` | Payment events only |

**Coupling rules, enforced by the workflow compiler:**

- A workflow declares which of its states map to the core `in_progress` or `completed`.
- A workflow state marked `requires_payment` cannot be entered unless `payment_status = succeeded`, when the checkout mode is prepaid.
- Reaching a state mapped to `completed` sets `orders.status = completed`, which creates review eligibility and starts payout-eligibility timers.
- Cancelling from any workflow state goes through the platform `cancel` command, which handles refunds and stock release. A workflow can *offer* cancellation but cannot implement it.

## 6. Versioning (directive §5)

| Bump | Meaning | Examples | Existing tenants |
|---|---|---|---|
| **Patch** `1.0.x` | Presentation only | Labels, translations, form order, menu text | Upgrade is always compatible; can be bulk-applied |
| **Minor** `1.x.0` | Additive and backward-compatible | New *optional* attribute, new enum option, new filter, new workflow state not on existing paths | Compatible; bulk-apply with preview |
| **Major** `x.0.0` | Breaking | Removed or renamed attribute, type change, attribute becoming required, enum option removed, workflow transition removed | Requires a **migration plan** with data transforms |

Lifecycle: `draft → in_review → published → deprecated → retired`.

- Only `draft` versions are editable.
- `publish` runs the compatibility checker against the previous version. If a change is breaking, the checker **forces** the major bump; the author cannot mislabel it.
- A `retired` version cannot be pinned by *new* tenants. Tenants still on it keep working until they are migrated.

**Reconciling "Super Admin adds Battery Health and the marketplace immediately understands it" with "existing merchants never change automatically":**

1. Adding the attribute edits a draft.
2. Publishing it creates version 1.1 (minor, compatible).
3. **New** merchants get 1.1 immediately.
4. Existing merchants appear in an "Upgrade available: 1.0 → 1.1 (compatible)" queue. The Super Admin can apply it to all of them *in one action*, after the preview.

Nothing changes for an existing tenant without an explicit, audited action, but that action can be one click for a thousand tenants.

## 7. Migrations between versions

`control.blueprint_migration_plans(from_version, to_version, steps jsonb, …)`. The available step types are:

| Step | Effect on data |
|---|---|
| `add_attribute` | None, or backfill a default |
| `rename_attribute` | Move the `jsonb` key and projection rows |
| `change_type` | Transform with a declared converter (e.g. `string→enum` mapping table, `number unit change`). Values that fail the transform go to a **quarantine list**. |
| `make_required` | Requires a backfill default or a per-record fix-up list; blocks until resolved |
| `remove_attribute` | Archive values into `migration_archive`; never delete on the first pass |
| `map_enum` | Old option → new option |
| `map_workflow_state` | Old state → new state for in-flight records. In-flight **orders with money** can only be mapped to states with equal financial meaning, and the checker enforces this. |

**Execution (per tenant, directive §5):**

1. **Preview (dry run).** Counts affected records and validation failures, and produces a sample diff. No writes.
2. **Compatibility check.** Refuse if the tenant uses features that the target version removes without a mapping.
3. **Snapshot.** Before rewriting a record, copy its prior `attributes`/`data` into `blueprint_migration_log(run_id, record_id, before jsonb)`.
4. **Apply.** Process records in batches of 500 inside transactions. Records carry `schema_rev`, and readers accept both revisions during the run.
5. **Validate.** Re-run all rules on all migrated records.
6. **Switch.** Update `tenants.blueprint_version_id` and increment `config_version`.
7. **Log.** Record the result in `blueprint_migration_runs(status, counts, errors, started_by, …)`.
8. **Rollback.** Restore from the snapshot rows and reset the pin. This is available until the run is *finalised*, 30 days by default.
9. **Failure recovery.** Runs are resumable: each batch is idempotent, keyed by `(run_id, batch_no)`. A failed run leaves the tenant on the old pin, and readers are unaffected.

## 8. Vertical-specific logic: extensions, not `if vertical == …`

Code that is genuinely vertical-specific is written as a **registered extension**:

```python
@extension("imei.luhn", kind="attribute_validator")
def validate_imei(value: str) -> ValidationResult: ...

@extension("parts.fitment", kind="search_filter")
class FitmentFilter: ...          # vehicle make/model/year → compatible part numbers
```

A blueprint lists the extension keys it uses. Publishing fails if a referenced key is not registered in the running release. Examples: IMEI Luhn check, VIN check digit, spare-part fitment, event seat maps, beauty appointment calendars, course progress. Rule: **no platform module branches on a vertical key.** CI checks this with a grep for vertical literals outside `extensions/` and `blueprints/`.

## 9. Compilation and caching

A published version is **compiled** once into:

- a server validator bundle (types, rules and extensions)
- per-role form schemas
- search configuration
- workflow graphs
- the client manifest fragment

These artefacts are cached by `content_hash` and are immutable. Tenants pinned to the same version share the same compiled artefacts. That sharing is why the cost of a blueprint grows with its number of versions, not with its number of tenants.

## 10. Seed blueprints in git

`blueprints/<vertical>/<version>.yaml` are the **source-controlled seeds**. The CLI command `arada blueprint import` loads them as drafts, and publishing still happens through the audited console flow. Phase 1 ships the engine with a test blueprint. Phase 5 ships **Phones v1.0** production-grade as the reference vertical (ADR-028). The other 17 verticals follow in Phase 7; each one is a YAML file plus any extensions it needs.
