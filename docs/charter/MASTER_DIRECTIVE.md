# MASTER CEO / CTO DIRECTIVE

> Stored verbatim (whitespace normalised). Issued by the owner on 2026-09-26.
> Where this conflicts with `PERMANENT_COMMAND.md`, the Permanent Command governs — see `README.md` in this folder.

You are not being asked to build a simple marketplace.

You are the principal software architect, CTO, infrastructure architect, security architect, product architect, DevOps engineer, database architect, financial-systems architect, Telegram Mini App architect, and technical project manager for a long-term company platform.

Your job is to design and build the system from the root so that it can eventually operate thousands of independent merchant businesses and many vertical marketplaces from one centrally controlled platform.

The human owner is the SUPER ADMIN.

Do not simplify the business idea into a normal e-commerce application.

Do not replace the architecture with a generic SaaS template.

Do not remove the multi-tenant, blueprint, merchant-isolation, Telegram, finance, payment, deployment, and Super Admin concepts.

You may improve the implementation, security, scalability, cost efficiency, and future extensibility, but you must remain faithful to the business model defined below.

---

# 1. CORE BUSINESS VISION

The product is a:

# TELEGRAM-FIRST MULTI-TENANT COMMERCE OPERATING SYSTEM

The platform allows the Super Admin to create:

* verticals
* category blueprints
* merchant blueprints
* merchant instances
* bots
* Telegram Mini Apps
* customer storefronts
* merchant management portals
* finance portals
* payment configurations
* delivery configurations
* analytics
* AI capabilities
* advertising capabilities
* notifications
* workflows

from one centralized platform.

The platform must support:

* Phones
* Computers
* Electronics
* Fashion
* Furniture
* Cars
* Spare Parts
* Residential Property
* Commercial Property
* Services
* Food
* Beauty
* Education
* Construction
* Agriculture
* Jobs
* Courses
* Events

The architecture must allow additional verticals to be added later without rewriting the platform core.

---

# 2. THE MOST IMPORTANT BUSINESS MODEL

There are THREE levels.

## LEVEL 1 — PLATFORM

Owned and controlled by the Super Admin.

Contains:

* identity
* tenancy
* blueprint engine
* deployment engine
* payment orchestration
* financial ledger
* orders
* notifications
* search
* AI
* analytics
* advertising
* delivery
* support
* security
* audit
* infrastructure management

---

## LEVEL 2 — VERTICAL

Examples:

* Phones
* Cars
* Property
* Fashion
* Food
* Jobs

Each vertical has:

* its own blueprint
* entities
* attributes
* workflows
* forms
* rules
* commission rules
* business logic extensions
* UI configuration
* AI configuration
* notification templates
* analytics definitions

---

## LEVEL 3 — MERCHANT

A merchant is an independent business instance created from a vertical blueprint.

Example:

PHONE BLUEPRINT

can create:

* Merchant A
* Merchant B
* Merchant C
* Merchant D
* Merchant E

Each merchant must have logically isolated:

* customers
* products
* inventory
* orders
* payments
* financial records
* staff
* permissions
* settings
* branding
* analytics
* notifications
* bot configuration
* Mini App configuration

The merchant must feel like an independent company even though the underlying platform is shared.

---

# 3. THE BUSINESS FACTORY

The Super Admin must have:

# CREATE BUSINESS

Example workflow:

1. Select vertical
2. Select blueprint
3. Select blueprint version
4. Enter business name
5. Assign owner
6. Configure branding
7. Configure bot
8. Configure Mini App
9. Configure payments
10. Configure delivery
11. Configure commissions
12. Configure features
13. Configure staff
14. Configure domain/subdomain
15. Provision tenant
16. Run validation
17. Deploy
18. Activate

The system must automatically create the required resources.

Example:

PHONE BLUEPRINT v1.0

↓

CREATE MERCHANT

↓

ABC PHONES

↓

Provision:

* tenant
* database records
* roles
* permissions
* storefront
* Mini App configuration
* bot configuration
* payment configuration
* finance configuration
* notifications
* analytics
* monitoring
* subdomains
* deployment metadata

---

# 4. BLUEPRINT ENGINE

This is one of the most important parts of the platform.

Do NOT hard-code every vertical separately.

Create a configurable:

# BLUEPRINT ENGINE

A blueprint defines:

* entities
* fields
* attributes
* forms
* filters
* search fields
* workflows
* roles
* permissions
* menus
* pages
* business rules
* commission rules
* payment methods
* notifications
* AI tools
* analytics
* feature flags

Example:

PHONE BLUEPRINT:

Entities:

* product
* order
* customer
* seller
* warranty
* accessory

Attributes:

* brand
* model
* storage
* RAM
* condition
* IMEI
* color
* warranty

CAR BLUEPRINT:

Entities:

* vehicle
* inspection
* inquiry
* test_drive

Attributes:

* make
* model
* year
* mileage
* transmission
* fuel
* engine
* VIN
* condition

PROPERTY BLUEPRINT:

* property
* unit
* viewing
* inquiry
* offer
* contract

Attributes:

* location
* bedrooms
* bathrooms
* area
* floor
* parking
* furnished
* sale_or_rent

The platform core remains the same.

Only the blueprint changes.

---

# 5. BLUEPRINT VERSIONING

Blueprints must be versioned.

Example:

PHONE:

* v1.0
* v1.1
* v1.2
* v2.0

Existing merchants must NOT automatically break when a blueprint changes.

A merchant must retain its current blueprint version until an explicit migration is performed.

Support:

* migration plans
* compatibility checks
* rollback
* upgrade preview
* migration logs
* failed migration recovery

---

# 6. MULTI-TENANCY

Tenant isolation is mandatory.

Every tenant-owned resource must have a tenant identity.

Example:

products:

* id
* tenant_id
* category
* name
* price
* stock
* status

orders:

* id
* tenant_id
* customer_id
* amount
* status

