# 00 — Phase 0 Discovery

Status: **Complete** · Date: 2026-09-26 · Revised the same day after the owner's Permanent Command (`charter/PERMANENT_COMMAND.md`)

These are evidence-based findings (Permanent Command §55, Phase 0), classified as KNOWN / ASSUMED / UNKNOWN. The live register is in `20_DECISIONS.md` §2.

---

## 1. This repository (KNOWN)

| Item | Observed |
|---|---|
| Local path | `arada/`. It was empty before Phase 0. |
| Remote | `github.com/Nebiyu-Dejenie/arada`, **public** |
| Consequence | No secrets, internal hostnames, IP addresses, tunnel identifiers or provider credentials may ever enter this repository. Infrastructure secrets belong in a separate private operations repository (`09_SECURITY.md` §6). Whether the repository stays public is question U9. |

## 2. Other projects on the development workstation (KNOWN: unrelated)

The workstation hosts several other projects, including ones that use the domains `arada.fun` and `arada.click`. **The owner has stated these are unrelated to ARADA** (Permanent Command §26, §51). Therefore:

- ARADA shares **no code, runtime, database, tunnel, credentials or domain** with them (ADR-021).
- Nothing is imported from them. Only general engineering lessons observed there inform this design (§6).

## 3. Domain and Cloudflare (KNOWN: TBD)

- `ROOT_DOMAIN = TBD` (ADR-026). It is supplied by the owner at the domain phase and used only as configuration.
- The `cloudflared` CLI on the workstation is authenticated to a Cloudflare account that contains tunnels. One of them, named `arada`, has no active connections. **Its purpose is UNKNOWN**, so it will not be used unless the owner confirms it belongs to this project. Directive: one project tunnel initially.

## 4. Infrastructure (UNKNOWN until a phase needs it)

- Production and staging machines are **unknown** (U2) and will not be guessed (Permanent Command §25, §52, §54).
- The development workstation is KNOWN: Ubuntu 24.04 on WSL2, Docker 29, Compose v2.29, Python 3.12, Node 22, Ansible, Terraform, GitHub CLI and `cloudflared`. This is enough to build and test Phases 1–4 entirely on local Docker.

## 5. Telegram and payment requirements (verified against official sources)

- **Mini App authentication** (Telegram docs, checked 2026-09-26): server-side HMAC-SHA256 validation of `initData` using a secret derived from the bot token with the key `WebAppData`, plus an Ed25519 `signature` field that third parties can verify with Telegram's published public keys. `auth_date` should be checked for freshness.
- **Managed bots** (Bot API 9.6+): a bot with management enabled in @BotFather can ask a user to create a bot that it manages (`KeyboardButtonRequestManagedBot`). It receives `managed_bot` updates, fetches and rotates the token (`getManagedBotToken`, `replaceManagedBotToken`), and can restrict access (`setManagedBotAccessSettings`). **Each bot still requires the user's action to create it.** Limits and API coverage beyond this are UNKNOWN (U6) and will be verified before Phase 2 builds on them.
- **Main Mini App and direct-link Mini Apps** are configured in @BotFather.
- **Payments:** the platform must not assume it may hold or settle customer funds without checking the National Bank of Ethiopia's framework and provider agreements (U4). **SMS alone is never proof of payment** (Permanent Command §16).

## 5a. Patterns worth applying (general engineering practice; nothing imported)

| Pattern | Applied in |
|---|---|
| `initData` validation with constant-time comparison, freshness and future-date rejection, never logging raw `initData` | `04` §5 |
| A double-entry ledger whose zero-sum invariant is enforced by a deferred database constraint trigger, with idempotency keys that detect reuse across operation kinds | `08` §1 |
| A provider-agnostic payment protocol with signature verification, status queries and payouts | `07` §2 |
| An explicit per-permission RBAC catalogue with no god-mode bypass | `10` |
| Trusting `CF-Connecting-IP` only behind a tunnel-only ingress | `05` §7 |
| Integration tests against real Postgres and Redis; strict type checking; secret scanning | `09` §11, `19` |

## 6. Lessons: failure modes this design must prevent

Each lesson is general engineering practice, and each is mapped to a control.

1. **Ingress configuration living outside version control** can silently drift or vanish. → All routing lives in git (`05` §7, ADR-010).
2. **Unrelated stacks sharing a Docker network** can resolve an ambiguous service alias to *another application's database*. → One isolated network per stack, host-unique container names, no shared networks (`11` §2).
3. **Backups on the same disk as the database** fail together with it. → Encrypted off-host backups with automated restore verification (`13`).
4. **Alert rules with no deployed evaluator** never fire. → The observability stack is part of Phase 1, and a test alert must arrive end to end (`12`).
5. **Payment confirmation from SMS parsing** is not authoritative. → Provider APIs, signed callbacks and reconciliation only (`07`).
6. **Identity keyed to one channel's user id** blocks new channels. → Provider-agnostic identity (ADR-024).
7. **A single bot token in environment configuration** does not scale to per-merchant bots. → Encrypted, rotatable per-merchant bot credentials (`04`).
8. **A single host as all of production** is a single point of failure. → A separate data tier and documented RPO/RTO (`11`, `13`).
9. **Template `.env` files that once held real values** leak secrets. → Blocking secret scanning in pre-commit and CI (`09` §6).

## 7. Implications

- Phases 1–4 can be built and fully tested on local Docker with **no** domain, machines, payment credentials or Telegram production bots. External dependencies sit behind adapters with documented boundaries (Permanent Command §33).
- The first real deployment (Phase 5, or earlier for staging) needs U1–U3 answered. The owner will be asked at that point, not before.
