# 09 — Security

Status: **Proposed** · Related: `16_THREAT_MODEL.md`, `10_RBAC.md`, ADR-012, ADR-017

Security ranks #4 in the priority order. Only correctness, tenant isolation and financial integrity rank above it, and those three are themselves largely security properties.

## 1. Principles

1. **Cloudflare is the public boundary**, but the application **never relies on it alone**. Every control that matters is also enforced in the app and the database.
2. **Fail closed.** A missing tenant context means no rows. A missing permission means deny. An unverifiable signature means reject.
3. **Least privilege** everywhere: database roles, API tokens, Cloudflare tokens, CI permissions and container users (non-root, read-only root filesystem where feasible).
4. **No secret in git, images, logs, frontends or error messages** (directive §83).
5. **Every sensitive action is audited** (directive §87), with actor, reason, before and after state, and request id.

## 2. Customer authentication

Telegram `initData` validation with HMAC **and** the Ed25519 signature, bot binding and freshness, which produces a tenant-bound 15-minute access token and a rotating refresh handle (`04` §5). There are no long-lived customer bearer tokens, and tokens are held in memory in the Mini App.

## 3. Staff authentication (directive §53–54)

> **As built (Phase 1 + corrective pass, 2026-10-01):** password (argon2id) + TOTP; opaque bearer tokens (no cookies yet, so no CSRF surface); platform and vertical roles, **and TENANT_OWNER / TENANT_ADMIN / TENANT_FINANCE**, are usable only in an MFA-verified session (ADR-035); manager and staff roles work without MFA. Confirming TOTP **rotates** the session: the pre-MFA token is revoked and a new one issued, capped at the old absolute expiry (ADR-035). One session policy for everyone for now: idle 30 min, absolute 12 h. Passkeys, per-action step-up, TOTP reset/recovery, device management and the per-tenant staff-MFA policy are **Planned**.
>
> **AUTHENTICATION RATE LIMITING = REQUIRED BEFORE PUBLIC EXPOSURE** (register B4). Only per-account lockout exists (10 failures → 15 min). There are no per-IP, per-ASN or global limits. Every login attempt costs one argon2id verification (64 MiB), including attempts for unknown usernames, which is a resource-exhaustion vector. The Redis counters below and the Cloudflare challenge are the target design, not the current state.

| Control | Merchant staff | Merchant owner / admin / finance | Platform roles (incl. Super Admin) |
|---|---|---|---|
| Primary factor | Passkey (WebAuthn) or password (argon2id) | Passkey or password | **Passkey required**; password + TOTP only as a recovery path |
| MFA | Optional (a per-tenant policy can require it) | **Required** (TOTP or passkey) | **Required**, phishing-resistant (passkey) |
| Extra edge layer | — | — | **Cloudflare Access** on `admin.`, `finance.`, `ops.` |
| Session | Server-side session, idle timeout 8 h, absolute 7 d | Idle 2 h, absolute 24 h | **Idle 30 min, absolute 12 h** |
| Step-up re-auth | — | Refunds, payout destination, staff roles, payment configuration | Everything in §5 of `10_RBAC.md`, valid for 5 minutes |
| Device and session management | View and revoke | View and revoke | View and revoke; new-device alert via the Ops bot |

- **Cookies:** `__Host-` prefix, `Secure`, `HttpOnly`, `SameSite=Strict`, host-only (no `Domain` attribute). Session ids are 256-bit random values, **rotated on login and on privilege change**.
- **CSRF:** SameSite=Strict, plus a synchronizer token that must be echoed in the `X-CSRF-Token` header on state-changing console requests. Customer APIs use bearer tokens, not cookies, so they are not CSRF-prone.
- **Brute force:**
  - Per-account and per-IP counters in Redis, with exponential backoff.
  - Soft lock after 10 failures, with owner notification.
  - Credential-stuffing detection: many accounts from one IP or ASN triggers a Cloudflare challenge.
  - Generic error messages, so the response does not reveal whether a user exists.
- **Break-glass account:** one sealed Super Admin credential (a hardware key plus an offline recovery code) kept in two physical locations. It is **disabled by default**. Enabling it requires host-level access, posts to the Ops bot, and every use is reviewed.