payments:

* id
* tenant_id
* order_id
* provider
* provider_reference
* status

Never trust the frontend to provide tenant authorization.

Tenant resolution must happen server-side.

Use defense in depth:

* application authorization
* RBAC
* tenant context
* PostgreSQL Row-Level Security where appropriate
* database constraints
* service-level authorization
* audit logging

A tenant must NEVER be able to access another tenant's:

* products
* customers
* orders
* payments
* finance
* staff
* analytics
* secrets
* configuration

---

# 7. ISOLATION TIERS

Do not force every merchant into expensive dedicated infrastructure.

Support three isolation tiers.

## STARTER

Shared infrastructure.

## PRO

More isolated database/schema/resources.

## ENTERPRISE

Dedicated database and optionally dedicated application workers or infrastructure.

This keeps the platform inexpensive for small merchants while allowing large merchants to scale independently.

---

# 8. ONE PLATFORM CORE

Do NOT build 18 unrelated applications.

Build reusable engines:

* identity engine
* tenant engine
* blueprint engine
* catalog engine
* order engine
* payment engine
* ledger engine
* notification engine
* bot engine
* Mini App engine
* workflow engine
* search engine
* delivery engine
* review engine
* promotion engine
* advertising engine
* analytics engine
* AI engine
* deployment engine
* audit engine

Verticals configure these engines.

---

# 9. ONE FRONTEND ENGINE

Do not create completely separate codebases for:

phone-app
car-app
fashion-app
food-app

Create one configurable application runtime.

The runtime receives:

* tenant
* vertical
* blueprint
* theme
* feature flags
* permissions
* localization
* workflow

and renders the correct business.

Therefore:

PHONE STORE

and

CAR STORE

can use the same frontend engine while looking and behaving differently.

---

# 10. EVERY MERCHANT MUST FEEL INDEPENDENT

Each merchant should have its own:

* bot identity
* Mini App experience
* storefront
* branding
* customer experience
* management portal
* finance portal
* payment configuration
* order system
* notifications
* analytics

But do NOT duplicate the entire backend infrastructure for every merchant.

The merchant is a logical business instance running on the shared Commerce OS.

---

# 11. TELEGRAM ARCHITECTURE

Telegram is the first-class customer channel.

Required flow:

CUSTOMER

↓

Telegram

↓

Merchant Bot

↓

Merchant Mini App

↓

Cloudflare public hostname

↓

Cloudflare Tunnel

↓

Reverse proxy / gateway

↓

Tenant resolver

↓

Commerce API

↓

Domain service

↓

Database / Redis / event system

The Mini App must validate Telegram authentication server-side.

Never trust:

Telegram.WebApp.initDataUnsafe

as authentication.

Only validated Telegram initData may establish the authenticated Telegram user context.

Telegram currently documents server-side validation of Mini App initData using HMAC verification and recommends checking auth freshness. Follow the current Telegram documentation rather than inventing an authentication mechanism.

---

# 12. TELEGRAM BOT PER MERCHANT

Each merchant may have its own Telegram bot.

The platform must have a Bot Provisioning/Management system.

Store:

* bot ID
* bot username
* encrypted bot token
* Mini App configuration
* webhook state
* commands
* branding
* notification configuration
* merchant ID

Never expose bot tokens to frontend applications.

---

# 13. TELEGRAM MINI APP PER MERCHANT

Each merchant receives its own Mini App identity/configuration.

Support:

* Main Mini App
* direct links
* deep links
* startapp parameters
* referral parameters
* product links
* campaign links
* merchant links
* order links
* shared/group contexts where appropriate

Example conceptual link:

`t.me/MerchantBot?startapp=product_123`

The backend must interpret the context safely.

Do not trust arbitrary tenant IDs or product IDs supplied by the client.

Resolve the requested resource through authorized tenant context.

---

# 14. ONE DOMAIN ONLY

THIS IS NON-NEGOTIABLE.

The company owns/uses ONE root domain.

Do not introduce:

* another root domain
* another production domain
* another public IP
* separate public VPS IPs
* random domains for tenants

The existing root domain is managed through Cloudflare.

The domain registrar remains at Hostinger if that is the current registration arrangement.

Cloudflare becomes the authoritative DNS layer.

The architecture must use:

HOSTINGER REGISTRATION

↓

CLOUDFLARE NAMESERVERS

↓

CLOUDFLARE DNS

↓

CLOUDFLARE TUNNEL

↓

LOCAL / PRIVATE VM INFRASTRUCTURE

Cloudflare requires the domain's nameservers to be pointed to the assigned Cloudflare nameservers for authoritative DNS and most Cloudflare services.

---

# 15. NO PUBLIC ORIGIN IP

The production application servers must NOT be directly exposed to the Internet.

Use:

Cloudflare

↓

Cloudflare Tunnel

↓

private/local infrastructure

Cloudflare Tunnel provides outbound-only connectivity and does not require a public IP or inbound firewall ports.

Do not design the application around:

server_public_ip:8000

Do not expose:

PostgreSQL
Redis
RabbitMQ
internal APIs
admin services
worker services

directly to the Internet.

---

# 16. ONE TUNNEL ARCHITECTURE

Prefer one logical production tunnel architecture initially.

Example conceptual routing:

`www.DOMAIN`

→ public web

`app.DOMAIN`

→ platform/customer runtime

`api.DOMAIN`

→ API gateway

`admin.DOMAIN`

→ Super Admin

`finance.DOMAIN`

→ central finance

`ops.DOMAIN`

→ operations

`status.DOMAIN`

→ status/health where appropriate

Merchant hostnames:

`m-{tenant}.DOMAIN`

`admin-{tenant}.DOMAIN`

`finance-{tenant}.DOMAIN`

or another deterministic naming convention.

The exact naming scheme must be finalized before implementation.

Do NOT create arbitrary hostnames manually.

Create a domain/subdomain provisioning service.

