# 05 — Domain, DNS and Tunnel

Status: **Proposed, blocked on Q1 (which root domain) and Q3 (approve the hostname scheme)** · Related: ADR-008, ADR-009, ADR-010

`DOMAIN` below means the single root domain chosen in Q1. No other root domain, public IP or origin exposure is introduced (directive §14–15).

## 1. Chain of custody

```
Registrar (Hostinger)  →  Cloudflare nameservers  →  Cloudflare DNS (proxied records only)
   →  Cloudflare edge (TLS, WAF, rate limits, Access)  →  Cloudflare Tunnel (outbound-only from our VMs)
   →  cloudflared container  →  Traefik (single ingress, default 404)  →  web / api containers
```

- **Tunnel and zone must live in the same Cloudflare account.** The two current `arada.*` zones appear to be on different accounts (`00_DISCOVERY.md` §3), so Q1 includes confirming the account.
- **One production tunnel** for the whole platform, separate from the gaming products' tunnels. Staging gets its own tunnel, so a staging credential can never serve production traffic.

## 2. Hostname scheme: two options evaluated (directive §18)

**Option A: role subdomains per merchant.** `abc-phones.DOMAIN`, `admin-abc-phones.DOMAIN`, `finance-abc-phones.DOMAIN`

**Option B (recommended): one customer host per merchant, with shared staff consoles.** `abc-phones.DOMAIN` (storefront and Mini App); merchant staff use `merchant.DOMAIN` and pick the business after login.

| Criterion | A: per-merchant role hosts | B: per-merchant storefront + shared consoles |
|---|---|---|
| TLS | Covered by Universal SSL (single-level) | Covered by Universal SSL (single-level) |
| DNS records per merchant (explicit mode) | **3** | **1** |
| Merchants before the Free-plan record cap (1,000 records per zone at time of writing; verify for this zone) | ≈330 | ≈990 |
| Admin attack surface | Thousands of admin hostnames. Each needs WAF and Access coverage, and the hostnames are enumerable. | **One** console host behind one Cloudflare Access application and one WAF policy |
| Cookie and session isolation from merchant content | Separate hosts (good) | Separate hosts (good). The storefront never carries staff cookies. |
| Caching | Cache rules must pattern-match `admin-*` | Simple rule: bypass on `merchant.`, `admin.`, `finance.` |
| Multi-business owner | Separate login per business | One login with a business switcher |
| "Merchant feels independent" | Branded admin URL | Customer-facing identity is fully branded: storefront, bot, Mini App, messages. The console is branded after the business is selected. |
| SEO | Storefront on its own subdomain | Same |
| Operational complexity | 3× records, verification and health probes | 1× |
| Slug namespace risk | `admin-*` and `finance-*` prefixes compete with merchant slugs | Only fixed platform names are reserved |

**Recommendation: B.** Customer-facing independence is fully preserved, while the admin surface, DNS footprint and security policy stay constant as the number of merchants grows.

## 3. Hostname map (Option B)

| Hostname | Routed to | Protection | Cache |
|---|---|---|---|
| `DOMAIN`, `www.DOMAIN` | `web-site` (company site) | Public | Yes |
| `app.DOMAIN` | `web-customer` (platform-level runtime, future cross-merchant discovery) | Public | Static assets only |
| `api.DOMAIN` | `api`: Telegram webhooks, payment webhooks, partner and mobile API | Public, WAF, rate limits | No |
| `admin.DOMAIN` | `web-console` + `api` (`/api/*`) | **Cloudflare Access** (Super Admin and platform roles) + application MFA | No |
| `finance.DOMAIN` | Same console app, finance workspace | Cloudflare Access + application MFA | No |
| `ops.DOMAIN` | Grafana and ops tools | Cloudflare Access only (no public login page) | No |
| `status.DOMAIN` | Status page (synthetic checks, no tenant data) | Public | Short TTL |
| `merchant.DOMAIN` | Console app, merchant workspace (catalog, orders, staff, merchant finance) | Public login; MFA required for owner, admin and finance roles | No |
| `media.DOMAIN` | Processed image variants (public listing media), signed URLs for private documents | Public or signed | Yes (immutable keys) |
| `{slug}.DOMAIN` | `web-customer` (`/`) + `api` (`/api/*`, same origin) | Public, WAF, bot management | Static assets only |
| `stg-*.DOMAIN` | Staging equivalents (e.g. `stg-api`, `stg-admin`, `stg-{slug}`) | Cloudflare Access on **all** staging hosts | No |

