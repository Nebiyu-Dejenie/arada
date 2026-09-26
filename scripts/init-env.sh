#!/usr/bin/env bash
# Generate a local .env with random development secrets.
#
# Nothing here is a real credential, but it is still generated rather than
# committed: the repository never contains passwords or keys (Permanent
# Command §28). Existing values are kept, so re-running is safe.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

set_if_missing() {
  local key="$1" value="$2"
  if ! grep -q "^${key}=" "$ENV_FILE"; then
    printf '%s=%s\n' "$key" "$value" >>"$ENV_FILE"
  fi
}

hex() { python3 -c 'import secrets; print(secrets.token_hex(24))'; }

set_if_missing ARADA_PG_SUPERUSER_PASSWORD "$(hex)"
set_if_missing ARADA_DB_OWNER_PASSWORD "$(hex)"
set_if_missing ARADA_DB_APP_PASSWORD "$(hex)"
set_if_missing ARADA_DB_READER_PASSWORD "$(hex)"
set_if_missing ARADA_KEK_BASE64 "$(python3 -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())')"
set_if_missing ARADA_PG_PORT 55432
set_if_missing ARADA_API_PORT 58000

echo "wrote $ENV_FILE (mode 600); values are local development secrets only"