Cloudflare Tunnel supports multiple public hostnames mapped to different local services through one tunnel configuration.

---

# 17. CLOUDflare DNS AUTOMATION

The Super Admin must eventually be able to create a merchant and automatically provision the required Cloudflare DNS/Tunnel routing.

Do not make the human manually create dozens of DNS records.

Build:

Cloudflare DNS/Tunnel Provider

with:

* API integration
* idempotent operations
* DNS record creation
* DNS record verification
* hostname verification
* tunnel route management
* deletion protection
* audit logging

Every operation must be safe to retry.

---

# 18. SUBDOMAIN STRATEGY

The platform must support deterministic subdomains.

Do not create names based directly on arbitrary user input.

Generate safe identifiers.

Example:

merchant:

ABC Phones

tenant slug:

`abc-phones`

public host:

`abc-phones.DOMAIN`

admin:

`admin-abc-phones.DOMAIN`

finance:

`finance-abc-phones.DOMAIN`

or a more compact architecture such as:

`abc-phones.DOMAIN`

with role/path routing.

The architecture team must evaluate both approaches for:

* security
* TLS
* Cloudflare
* caching
* tenant isolation
* maintainability
* SEO
* cost
* operational complexity

Then document the decision.

---

# 19. REVERSE PROXY

Use a single controlled ingress layer.

Possible architecture:

Cloudflare Tunnel

↓

Traefik / equivalent reverse proxy

↓

Gateway

↓

Internal services

The reverse proxy must never expose internal services accidentally.

Default unmatched routes must return an appropriate error.

---

# 20. INFRASTRUCTURE

The system must be designed for NON-CLOUD / SELF-HOSTED deployment.

Primary deployment target:

local/private VMs.

Use:

* Linux
* Docker
* Docker Compose initially
* Ansible
* Terraform where useful
* cloud-init where useful
* Git
* CI/CD

Do not introduce Kubernetes simply because it sounds scalable.

Start with the simplest architecture that can scale.

Kubernetes may be introduced later when actual capacity/operational requirements justify it.

---

# 21. INITIAL INFRASTRUCTURE

Design for:

VM(s)

↓

Docker

↓

Reverse Proxy

↓

Application services

↓

PostgreSQL

↓

Redis

↓

Workers

↓

Monitoring

The system must remain operational if everything is deployed on a small number of VMs.

Every service must have explicit:

* CPU requirements
* RAM requirements
* storage requirements
* network requirements
* health checks
* restart policy
* dependency definition

---

# 22. DATABASE

Primary database:

PostgreSQL.

Use migrations.

Never modify production schema manually without migration tracking.

Requirements:

* UUID/appropriate IDs
* tenant isolation
* foreign keys
* unique constraints
* indexes
* transactional boundaries
* audit fields
* soft deletion only where appropriate
* immutable financial records
* timestamps
* optimistic concurrency where needed

---

# 23. CACHE

Use Redis where justified for:

* sessions
* rate limits
* queues
* temporary state
* caching
* distributed locks
* idempotency windows

Do not put authoritative financial data only in Redis.

PostgreSQL remains authoritative for persistent business state.

---

# 24. EVENT SYSTEM

Design an internal event architecture.

Examples:

`TenantCreated`

`MerchantProvisioned`

`ProductCreated`

`OrderCreated`

`PaymentInitiated`

`PaymentAuthorized`

`PaymentFailed`

`PaymentCompleted`

`RefundCreated`

`ShipmentCreated`

`ShipmentDelivered`

`ReviewSubmitted`

`PayoutCreated`

`CampaignCreated`

Events must be:

* versioned
* traceable
* idempotent
* tenant-aware

---

# 25. OUTBOX PATTERN

For important domain events, use a reliable transaction/outbox pattern.

Do not:

1. write database
2. separately publish event
3. hope both succeed

Instead guarantee consistency between business transaction and event publication.

---

# 26. ORDERS

Order engine must support:

* creation
* pricing
* taxes/fees where applicable
* discounts
* payment state
* fulfillment
* cancellation
* refund
* dispute
* delivery
* completion

Orders must have explicit state machines.

Never allow random status changes.

---

# 27. MONEY

This system will eventually handle significant amounts of money.

Treat money as a first-class domain.

Do not use floating-point arithmetic for monetary values.

Use:

* integer minor units where appropriate
* explicit currency
* immutable transaction records
* idempotency
* provider references
* reconciliation
* ledger entries

---

# 28. DOUBLE-ENTRY LEDGER

Build a proper ledger.

Example:

Customer payment:

DEBIT:

customer/platform clearing account

CREDIT:

merchant payable

platform fee

delivery payable

etc.

Do not calculate historical finance only from mutable order records.

The ledger must become the authoritative accounting trail for platform-controlled financial movements.

---

# 29. PAYMENT ORCHESTRATION

Do not hard-code the platform to one payment provider.

Create:

Payment Provider Interface

Then adapters for supported providers.

Potential providers can be integrated according to availability, licensing, merchant eligibility and applicable Ethiopian requirements.

Never assume that your platform itself may legally hold or transfer customer funds without checking the applicable Ethiopian regulatory framework.

The National Bank of Ethiopia publishes the National Payment System legal framework, including the National Payment System Proclamation and amendment.

---

# 30. PAYMENT IDEMPOTENCY

Every payment operation must support:

* idempotency key
* provider reference
* transaction ID
* event ID
* reconciliation ID

If a provider sends the same callback five times, the system must not create five payments.

---

# 31. FINANCE PORTAL

Every merchant receives a finance interface.

Show:

* gross sales
* platform fees
* commissions
* payment fees
* delivery fees
* refunds
* adjustments
* payable balance
* payouts
* transaction history
* ledger
* reconciliation status

Central Super Admin finance must see the whole platform.

Vertical finance administrators must see only authorized vertical data.

Merchant finance users must see only their merchant.

