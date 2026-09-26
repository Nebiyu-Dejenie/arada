# 16 — Threat Model

Status: **Proposed** · Method: every threat class in Permanent Command §44, each with risk, impact, likelihood, mitigation and verification · Reviewed at every phase gate and whenever an external integration is added. **Production launch requires this review to be complete** (Permanent Command §44).

**Rating scale:**

- **Impact:** H = money loss, cross-tenant data exposure or platform takeover; M = a single tenant's data or availability; L = limited or nuisance.
- **Likelihood:** H = commonly attempted against internet commerce; M = needs specific conditions; L = needs insider access or rare conditions.

All ratings are *before* mitigation.

## 1. Assets (ranked)

1. **Money and financial records**: ledger, payment state, payout destinations, provider credentials.
2. **Tenant isolation**: every merchant's customers, orders, finance and configuration.
3. **Credentials**: bot tokens, provider keys, key-encryption key, tunnel credentials, Cloudflare token, admin sessions.
4. **Customer personal data**: phone numbers, addresses, documents, messages.
5. **Platform integrity and availability**: releases, blueprints, DNS, backups.

## 2. Trust boundaries

```
[Internet] ─┬─ Cloudflare edge ─ Tunnel ─ Traefik ─┬─ api ─┬─ Postgres / Redis / Object store
            │                                      │       └─ AI gateway ─→ model provider
            ├─ Telegram (webhooks in, Bot API out) ┤
            ├─ Payment providers (callbacks in, API out)
            ├─ Staff browsers (consoles)           └─ worker / scheduler
            └─ CI/CD (GitHub) ─→ registry ─→ pull-deploy        Backups ─→ off-host repository
```

## 3. Threat register