## 4. Service-to-service and API tokens

- Internal calls between process roles pass through the database (outbox and jobs) or through signed internal tokens (EdDSA, 60-second lifetime, audience-bound). There is no shared static "internal API key".
- Partner or API keys (future) are shown once, stored hashed (SHA-256 with a prefix id), tenant-scoped, permission-scoped, rate-limited and expiring.

## 5. Webhook security

| Source | Verification |
|---|---|
| Telegram | Per-bot `secret_token` header (constant-time comparison) on an unguessable route key; dedupe by `update_id` |
| Payment providers | Provider signature scheme per adapter, using that configuration's credentials; dedupe by provider event id; state confirmed via a status query before crediting |
| Cloudflare (future notifications) | Signed payload or Access service token |

Webhook paths accept `POST` only (WAF rule and app check). Bodies are limited to 256 KB and parsed only after verification.

## 6. Secrets management (ADR-017)

**Application-held secrets** (bot tokens, provider credentials, per-merchant API keys) use **envelope encryption**:

- A random 256-bit **DEK** per record encrypts the secret with AES-256-GCM.
- **AAD** = `table|record_id|tenant_id|purpose`. A ciphertext copied onto another tenant's row fails to decrypt.
- The DEK is wrapped by the **KEK**, which is versioned (`key_version`).
- The KEK is **never in the database or the image**. In Phase 1 it is a Docker secret or systemd credential file on the host, readable only by the app user and loaded at start. Later it can move to OpenBao/Vault transit, behind the same `KeyProvider` interface.
- Rotation: `rewrap` jobs re-encrypt DEKs under a new KEK version without touching plaintext at rest.
- Decrypted values live only in memory. Bot tokens are cached for 5 minutes in a process-local LRU.

**Infrastructure secrets** (database passwords, the tunnel credentials file, the Cloudflare API token, the KEK, the backup encryption key) are held in **a separate private ops repository**, encrypted with SOPS + age (or Ansible Vault) and rendered onto hosts by Ansible. **Nothing of this kind goes in this public repository.**

**Secret scanning** (directive §83):

- `gitleaks` runs as a pre-commit hook and as a **blocking** CI job.
- GitHub push protection is enabled.
- CI fails if any `.env*` other than `*.example` is tracked.
- A detected secret is **rotated first** and then purged from history.

## 7. Transport and headers