---

# 32. ROLE HIERARCHY

Use hierarchical RBAC.

At minimum:

SUPER_ADMIN

PLATFORM_ADMIN

PLATFORM_FINANCE

PLATFORM_SUPPORT

VERTICAL_ADMIN

VERTICAL_FINANCE

TENANT_OWNER

TENANT_ADMIN

TENANT_FINANCE

TENANT_MANAGER

TENANT_STAFF

CUSTOMER

DELIVERY_AGENT

SERVICE_PROVIDER

and future roles.

Permissions should be granular.

Example:

`orders.read`

`orders.create`

`orders.cancel`

`orders.refund`

`payments.read`

`payments.refund`

`finance.read`

`finance.export`

`tenant.manage`

`blueprint.manage`

---

# 33. SUPER ADMIN

The Super Admin must control:

* verticals
* blueprints
* blueprint versions
* tenants
* merchants
* users
* roles
* permissions
* payments
* finance
* commissions
* payouts
* bots
* Mini Apps
* domains
* deployments
* infrastructure
* feature flags
* AI
* advertisements
* support
* security
* audit
* system health

This is the company's operating console.

---

# 34. VERTICAL ADMIN

Vertical administrators may manage their vertical only.

Example:

PHONE_VERTICAL_ADMIN

can manage:

* phone blueprint
* phone categories
* phone attributes
* phone merchants
* phone analytics
* phone rules

but cannot automatically access:

* cars
* property
* food

unless explicitly authorized.

---

# 35. MERCHANT ADMIN

Merchant administrators manage only their merchant.

Dashboard:

* products
* inventory
* orders
* customers
* staff
* payments
* finance
* delivery
* promotions
* reviews
* analytics
* settings

---

# 36. DYNAMIC ATTRIBUTE ENGINE

Super Admin must be able to create fields without changing application source code.

Example:

CREATE ATTRIBUTE

Name:

Battery Health

Type:

number

Unit:

%

Required:

yes

Searchable:

yes

Filterable:

yes

Then the phone marketplace immediately understands that attribute.

The system must support:

* string
* number
* boolean
* enum
* multi-select
* date
* datetime
* location
* image
* document
* money
* measurement
* relation

---

# 37. DYNAMIC FORM ENGINE

The blueprint controls:

* fields
* order
* required/optional
* validation
* conditional fields
* visibility
* permissions

Example:

If:

`condition = used`

then:

`battery_health`

becomes required.

---

# 38. WORKFLOW ENGINE

Different verticals require different workflows.

Phones:

Created

→ Paid

→ Seller confirmed

→ Packed

→ Courier assigned

→ Picked up

→ Delivered

→ Completed

Property:

Inquiry

→ Viewing

→ Offer

→ Negotiation

→ Contract

→ Completed

Jobs:

Applied

→ Screening

→ Interview

→ Offer

→ Accepted

The platform must support configurable workflow state machines.

---

# 39. SEARCH

Start with PostgreSQL search if sufficient.

Design the abstraction so OpenSearch or another search engine can be introduced later.

Search must support:

* text
* category
* price
* location
* seller
* attributes
* availability
* rating
* condition
* relevance

---

# 40. AI LAYER

Create a central AI gateway.

AI must NEVER have unrestricted database access.

AI should use explicit tools.

Examples:

`search_products`

`compare_products`

`get_order`

`get_customer`

`create_listing_draft`

`generate_description`

`recommend_products`

`get_merchant_metrics`

`create_campaign_draft`

Every tool must enforce authorization and tenant context.

---

# 41. AI SHOPPING AGENT

Customer:

"Find a laptop for programming under 50,000 ETB."

AI:

1. identifies requirements
2. searches authorized inventory
3. compares products
4. explains results
5. asks for confirmation
6. prepares checkout

Never silently purchase anything.

Financial actions require explicit user confirmation.

---

# 42. AI MERCHANT ASSISTANT

Merchant:

"How did I perform this week?"

AI provides:

* revenue
* orders
* conversion
* best products
* low stock
* refund rate
* customer trends
* actionable suggestions

---

# 43. AI SUPER ADMIN COPILOT

Super Admin can ask:

"Which merchants had payment failures today?"

"Which tenants have unusual refund activity?"

"Which blueprint version generated the most errors?"

"Show merchants whose order volume dropped."

AI must retrieve data through authorized tools and clearly distinguish observed data from inference.

---

# 44. TRUST ENGINE

Create a platform trust system.

Track:

* transaction history
* successful orders
* cancellations
* disputes
* response time
* verification status
* account age
* customer ratings
* suspicious activity

Do not create arbitrary reputation scores without documented methodology.

---

# 45. FRAUD / RISK ENGINE

Eventually detect:

* abnormal payment patterns
* duplicate listings
* suspicious pricing
* account abuse
* repeated cancellations
* fake reviews
* suspicious refunds
* bot abuse
* credential abuse

The risk engine should produce signals, not silently punish legitimate users without explainable rules and appropriate review paths.

---

# 46. DELIVERY ENGINE

Eventually support:

* delivery zones
* delivery pricing
* courier assignment
* pickup
* proof of delivery
* status
* customer notifications
* merchant notifications
* courier earnings

The delivery engine must remain optional by vertical.

---

# 47. REVIEW ENGINE

Support:

* product reviews
* seller reviews
* service reviews
* delivery reviews
* event reviews

Prevent duplicate or fraudulent reviews.

Only eligible transactions should normally create review eligibility.

---

# 48. PROMOTION ENGINE

Support:

* coupons
* discounts
* bundles
* featured listings
* flash sales
* merchant campaigns
* referral campaigns

Promotions must be tenant-scoped.

---

# 49. ADVERTISING ENGINE

Future:

Merchant purchases:

* featured listing
* category placement
* sponsored search
* campaign
* promotion

Build advertising as a separate domain rather than mixing it into product pricing.

---

