# Runbook: local development and reproduction

Audience: engineers working on the ARADA backend. Requirements: Linux or WSL2, Docker with Compose v2, and [uv](https://docs.astral.sh/uv/). Python 3.12 is used through uv.

## 1. First run (from a fresh clone)

```bash
./scripts/init-env.sh                 # generates .env with random local secrets (gitignored, mode 600)
docker compose up -d --build --wait   # postgres -> role bootstrap -> migrations -> api
curl -s http://127.0.0.1:58000/readyz # {"status":"ready","database":"ok"}
```

Ports are bound to `127.0.0.1` only: the API on `ARADA_API_PORT` (default 58000) and PostgreSQL on `ARADA_PG_PORT` (default 55432). Change them in `.env` if another project already uses them.

## 2. Create the platform owner (once per database)

```bash
docker compose exec -e ARADA_BOOTSTRAP_PASSWORD='<a strong password>' api \
  arada admin bootstrap-superadmin --username owner --display-name "Platform Owner"
```

Then log in (`POST /v1/auth/login`) and enrol TOTP (`POST /v1/me/mfa/totp`, then `/confirm`). **`/confirm` returns a new token and revokes the old one; use the new token from then on.** Later logins need the TOTP code. **Platform and vertical permissions, and TENANT_OWNER / TENANT_ADMIN / TENANT_FINANCE permissions, are withheld until the session is MFA-verified.** API docs: `http://127.0.0.1:58000/docs` (off in production).

## 3. Tests and quality gates (same as CI)

```bash
cd backend
uv sync --frozen
uv run ruff check . ../scripts && uv run ruff format --check . ../scripts
uv run mypy
uv run lint-imports
uv run pytest -q                      # needs the compose postgres; each run creates and drops its own database
```

Set `ARADA_TEST_KEEP_DB=1` to keep the test database for inspection.

## 4. Reproduce Phase 1 from zero

```bash
./scripts/phase1_demo.sh
```

This builds the image, starts an **isolated** stack (its own project, volume, ports and secrets), migrates from zero, bootstraps the platform identity, runs the ten-step Definition-of-Done walkthrough over HTTP, and tears everything down. Set `ARADA_DEMO_KEEP=1` to keep the stack.

## 5. Indicative performance

```bash
ARADA_DEMO_KEEP=1 ARADA_DEMO_STATE=/tmp/state.json ./scripts/phase1_demo.sh
backend/.venv/bin/python scripts/measure_api.py --state-file /tmp/state.json
```

Numbers from a developer laptop are **not** sizing numbers (ADR-004 Evidence). Real sizing is measured on the target machines.

## 6. Telegram Mini App login (Phase 2)

Telegram logins are **off** until a key is configured. Every attempt then fails closed with the generic 401.

- `ARADA_TELEGRAM_ENVIRONMENT=test` and `ARADA_TELEGRAM_PUBLIC_KEY_HEX=<Telegram's test key>`. The key value is in ADR-012; it is public. A key that does not match the environment is refused at startup. Production accepts only Telegram's production key, and staging only a key Telegram publishes. A throwaway key works only in `development` and `test`.
- Bind a **test** bot to a tenant: `PUT /v1/platform/tenants/{id}/telegram-bot` with `{bot_id, bot_token}`, as a platform admin with MFA. Use a bot in Telegram's test environment, never a production bot.
- **Live conformance check (assumption A8).**
  1. Open the test bot's Mini App with a test account whose name has non-ASCII characters and a space.
  2. Copy `Telegram.WebApp.initData`, and note `Telegram.WebApp.initData.length`.
  3. Run `cd backend && pbpaste | uv run python ../scripts/telegram_sample_check.py --init-data-stdin`. Piping avoids the terminal's line limit (1024 bytes on macOS), which would silently cut a long sample. Without the flag, the script asks for the sample with hidden input. It asks for the bot id, token and key with hidden input either way.
  4. Check that the printed length equals `initData.length`. Then read the verdicts. Pass criteria and the failure procedure are in `docs/reports/PHASE_2.md` §9.
  5. The checker's output (MATCH/no, rule and field names, booleans, the length) contains no values and may be shared. **Never** paste the sample, the token, a hash, a signature, names or ids into the repository, an issue or a chat.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `port is already allocated` | Another project uses the port. Change `ARADA_API_PORT` / `ARADA_PG_PORT` in `.env`. |
| Tests fail with "database tests need PostgreSQL" | Run `./scripts/init-env.sh && docker compose up -d --wait postgres`. |
| `403 mfa-required-for-scope` (super admin, tenant owner, admin or finance) | Enrol and confirm TOTP, then use the token that `/confirm` returns, or log in with a TOTP code. |
| `401` right after confirming TOTP | Expected: the pre-MFA token was revoked by rotation. Use the new `access_token`. |
| `404` on another tenant's URL | Expected: non-members cannot see tenants (`02_TENANCY.md` §4). |
| Migrations fail with a role error | Roles are created by `arada db bootstrap-roles` (the `db-bootstrap` service). Run it before `arada db upgrade`. |