Same-origin `/api/*` on every host means no CORS, host-only cookies, and a tenant that is implied by the host.

## 4. Slugs

- **Generated, never raw input.** The business name is transliterated (Amharic → Latin via a fixed table), lower-cased, and cleaned to `[a-z0-9-]`, with runs of hyphens collapsed. The result must match `^[a-z][a-z0-9-]{1,30}[a-z0-9]$`.
- **Forbidden:** the substring `--` (which also blocks `xn--` punycode spoofing), the prefixes `stg-`, `dev-`, `test-`, `admin-`, `finance-`, `api-`, `ops-`, and the **reserved list**: `www app api admin finance ops status merchant media static cdn assets auth login sso id account billing pay payments agent sms mail smtp imap mx ns help support docs blog shop store dev staging test internal root platform arada` plus any hostname already used by another product on the same zone.
- A curated list blocks brand impersonation (major brands and banks) and offensive words. A Super Admin can override it with an audit reason.
- A slug is **unique for all time**. Archived slugs are never reissued, which prevents old links resolving to a new owner.
- **Renaming** the business does not change the slug. Changing the slug is an explicit action: a new domain row, a 301 from the old host for 180 days, and Telegram Mini App URLs are updated.

## 5. DNS provisioning (directive §17): `edge` module

```python
class DnsProvider(Protocol):
    async def ensure_record(self, name: str, target: str, *, proxied: bool, comment: str) -> RecordRef
    async def get_record(self, name: str) -> RecordRef | None
    async def delete_record(self, ref: RecordRef, *, guard: DeletionGuard) -> None
class TunnelProvider(Protocol):
    async def ensure_ingress_covers(self, hostname: str) -> bool     # verifies wildcard rule matches
    async def tunnel_health(self) -> TunnelHealth
```

**Cloudflare adapter:**

- **API token** scoped to *this zone only*, with Zone.DNS:Edit and read-only Tunnel access. It is stored as an encrypted platform secret and rotated every 90 days.
- **Idempotent `ensure_record`:**
  1. Look up the record by name.
  2. If it exists with the same target, do nothing.
  3. If it exists with a different target, raise `DnsConflict`, alert, and never overwrite silently.
  4. Otherwise create it: a proxied `CNAME name → <tunnel-id>.cfargotunnel.com`, with comment `arada:tenant=<id>:run=<run>`.
- **Verification.** The record must exist via the API, public resolution must return Cloudflare anycast, and an HTTPS probe to `https://{host}/.well-known/arada-host-check` must return the tenant's signed nonce. The domain becomes `active` only after all three pass.
- **Deletion protection:**
  - Only records whose comment carries the `arada:` marker and a matching tenant id can be deleted.
  - Platform hostnames are on a deny-list.
  - Deletion needs the tenant to be in `archived`, and a second confirmation for any batch of more than 5 records.
- **Every call is audited**, with the before and after state.
- **Reconciler** (`scheduler`, hourly): diff `control.domains` against the Cloudflare records carrying the `arada:` marker. It reports drift and never auto-deletes unknown records.

**DNS mode (ADR-009):**

- **`explicit` (default):** one proxied record per active merchant. Unknown subdomains are NXDOMAIN at the edge and never reach the origin. Suspending or archiving a merchant can remove its record.
- **`wildcard` (scale fallback):** one proxied `*.DOMAIN` record. There are zero DNS API calls per merchant, and unknown hosts are rejected by the tenant resolver with a cached 404. Switch when record usage exceeds 80% of the zone limit, or upgrade the Cloudflare plan. Which to do is a cost decision (`14_COST_MODEL.md`).

Explicit records above the wildcard keep working in both modes, so switching is not a migration.

## 6. Tunnel ingress (committed template; credentials never committed)