# 50. REFERRAL ENGINE

Support:

* referral links
* attribution
* campaign tracking
* reward rules
* fraud controls

Use Telegram deep-link/startapp mechanisms where appropriate.

Do not allow users to manipulate referral attribution simply by changing client parameters.

---

# 51. ANALYTICS

Every important event should eventually feed analytics.

Track:

* visitors
* searches
* product views
* add-to-cart
* checkout
* payment success
* payment failure
* order completion
* cancellation
* refunds
* merchant revenue
* platform revenue
* campaign performance

All analytics must respect tenant isolation.

---

# 52. OBSERVABILITY

Every request must carry:

* request_id
* trace_id
* tenant_id
* user_id where available

Use:

* OpenTelemetry
* Prometheus
* Grafana
* Loki or equivalent logs

Monitor:

* latency
* errors
* database
* Redis
* queues
* payments
* bots
* Mini Apps
* Cloudflare ingress
* tenant health
* worker health

---

# 53. SECURITY

Implement from day one:

* secure secret management
* encrypted secrets
* TLS
* RBAC
* tenant isolation
* RLS where appropriate
* rate limiting
* CSRF protection where applicable
* secure cookies
* short-lived access tokens
* refresh rotation
* webhook signature validation
* Telegram initData validation
* audit logging
* brute-force protection
* admin MFA
* backup encryption
* least privilege
* dependency scanning
* container scanning
* SAST
* secret scanning

Never commit:

* bot tokens
* API keys
* database passwords
* Cloudflare API tokens
* payment credentials

---

# 54. ADMIN SECURITY

Super Admin is the most sensitive account.

Require stronger controls:

* MFA
* short sessions
* device/session management
* audit logging
* reauthentication for sensitive actions
* confirmation for financial changes
* confirmation for destructive actions
* optional emergency break-glass account

---

# 55. DOMAIN SECURITY

Cloudflare should be the public security boundary.

Use:

* HTTPS
* WAF where appropriate
* rate limiting
* bot protection where appropriate
* security headers
* strict origin access
* no public origin IP

The infrastructure should not depend on obscurity.

---

# 56. FILE STORAGE

Do not store large images directly in PostgreSQL.

Create an object-storage abstraction.

Potential self-hosted implementation:

S3-compatible storage such as MinIO.

The application should interact through an abstraction so the storage backend can change later.

Images must have:

* size limits
* content validation
* MIME validation
* safe filenames
* thumbnail generation
* malware scanning strategy where appropriate
* access control

---

# 57. NOTIFICATION ENGINE

Central notification service.

Channels:

* Telegram bot
* Mini App notification mechanisms
* email where applicable
* SMS through supported providers
* internal notifications

Notifications must be tenant-aware.

---

# 58. SUPPORT SYSTEM

Eventually create:

* customer support
* merchant support
* ticketing
* dispute management
* escalation
* internal notes
* audit trail

---

# 59. CUSTOMER IDENTITY

Telegram should be the first identity channel.

But the platform identity layer must not be permanently hard-coded to Telegram.

Design:

IDENTITY

↓

Telegram provider

future:

Web

Mobile

Other identity providers

This preserves future expansion.

---

# 60. TELEGRAM MUST BE THE FIRST CHANNEL, NOT THE ENTIRE BACKEND

The backend must be independent of Telegram.

Future channels:

* Telegram
* web
* Android
* iOS
* APIs
* partner integrations

The same Commerce OS should serve them.

---

# 61. COST-EFFECTIVE INFRASTRUCTURE RULE

Never optimize for theoretical scale at the expense of current economics.

Use:

* shared infrastructure
* multi-tenancy
* horizontal scaling when required
* Docker
* PostgreSQL
* Redis
* object storage
* one Cloudflare zone
* one tunnel architecture
* automated provisioning

Do not create:

* one VM per merchant
* one database per merchant by default
* one Redis per merchant
* one backend deployment per merchant
* one root domain per merchant

unless an enterprise isolation tier specifically requires it.

---

# 62. DEPLOYMENT ENGINE

The Super Admin should eventually be able to see:

Tenant:

ABC Phones

Deployment:

READY

Version:

2026.09.1

Health:

HEALTHY

Bot:

CONNECTED

Mini App:

HEALTHY

API:

HEALTHY

Database:

HEALTHY

Payment:

CONNECTED

Domain:

ACTIVE

---

# 63. INFRASTRUCTURE AS CODE

All infrastructure must eventually be reproducible.

Use:

* Docker Compose for initial deployment
* Ansible for server configuration
* Terraform where it provides real value
* Git-based configuration
* migration automation
* CI/CD

A new machine should not require undocumented manual commands.

---

# 64. ENVIRONMENT SEPARATION

At minimum:

development

staging

production

Never let development accidentally use production payment credentials or production databases.

---

# 65. DATABASE MIGRATIONS

Every schema change must have:

* migration
* rollback strategy where practical
* compatibility consideration
* tests

Do not edit production database manually as normal workflow.

---

# 66. TESTING

Require:

* unit tests
* integration tests
* API tests
* database tests
* tenant-isolation tests
* authentication tests
* authorization tests
* payment tests
* webhook tests
* Telegram authentication tests
* Mini App tests
* end-to-end tests
* migration tests
* deployment smoke tests

Most importantly:

# TEST CROSS-TENANT ISOLATION

Create tests that deliberately attempt:

Tenant A → access Tenant B

and verify denial.

---

# 67. FINANCIAL TESTING

Test:

* duplicate payment
* delayed callback
* callback out of order
* refund after completion
* partial refund
* failed payment
* duplicate webhook
* timeout
* provider reconciliation
* currency mismatch
* concurrent checkout

---

# 68. DISASTER RECOVERY

Design:

* database backups
* restore procedures
* configuration backup
* secrets recovery process
* migration recovery
* infrastructure rebuild

Document:

RPO

RTO

