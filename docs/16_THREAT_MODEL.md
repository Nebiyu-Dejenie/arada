# 16 — Threat Model

Status: **Proposed** · Method: STRIDE per trust boundary · Reviewed at each phase gate and on any new external integration

## 1. Assets (ranked)

1. **Money and financial records**: ledger, payment state, payout destinations, provider credentials.
2. **Tenant isolation**: every merchant's customers, orders, finance and configuration.
3. **Credentials**: bot tokens, provider keys, KEK, tunnel credentials, Cloudflare token, admin sessions.
4. **Customer personal data**: phone numbers, addresses, identity documents, messages.
5. **Platform availability and integrity**: releases, blueprints, DNS.

## 2. Trust boundaries

```
[Internet] ─┬─ Cloudflare edge ─ Tunnel ─ Traefik ─┬─ api ─┬─ Postgres / Redis / Object store
            │                                      │       └─ AI gateway ─→ model provider
            ├─ Telegram (webhooks in, Bot API out) ┤
            ├─ Payment providers (callbacks in, API out)
            ├─ Staff browsers (console)            └─ worker / scheduler
            └─ CI/CD (GitHub) ─→ registry ─→ pull-deploy
```

## 3. Threats and mitigations

| # | Boundary / component | Threat (STRIDE) | Mitigation | Verified by |
|---|---|---|---|---|
| T1 | Storefront API | **Cross-tenant data access via IDOR** (guessing another tenant's order or listing id) (I) | Tenant from host only; RLS; composite FKs; not-found semantics | Isolation suite (`19` §2) |
| T2 | Console | Tenant switching by editing the path slug or a header (E) | Membership check per request; header ignored; 404 on non-membership | Isolation suite |
| T3 | Mini App | **Forged `initData`** by someone holding the bot token (BYO merchant, leaked token) (S) | **Ed25519 `signature` verification** with Telegram's public key, plus HMAC; bot binding | Auth tests with forged HMAC-valid data |
| T4 | Mini App | Replay of captured `initData` (S) | 1 h max age for session creation; bootstrap replay cache; short access tokens | Auth tests |
| T5 | Mini App | Trusting `initDataUnsafe` or client-supplied user ids (S) | Never read server-side; lint rule in the frontend | Code review + test |
| T6 | Telegram webhook | Forged updates to our endpoint (S, T) | Unguessable route key + per-bot secret header; constant-time compare | Webhook tests |
| T7 | Telegram | **Webhook hijack** with a stolen token (`setWebhook` to an attacker's URL) (I, D) | Health loop detects URL mismatch → restore, rotate (`replaceManagedBotToken`), alert | Chaos test on staging |
| T8 | Payment webhook | Forged or replayed success callbacks (S, T) | Signature per configuration; dedupe on event id; **status verified via provider API**; amount/currency/ref match | Finance suite |
| T9 | Checkout | Client-side price, discount or fee tampering (T) | Server re-prices from DB; totals recomputed; signed confirmation token | API tests |
| T10 | Checkout | Race on the last stock unit (T) | Row-locked reservation; `CHECK` constraints | Concurrency test |
| T11 | Refund/payout | Insider or compromised staff draining funds (E, T) | Step-up, limits, maker–checker, payout-destination cool-off + notification, audit, daily caps | RBAC + finance tests |
| T12 | Ledger | Direct manipulation or silent correction (T, R) | Append-only triggers; app role INSERT/SELECT only; zero-sum trigger; nightly rebuild compare | DB tests |
| T13 | Commission | Retroactive rate change altering history (T) | Rules immutable once referenced; snapshots on order items | Finance tests |
| T14 | Referral | Self-referral, farming with fake accounts, client-set attribution (S, T) | Server-issued codes; first-touch server-side; qualifying-event rewards; velocity limits; risk signals | Referral tests |
| T15 | Reviews | Fake or duplicate reviews (S, T) | Eligibility from completed orders only; one per eligibility; risk signals | Review tests |
| T16 | Merchant content | **Stored XSS** via descriptions or brand names (T, E) | Sanitiser allow-list; CSP without inline scripts; storefront origin never holds staff cookies | Security tests |
| T17 | Media upload | Malicious files, polyglots, EXIF location leaks, oversized uploads (T, I, D) | Pre-signed size-bound uploads to quarantine; magic-byte check; re-encode; ClamAV for documents | Media tests |
| T18 | Outbound fetches | **SSRF** (image-by-URL imports, partner webhooks) (I, E) | Egress allow-list proxy; block RFC1918/metadata ranges; no redirects to internal hosts | SSRF tests |
| T19 | AI | **Prompt injection** via product text or messages, leading to data exfiltration or unauthorized actions (E, I) | Tools enforce authz as the principal; PII redaction; financial tools return drafts only; no DB access | AI tool tests |
| T20 | AI | Cost exhaustion by one tenant (D) | Budgets, rate limits, degraded mode | Budget tests |
| T21 | Edge | Direct-to-origin attacks bypassing Cloudflare (all) | No public ports; tunnel only; external scan | Deployment acceptance |
| T22 | Edge | Host-header or subdomain probing; cache poisoning (T, D) | Traefik default 404; negative-lookup cache; `/api` never cached; cache key includes host | Ingress tests |
| T23 | DNS | Record injection or deletion by a compromised token (T, D) | Zone-scoped token; `arada:` marker + deletion guards; hourly reconciler; Terraform-managed zone config; registrar MFA | Reconciler alerts |
| T24 | Staff auth | Phishing or credential stuffing on admins (S) | Passkeys; Cloudflare Access; MFA; brute-force controls; new-device alerts | Auth tests |
| T25 | Sessions | CSRF on console (T) | SameSite=Strict + synchronizer token | Security tests |
| T26 | Secrets | Secret committed to git (public repo!) (I) | gitleaks pre-commit + blocking CI; push protection; rotation runbook | CI |
| T27 | Secrets | Ciphertext moved between tenant rows (I) | AES-GCM AAD binds ciphertext to table/row/tenant | Crypto tests |
| T28 | Supply chain | Malicious dependency or action (T, E) | Lockfiles; audit; SHA-pinned actions; minimal CI permissions; image scan; deploy by digest | CI |
| T29 | Support staff | Over-broad access to tenant data (I) | JIT grants with reason and expiry; audit tagging | RBAC tests |
| T30 | Logs | PII or token leakage into logs and traces (I) | Redaction processor; collector attribute filter; log-sample test | Log tests |
| T31 | Blueprints | Malicious or erroneous blueprint breaking tenants (T, D) | Meta-schema validation; immutability; pinning; preview-before-migrate; sandboxed JSONLogic (no code) | Blueprint tests |
| T32 | Provisioning | Slug squatting or impersonation (S) | Reserved and brand lists; no reuse of slugs; Super Admin review for flagged names | Provisioning tests |
| T33 | Repudiation | Admin denies a sensitive action (R) | Append-only audit with request id, IP, device; step-up evidence | Audit tests |
| T34 | Availability | Webhook floods, bot abuse, scraping (D) | Cloudflare rate limits and WAF; per-bot queues; per-principal limits in the app | Load tests |
| T35 | Legal | Operating as an unlicensed payment intermediary | Settlement Model A/B by default; Model C behind legal clearance (`07` §1) | Owner decision (Q8) |

## 4. Residual risks accepted for launch (to revisit)

- A single Postgres primary until Stage 2 (mitigated by PITR with a ≤ 5-minute RPO).
- Main Mini App configuration is a manual BotFather step (mitigated by automated verification).
- BYO-bot merchants know their own token. HMAC forgery is blocked by the Ed25519 check, but a merchant could still misuse *their own* bot. Managed bots are preferred.