```yaml
# infra/cloudflared/config.template.yml  (rendered by Ansible; the credentials file comes from the private ops secret store)
tunnel: ${TUNNEL_ID}
credentials-file: /etc/cloudflared/credentials.json
originRequest:
  connectTimeout: 10s
  noTLSVerify: false
ingress:
  - hostname: "DOMAIN"
    service: http://traefik:8080
  - hostname: "*.DOMAIN"          # every platform + merchant host; Traefik decides
    service: http://traefik:8080
  - service: http_status:404       # required catch-all
```

Merchant creation **never changes the tunnel config**. It adds a DNS record and a database row. The tunnel runs as a container (`cloudflared tunnel run`) with `--metrics` exposed on the internal network only.

## 7. Traefik (single ingress, all config in git)

- **Entry point** `web` on `:8080`, reachable only on the internal Docker network from cloudflared. No host port is published.
- **Routers** come from the file provider (`infra/traefik/dynamic/*.yml`). They are not discovered from Docker labels, so routing is reviewed in pull requests.
  - `Host(admin.DOMAIN) || Host(finance.DOMAIN) || Host(merchant.DOMAIN)` → `web-console`, with `PathPrefix(/api)` → `api`
  - `Host(api.DOMAIN)` → `api`
  - `HostRegexp(^[a-z][a-z0-9-]{1,30}[a-z0-9]\.DOMAIN$)` with `PathPrefix(/api)` → `api`; otherwise → `web-customer`
  - **Default (priority 1):** return 404 through a static `noop@internal` service with an error page. **An unmatched host or path never reaches any application.**
- **Middlewares:**
  - Security headers: HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, and CSP set per bundle.
  - Request id (`X-Request-Id`, generated when absent; client-supplied ids are replaced).
  - A body size limit.
  - Real client IP taken from `CF-Connecting-IP`. This is trusted only because Traefik is unreachable except through the tunnel.
  - Coarse rate limiting (fine-grained, per-principal limits are in the app, backed by Redis).
- **Access logs** in JSON with `request_id`, host, status and latency, shipped to Loki. Query strings are omitted, because they may contain tokens.

## 8. Cloudflare zone settings (managed as code: `infra/terraform/cloudflare`)

| Setting | Value |
|---|---|
| SSL mode | Full (strict). The tunnel is encrypted end-to-end, and Cloudflare's edge certificate is Universal SSL. |
| Always Use HTTPS, HSTS | On (HSTS with `includeSubDomains` only after all hosts are verified) |
| Minimum TLS | 1.2 |
| WAF | Managed rules on. Custom rules: block non-`POST` requests on webhook paths; geo and ASN rules for `admin.`/`finance.` if desired. |
| Rate limiting | `/api/v1/auth/*`: per IP. Webhooks: per route key. |
| Bot protection | Bot Fight Mode on storefront hosts, **off** for `api.DOMAIN` webhook paths (Telegram and providers are bots) |
| Access applications | `admin.`, `finance.`, `ops.`, `stg-*`. Identity: one-time PIN or IdP, with an allow-list of emails. |
| Caching | Cache static assets on `{slug}`, `app`, `media`. Bypass `/api/*` and all console hosts. |
| DNSSEC | On (DS record at Hostinger) |

## 9. "No public origin" invariants (directive §15; verified in `19` §5)

1. **No `ports:` mapping** in any production compose file; CI fails on one. Internal services use `expose` only. This matters because Docker-published ports bypass host firewalls such as UFW.
2. **Host firewall:** default-deny inbound. Management SSH is reachable only over a private overlay (WireGuard or Tailscale) or through Cloudflare Access for Infrastructure. It is never world-open.
3. **PostgreSQL, Redis, the object store, Prometheus and Grafana** listen only on internal Docker networks. Grafana is reachable only through `ops.DOMAIN` behind Access.
4. **An external scan** (nmap from outside) of every VM's public address, if the VM has one, shows **no open ports**. This check is part of the deployment acceptance tests.
5. **DNS:** no A or AAAA record for any origin address, and the zone is audited for records not pointing to the tunnel.