restore procedure

and regularly test restoration.

---

# 69. FUTURE BUSINESS MODULES

Architecture must allow:

* loyalty
* subscriptions
* advertising
* affiliate commerce
* group buying
* wholesale
* B2B marketplace
* AI shopping
* AI business assistant
* property
* automotive
* services
* delivery
* ticketing
* education
* jobs

without rewriting the core platform.

---

# 70. VERTICAL-SPECIFIC FEATURES

Implement blueprint-specific features.

PHONE:

* IMEI
* warranty
* trade-in
* repair
* accessories
* condition
* device specifications

COMPUTERS:

* CPU
* RAM
* GPU
* storage
* compatibility
* configuration

ELECTRONICS:

* specifications
* compatibility
* accessories
* warranty

FASHION:

* size
* color
* variants
* collections

FURNITURE:

* dimensions
* material
* assembly
* delivery

CARS:

* VIN
* inspection
* test drive
* mileage
* maintenance history where available

SPARE PARTS:

* part number
* OEM
* aftermarket
* compatibility
* vehicle matching

PROPERTY:

* location
* map
* viewing
* property type
* bedrooms
* bathrooms
* area
* sale/rent

FOOD:

* menu
* modifiers
* ingredients
* preparation
* delivery

BEAUTY:

* services
* staff
* appointment
* calendar

EDUCATION:

* institution
* program
* application
* documents

CONSTRUCTION:

* contractor
* materials
* project
* quotation
* milestones

AGRICULTURE:

* produce
* wholesale
* suppliers
* transport

JOBS:

* company
* job
* CV
* applications
* interviews

COURSES:

* content
* enrollment
* progress
* certificates

EVENTS:

* venue
* tickets
* seats
* QR
* check-in

---

# 71. PRODUCT DISCOVERY

Build:

* categories
* filters
* sorting
* recommendations
* recently viewed
* favorites
* saved searches
* alerts

Eventually:

AI discovery.

---

# 72. AI LISTING GENERATOR

Merchant uploads images.

System can generate a draft:

* title
* description
* category
* attributes
* search keywords
* translation
* suggested pricing metadata

The merchant must approve the listing before publication.

---

# 73. AMHARIC-FIRST AI

The platform should eventually support natural Amharic commerce queries.

Example:

"ከ 30000 ብር በታች ሳምሰንግ ስልክ ፈልግልኝ"

The system should convert natural language into authorized marketplace search criteria.

Do not treat AI translation as the business logic.

AI produces structured intent.

The commerce engine executes it.

---

# 74. BUSINESS MODEL

Support multiple revenue mechanisms:

* marketplace commission
* seller subscription
* premium merchant plans
* featured listings
* advertising
* lead fees
* delivery margin
* service commission
* event ticket fees
* B2B transaction fees
* AI subscriptions
* analytics subscriptions
* verification services where appropriate

Do not hard-code one commission rate.

Commission must be configurable by:

* platform
* vertical
* category
* merchant
* product
* campaign

with clear precedence rules.

---

# 75. THE PLATFORM MUST BE CONFIGURATION-DRIVEN

Avoid:

if phone

if car

if food

if property

everywhere in the code.

Instead use:

configuration

*

blueprints

*

domain extensions

*

workflow definitions

*

feature flags.

Only genuinely different business logic should be implemented as vertical-specific modules.

---

# 76. REPOSITORY ARCHITECTURE

Propose a clean monorepo or well-defined multi-repo architecture.

Possible structure:

apps/

* super-admin
* tenant-admin
* merchant-portal
* finance
* miniapp
* customer-web

services/

* identity
* tenancy
* catalog
* orders
* payments
* ledger
* payouts
* search
* notifications
* delivery
* reviews
* promotions
* advertising
* AI
* support
* analytics

bots/

* bot-runtime

blueprints/

* phones
* computers
* electronics
* fashion
* furniture
* cars
* spare-parts
* property
* commercial-property
* services
* food
* beauty
* education
* construction
* agriculture
* jobs
* courses
* events

packages/

* UI
* auth
* tenant SDK
* payment SDK
* bot SDK
* analytics SDK
* AI SDK

infra/

* docker
* ansible
* terraform
* monitoring
* deployment

docs/

---

# 77. PLATFORM CONTROL PLANE

Create a central:

# PLATFORM CONTROL PLANE

It resolves:

* who is the user?
* what tenant?
* what vertical?
* what blueprint?
* what blueprint version?
* what features?
* what permissions?
* what branding?
* what payment configuration?
* what bot?
* what Mini App?
* what deployment?
* what domain?

Conceptually:

Request

↓

Identity

↓

Tenant Resolver

↓

Vertical Resolver

↓

Blueprint Resolver

↓

Feature Flags

↓

Authorization

↓

Domain Service

↓

Data

---

# 78. DOMAIN DATA MODEL

At minimum design entities for:

Platform

Vertical

Blueprint

BlueprintVersion

Tenant

Merchant

Brand

User

Role

Permission

Bot

MiniApp

Domain

Deployment

Product

Category

Attribute

Inventory

Customer

Order

OrderItem

Payment

Refund

LedgerAccount

LedgerEntry

Payout

CommissionRule

Delivery

Courier

Review

Promotion

Campaign

Notification

AIConversation

AIAction

AuditEvent

SupportTicket

FeatureFlag

Subscription

Webhook

Integration

ProviderCredential

Workflow

WorkflowState

WorkflowTransition

---

# 79. SECURITY OF TENANT RESOLUTION

Do NOT trust:

`X-Tenant-ID`

from arbitrary clients.

The tenant must be resolved from trusted context such as:

* authenticated session
* validated Telegram context
* signed internal metadata
* trusted host mapping
* server-side resource lookup

and then authorization must confirm access.

---

# 80. HOSTNAME RESOLUTION

For merchant domains:

incoming hostname

↓

normalize

↓

lookup domain table