- TLS terminates at Cloudflare (Full-strict), and the tunnel is encrypted to the origin.
- Headers: HSTS, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` (minimal), and `frame-ancestors` restricted. The customer bundle allows Telegram's WebView embedding; the console allows `'none'`.
- **CSP** per bundle: `default-src 'self'`, no inline scripts (hashed only), images from `self` and `media.ROOT_DOMAIN`, and `connect-src` to `self` only.
- **Merchant-supplied rich text** (descriptions) is sanitised to an allow-list of tags with a server-side sanitiser, and rendered without `dangerouslySetInnerHTML` except through the sanitised path.

## 8. File and media pipeline (directive §56)

1. The client requests an upload slot (`POST /api/v1/media/uploads`). The server checks quota and permission and returns a **pre-signed PUT** to a *quarantine* prefix `q/t/{tenant}/{uuid}`, with an exact size limit and content type.
2. The worker validates:
   - magic bytes match the declared MIME type (allow-list: JPEG, PNG, WebP, AVIF, PDF)
   - dimensions and size
   - image re-encoding strips EXIF and GPS data and neutralises polyglot files
   - PDFs are checked with a sanitiser and a ClamAV scan
3. The worker writes variants (`thumb`, `card`, `full`, WebP) to `t/{tenant}/media/{asset_id}/{variant}` with immutable keys, and deletes the quarantine object.
4. Public listing images are served via `media.ROOT_DOMAIN` (cached). Private documents (IDs, contracts, delivery proofs) use **signed GET URLs** with a 5-minute lifetime, after an authorization check.
5. Filenames are never used as keys. The original name is stored as metadata, and sanitised for display only.

## 9. AI security (directive §40–43, §89)

- The AI gateway has **no database access**. It calls **registered tools**. Each tool:
  - declares its required permission and its data scope
  - runs through the normal authorization and RLS path **as the invoking principal**
  - returns data with PII fields redacted unless the principal can see them
- **Prompt injection is expected**, because product descriptions and customer messages are untrusted. Mitigations:
  - Tool outputs are data, not instructions.
  - Tool-calling policy is enforced server-side, never by the model's judgement.
  - **Financial or destructive tools cannot execute.** They return a *draft* plus a confirmation token that only a human UI action can redeem.
- AI actions are logged in `ai_actions` (tool, arguments hash, authorization result, cost). Per-tenant budgets and rate limits apply (`14` §6).
- Merchant and customer data sent to external model providers is minimised and governed by a data-processing agreement. A provider is selected only after its data-retention terms are reviewed.

## 10. Data protection

- PII inventory: phone numbers, names, addresses, identity documents and messages. PII columns are listed in `09-pii-inventory` (to be produced in Phase 1).
- Encryption at rest:
  - phone numbers and addresses use field-level encryption with the same envelope scheme, plus a keyed hash for lookups
  - disks are LUKS-encrypted
  - backups are encrypted (`13`)
- **Log redaction:** a structlog processor removes tokens, `initData`, `Authorization` headers, card-like and phone-like patterns, and every field marked `pii` in blueprints.
- **Retention:** raw provider payloads 7 years (finance); audit 7 years; analytics events 24 months, then aggregated; customer data deleted or anonymised on request, *except* where finance or legal retention applies. Ethiopia's personal data protection law is to be confirmed with counsel.

## 11. Supply chain and CI (directive §53)

| Check | Tool | Gate |
|---|---|---|
| Secrets | gitleaks | Blocking |
| Python dependencies | pip-audit (lockfile) | Blocking on high or critical severity with a fix available |
| JS dependencies | `pnpm audit` / osv-scanner | Same |
| SAST | Semgrep (Python, TS, Dockerfile rulesets) + Bandit | Blocking on high severity. **Not in CI yet**: today only ruff's `S` (flake8-bandit) rules run, as part of lint |
| Containers | Trivy (image + filesystem) | Blocking on critical severity. **As built:** CI scans the image only, gating `CRITICAL` with a fix available (`--severity CRITICAL --ignore-unfixed`); HIGH findings do not fail CI |
| IaC | Trivy config / Checkov on compose, Terraform, Ansible | Blocking on high severity |
| SBOM | Syft → attached to the release | — |
| Image provenance | Build on GitHub-hosted runners, push to GHCR with digest pinning; deploy by **digest**, never by `latest` | Required |
| Actions | Pinned by commit SHA; `permissions:` minimal per job; OIDC instead of long-lived tokens where possible | Required |
| Dependency updates | Renovate, grouped weekly, auto-merged for patch versions only when tests pass | — |

## 12. Audit trail: what is and is not guaranteed

Precise wording: **the audit trail is append-only for the application, and tamper-resistant; it is not tamper-proof and not tamper-evident.**

- **Guaranteed against the runtime role (`arada_app`):**
  - it holds only INSERT and SELECT on `control.audit_events`;
  - row triggers reject UPDATE and DELETE, and a statement trigger rejects TRUNCATE;
  - forced RLS confines reads and inserts to the transaction's tenant context;
  - no API route writes or edits audit records.

  Tests: `tests/integration/test_audit_db.py`.
- **Guaranteed against plain DML by the schema owner and the superuser.** Their ordinary UPDATE, DELETE and TRUNCATE are refused.
- **Not guaranteed against holders of the schema-owner or superuser credentials.**
  - The owner can `ALTER TABLE … DISABLE TRIGGER USER` and `NO FORCE ROW LEVEL SECURITY`, then rewrite rows.
  - A superuser can `SET session_replication_role = replica`, which skips triggers.

  This is demonstrated, not assumed, by `tests/integration/test_audit_db.py::test_known_limitation_schema_owner_can_disable_audit_guards`.
- **What mitigates it today:**
  - the owner credentials exist only in the one-shot `migrate` container, and the API container has no owner DSN;
  - the superuser password exists only in the bootstrap step.
- **Planned before real data:**
  - a hash chain or periodic signed checkpoints (tamper evidence);
  - shipping audit records off the database host.