| # | Threat class (§44) | Risk | Impact | Likelihood | Mitigation | Verification |
|---|---|---|---|---|---|---|
| T1 | **Tenant escape** | A request or query reads or writes another tenant's rows | H | M | Server-side tenant resolution only; forced RLS keyed on `SET LOCAL`; composite same-tenant foreign keys; tenant-keyed caches, search and object prefixes | ISO-1…15 on every PR (`19` §2) |
| T2 | **IDOR** | Guessing or enumerating another tenant's order or listing ids | H | H | UUIDv7 ids; tenant from host or session only; 404 on non-ownership; resource-policy ownership checks | ISO-1, ISO-3, ISO-8 |
| T3 | **Authorization bypass** | A missing permission check on an endpoint, or reliance on UI hiding | H | M | `authorize()` required by a route decorator, with CI rejecting routes without a declared permission; scoped roles; policy checks | AUTH-9; route-lint in CI |
| T4 | **Authentication attacks** | Credential stuffing, brute force or session fixation against staff | H | H | Passkeys; MFA for privileged roles; Cloudflare Access on admin hosts; per-account and per-IP backoff; session rotation on login and privilege change | AUTH-6, AUTH-7 |
| T5 | **Telegram auth forgery** | Forged `initData` by anyone holding a bot token; trusting `initDataUnsafe` | H | M | HMAC **and** Ed25519 `signature` verification; bot_id binding to the tenant; freshness; `initDataUnsafe` never read server-side | AUTH-1…4, ISO-4 |
| T6 | **Webhook forgery** (Telegram) | Forged updates to our endpoint | M | M | Unguessable per-bot route key + secret header, compared in constant time; dedupe on `update_id` | AUTH-5 |
| T7 | **Webhook forgery** (payments) | Forged "payment succeeded" callbacks | H | H | Signature per configuration; status confirmed via the provider API before crediting; amount, currency and reference must match | FIN-1, FIN-9 |
| T8 | **Payment replay** | Replaying a genuine success callback or checkout request | H | H | `UNIQUE(provider, provider_event_id)`; idempotency keys at API, intent, ledger and consumer levels; monotonic state machine | FIN-1, FIN-2, FIN-16 |
| T9 | **Double spending** | Concurrent refunds, payouts or checkouts exceeding available value | H | M | Row locks on intents and balances; `CHECK` constraints; running refund total ≤ captured; `no_overdraft` accounts; the ledger zero-sum trigger | FIN-5, FIN-10, FIN-11 |
| T10 | **SQL injection** | Dynamic blueprint filters or sorting concatenated into SQL | H | M | SQLAlchemy Core with bound parameters only; filter and sort keys allow-listed from the compiled blueprint; no raw SQL strings from input; Semgrep rule banning string-built SQL | SAST in CI; fuzz tests on filter parameters |
| T11 | **XSS** | Merchant-supplied descriptions, brand names or reviews executing script | H | M | Server-side sanitiser allow-list; CSP without inline scripts; storefront origin never holds staff cookies; React escaping by default | Security tests with payload corpus |
| T12 | **CSRF** | Forged state-changing console requests | M | M | `SameSite=Strict` `__Host-` cookies + synchronizer token header; customer API uses bearer tokens, not cookies | AUTH-6 |
| T13 | **SSRF** | Import-by-URL or outbound webhooks reaching internal services or metadata endpoints | H | M | Egress through an allow-list proxy; RFC1918, link-local and metadata ranges blocked; no redirects to internal hosts | SSRF tests |
| T14 | **File upload attacks** | Malware, polyglots, oversized files, EXIF location leaks | M | H | Pre-signed size-bound uploads to quarantine; magic-byte check; re-encode images; strip metadata; ClamAV for documents; signed short-lived URLs for private files | Media tests |
| T15 | **Credential theft** (bot and provider tokens) | Stolen tokens used for impersonation or to redirect webhooks | H | M | Envelope encryption with AAD; tokens never sent to clients or logs; managed-bot rotation; webhook-URL drift detection with auto-restore and rotation | Health-loop chaos test; crypto tests |
| T16 | **Secret leakage** | Secrets committed to this **public** repository or written to logs | H | M | gitleaks pre-commit + blocking CI; GitHub push protection; log redaction processor; infrastructure secrets in a private ops repo | CI gate; log-sample test |
| T17 | **Rate abuse / API abuse** | Scraping, enumeration and flooding of auth or checkout | M | H | Cloudflare rate limits and WAF; per-principal and per-route limits in Redis; the 404 on unknown hosts is cached | Load tests; rate-limit tests |
| T18 | **Bot abuse** | Spam through merchant bots; mass fake accounts; webhook floods | M | H | Per-bot queues and token buckets; per-user command limits; risk signals on account velocity | Bot rate-limit tests |
| T19 | **Data leakage** | PII exposed through exports, logs, analytics, AI context or error pages | H | M | Field-level encryption for PII; `pii` attribute flags drive redaction; RFC 9457 errors without internals; formula-safe CSV exports | Export and log tests |
| T20 | **Admin compromise** | A takeover of a Super Admin or finance account | H | L | Passkeys + Cloudflare Access; short sessions; step-up re-authentication; maker–checker on money and security actions; payout-destination cool-off; new-device alerts; audit trail | AUTH-8, AUTH-11; audit tests |
| T21 | **Insider misuse** | A support or finance staff member misusing access | H | L | JIT support grants with reason and expiry; limits; dual approval; append-only audit | AUTH-10 |
| T22 | **Supply-chain risk** | A malicious dependency, image or CI action | H | M | Lockfiles; pip-audit and osv; SHA-pinned actions; minimal CI permissions; Trivy; deploy by digest; SBOM | CI gates |
| T23 | **Backup compromise** | Backups stolen, tampered with or deleted (for example by ransomware) | H | L | Encryption at rest with the key held outside the backup host; append-only / object-locked repository; separate credentials that cannot delete; weekly restore verification | DR-1, DR-3 |
| T24 | **Origin exposure** | Attackers bypassing Cloudflare to reach the origin | H | M | Tunnel-only ingress; no published ports; default-deny firewall; no origin DNS records | EDGE-1, EDGE-2 |
| T25 | **DNS tampering** | Records injected or deleted with a compromised token | H | L | Zone-scoped token; `arada:` marker with deletion guards; reconciler; Terraform-managed zone settings; registrar MFA | EDGE-5…7; reconciler alerts |
| T26 | **AI prompt injection** | Product text or messages steering tools to exfiltrate data or act without authority | H | M | Tools run with the principal's permissions and RLS; PII redaction; financial and destructive tools return drafts that need human confirmation; no DB or SQL access | AI-1, AI-2 |
| T27 | **AI cost abuse** | One tenant exhausting the AI budget | M | M | Per-tenant budgets, rate limits, degraded mode | AI-3 |
| T28 | **Referral and review fraud** | Self-referral, farmed accounts, fake reviews | M | H | Server-issued codes; server-side first-touch attribution; rewards on qualifying events; eligibility-gated reviews; risk signals with review paths | Referral and review tests |
| T29 | **Blueprint misuse** | A bad or malicious blueprint breaking tenants or injecting logic | M | L | Meta-schema validation; immutable versions; tenant pinning; sandboxed JSONLogic; preview before migration | BP-1…7 |
| T30 | **Regulatory exposure** | Operating as an unlicensed payment intermediary | H | M | Settlement Model A by default; Model C only with written legal clearance (ADR-015, U4) | Owner decision at Phase 4 |

## 4. Residual risks accepted for early phases (to revisit)

- A single database primary until measured need justifies a replica (mitigated by point-in-time recovery once off-host backups exist).
- Main Mini App configuration is a manual @BotFather step (mitigated by automated verification).
- A merchant using their own bot token (BYO) knows it. HMAC forgery is blocked by the Ed25519 check, but misuse of their *own* bot remains possible; managed bots reduce this.