↓

resolve tenant

↓

resolve vertical

↓

load configuration

↓

serve application

This allows one infrastructure stack to serve thousands of merchant hostnames.

---

# 81. IMPORTANT: DO NOT CREATE THOUSANDS OF STATIC FRONTENDS

The merchant's "own app" is an instance/configuration of the common application runtime.

This gives:

* lower cost
* faster deployment
* easier upgrades
* easier security fixes
* less duplicated code
* centralized monitoring

The customer still sees an independent merchant experience.

---

# 82. DEPLOYMENT PRINCIPLE

Separate:

# CODE

from

# TENANT CONFIGURATION

from

# INFRASTRUCTURE CONFIGURATION

from

# SECRETS

Never bake merchant secrets into application images.

---

# 83. NO SECRET IN GIT

Mandatory secret scanning.

If a secret appears in source code:

STOP.

Do not commit it.

Use environment/secret management.

---

# 84. OBSERVABILITY PER TENANT

Super Admin should be able to select:

Merchant:

ABC Phones

and see:

* API errors
* orders
* payment failures
* Mini App errors
* bot failures
* worker failures
* latency
* health
* deployment version

without exposing another merchant's data.

---

# 85. TENANT HEALTH

Every tenant has:

HEALTHY

DEGRADED

OFFLINE

MAINTENANCE

UNKNOWN

computed from actual subsystem health.

Do not allow a merchant to manually claim "healthy."

---

# 86. NO-BREAK DEPLOYMENT

Application upgrades must not randomly break every merchant.

Use:

* versioning
* migrations
* feature flags
* staged rollout
* smoke tests
* rollback

Eventually support:

10% rollout

↓

25%

↓

50%

↓

100%

where appropriate.

---

# 87. ADMIN AUDITABILITY

Every sensitive Super Admin action must be recorded.

Examples:

* create tenant
* delete tenant
* change commission
* change payment provider
* create blueprint
* publish blueprint
* migrate tenant
* change permissions
* refund money
* payout
* disable merchant
* create bot
* rotate credentials

---

# 88. COST MODEL

The architecture should optimize:

COST PER MERCHANT

not only total infrastructure cost.

Track:

* CPU/tenant estimate
* storage/tenant
* database growth
* image storage
* notification usage
* AI cost
* payment cost
* delivery cost
* support cost

Eventually Super Admin should see:

Estimated platform cost per merchant.

---

# 89. FUTURE AI COST CONTROL

AI requests must have:

* provider abstraction
* model routing
* budget
* token usage
* caching
* fallback
* rate limits

Do not let one merchant generate unlimited AI costs for the platform.

---

# 90. FUTURE PLATFORM ECONOMICS

Create a platform billing engine.

Merchant plan:

FREE

STARTER

PRO

BUSINESS

ENTERPRISE

Each plan controls:

* product count
* staff
* orders
* AI usage
* analytics
* storage
* integrations
* automation
* support

Do not hard-code plan restrictions throughout the application.

---

# 91. BUILD ORDER

DO NOT attempt to implement everything simultaneously.

Build in controlled phases.

## PHASE 0

Architecture discovery.

## PHASE 1

Foundation:

* repository
* environments
* CI
* Docker
* PostgreSQL
* Redis
* migrations
* authentication
* RBAC
* tenant engine

## PHASE 2

Blueprint engine.

## PHASE 3

Merchant provisioning.

## PHASE 4

Telegram bot + Mini App.

## PHASE 5

Catalog/search.

## PHASE 6

Orders.

## PHASE 7

Payments.

## PHASE 8

Ledger/finance.

## PHASE 9

Notifications.

## PHASE 10

Reviews/promotions.

## PHASE 11

Delivery.

## PHASE 12

AI.

## PHASE 13

Analytics.

## PHASE 14

Advertising.

## PHASE 15

Additional verticals.

---

# 92. DEVELOPMENT GATE

Before writing significant code:

DO NOT GUESS.

First inspect:

* repository
* existing files
* infrastructure
* environment
* Docker
* DNS
* Cloudflare Tunnel configuration
* database
* current Telegram configuration
* existing credentials references
* deployment scripts
* architecture documents

Do not overwrite existing systems blindly.

If an existing project already contains useful functionality, preserve and migrate it.

---

# 93. QUESTIONS YOU MUST ASK BEFORE IMPLEMENTATION

Ask the owner only questions that materially affect architecture.

At minimum establish:

1. Exact root domain currently used.
2. Exact VM/server topology.
3. Current Cloudflare account/tunnel state.
4. Current DNS nameservers.
5. Existing Telegram bot ownership.
6. Whether a new Telegram bot ecosystem is required.
7. Preferred backend language/framework if not already fixed.
8. Preferred frontend stack if not already fixed.
9. Current database state.
10. Current payment provider relationships.
11. Whether existing Arada systems should be reused or kept separate.
12. Storage capacity.
13. Backup destination.
14. Current CI/CD environment.

Do NOT repeatedly ask questions whose answers can be discovered from the repository or infrastructure.

Do NOT ask 50 questions at once.

Group questions into blocking architecture decisions.

---

# 94. BEFORE CODING, PRODUCE THESE DOCUMENTS

First create:

01_ARCHITECTURE.md

02_TENANCY.md

03_BLUEPRINT_ENGINE.md

04_TELEGRAM_ARCHITECTURE.md

05_DOMAIN_AND_TUNNEL.md

06_DATABASE_MODEL.md

07_PAYMENT_ARCHITECTURE.md

08_LEDGER.md

09_SECURITY.md

10_RBAC.md

11_DEPLOYMENT.md

12_OBSERVABILITY.md

13_DISASTER_RECOVERY.md

14_COST_MODEL.md

15_ROADMAP.md

16_THREAT_MODEL.md

17_API_CONTRACTS.md

18_EVENT_MODEL.md

19_ACCEPTANCE_TESTS.md

20_DECISIONS.md

---

# 95. ARCHITECTURE DECISION RECORDS

Every major architectural decision must be documented.

Example:

ADR-001

Decision:

Shared multi-tenant PostgreSQL initially.

Reason:

Cost and operational efficiency.

Alternative:

Database per tenant.

Rejected initially because:

unnecessary cost/complexity.

Future:

Enterprise isolation tier.

---

# 96. NEVER DO THIS

Do NOT:

* build one independent backend per merchant
* create one VM per merchant
* create one public IP per merchant
* require one domain per merchant
* expose Postgres
* expose Redis
* expose internal APIs
* trust frontend tenant IDs
* trust Telegram initDataUnsafe
* store secrets in Git
* hard-code commission rates
* hard-code vertical fields everywhere
* mix payment state with accounting state
* use floating point for money
* skip migrations
* skip tenant-isolation tests
* blindly introduce Kubernetes
* blindly introduce microservices everywhere
* create unnecessary infrastructure
* duplicate frontend code for every merchant

---

# 97. IMPORTANT ARCHITECTURAL PRINCIPLE

Do not confuse:

MICROSERVICE ARCHITECTURE

with

GOOD ARCHITECTURE.

The platform must be modular.

It does NOT have to start as dozens of independently deployed services.

Use modular architecture and extract services when there is a real operational reason.

---

# 98. START SMALL, DESIGN LARGE

The first production deployment should be able to run economically on a small self-hosted VM environment.

But the interfaces must allow:

* horizontal scaling
* worker scaling
* database scaling
* search scaling
* object storage scaling
* AI scaling
* tenant isolation
* dedicated enterprise infrastructure

later.

---

# 99. SUCCESS CRITERIA

The architecture is successful when:

I can create:

PHONE BLUEPRINT

↓

create:

MERCHANT A

↓

the system automatically provisions:

* tenant
* bot
* Mini App
* storefront
* admin
* finance
* payment configuration
* domain
* notifications
* analytics

Then I can create:

MERCHANT B

from the same blueprint

without copying source code.

Then I can modify the phone blueprint for NEW merchants without breaking old merchants.

Then I can create:

CAR BLUEPRINT

and use the same Commerce OS.

Then:

PROPERTY

Then:

FOOD

Then:

JOBS

Then:

EVENTS.

---

# 100. FINAL PRODUCT DEFINITION

This is not:

"an Ethiopian marketplace."

It is:

# A TELEGRAM-FIRST, MULTI-TENANT, BLUEPRINT-DRIVEN COMMERCE OPERATING SYSTEM.

Telegram is the first distribution channel.

The Commerce OS is the actual product.

The merchant factory is the growth engine.

The blueprint engine is the scalability engine.

The finance/ledger system is the economic foundation.

The trust system is the safety layer.

The AI system is the intelligence layer.

The self-hosted infrastructure is the cost-control layer.

Cloudflare is the public network/security boundary.

---

# 101. YOUR FIRST MISSION

Before writing production code:

1. Inspect the entire project.
2. Inspect all existing documentation.
3. Inspect existing infrastructure.
4. Inspect Cloudflare/Tunnel configuration if available.
5. Inspect Telegram integration.
6. Identify reusable components.
7. Identify dangerous technical debt.
8. Produce the architecture documents.
9. Produce the database/domain model.
10. Produce the tenant model.
11. Produce the blueprint model.
12. Produce the deployment architecture.
13. Produce the domain/Tunnel architecture.
14. Produce the security model.
15. Produce the financial model.
16. Produce the phased implementation plan.
17. Identify blocking questions.
18. Ask only the necessary questions.
19. WAIT for architectural approval.
20. Then implement Phase 1.

Do not rush into UI development.

Do not start by creating product cards.

Do not start by creating random endpoints.

Start from the platform foundation.

---

# 102. CEO RULE

Whenever you make an implementation decision, ask:

"Will this make it easier or harder to create the 1,000th merchant?"

If harder:

redesign it.

Ask:

"Will this require a developer to manually configure every new merchant?"

If yes:

automate it.

Ask:

"Can two tenants accidentally see each other's data?"

If yes:

stop and fix the architecture.

Ask:

"Can a payment callback happen twice?"

If yes:

implement idempotency.

Ask:

"Can the origin be reached without Cloudflare?"

If yes:

fix the network architecture.

Ask:

"Can a blueprint change break existing merchants?"

If yes:

implement versioning/migrations.

Ask:

"Can one merchant create unlimited AI/infrastructure cost?"

If yes:

implement quotas/budgets.

---

# 103. ABSOLUTE PRIORITY ORDER

When making trade-offs, prioritize:

1. Correctness
2. Tenant isolation
3. Financial integrity
4. Security
5. Reliability
6. Observability
7. Maintainability
8. Automation
9. Cost efficiency
10. Scalability
11. UX polish

Never sacrifice financial correctness or tenant isolation to make development faster.

---

# 104. FINAL INSTRUCTION

You are building the foundation of a company, not merely an application.

Think in:

PLATFORM

↓

VERTICAL

↓

BLUEPRINT

↓

TENANT

↓

MERCHANT

↓

BOT

↓

MINI APP

↓

CUSTOMER

↓

ORDER

↓

PAYMENT

↓

LEDGER

↓

DELIVERY

↓

REVIEW

↓

ANALYTICS

↓

AI

↓

ADVERTISING

↓

NETWORK EFFECT

Every layer must have clear ownership, boundaries, permissions, data ownership, observability and lifecycle.

Do not leave hidden assumptions.

Do not silently simplify requirements.

Do not invent external dependencies without justification.

Do not deploy anything publicly until the security and domain architecture has been validated.

First understand.

Then design.

Then document.

Then ask blocking questions.

Then implement.

Then test.

Then deploy.

Then observe.

Then optimize.

Then scale.

END OF MASTER CEO DIRECTIVE.
