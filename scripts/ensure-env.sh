#!/bin/sh
# Create .env if it is missing, then replace any placeholder secret with real
# entropy.
#
# Why this exists:  JWT_SECRET signs access tokens AND keys the HMAC on the
# presigned artifact URLs (backend/app/storage/store.py).  docker-compose.yml
# carries a fallback so that a clean clone starts with one command -- but that
# fallback is a constant published in this repository, so anyone who reads the
# repo can forge a session for any user and mint a download token for any
# storage key.  `make up` and `make up-build` both depend on this script, so
# there is no path through the documented quick start that boots on it.
#
# It is deliberately a no-op once a real value is present: regenerating the
# secret on every `make up` would sign every user out on every restart.

set -eu

ENV_FILE=".env"
EXAMPLE_FILE=".env.example"

# Secrets that must never keep their placeholder value.  Add a name here and it
# is filled on the next `make up`.
KEYS="JWT_SECRET"

if [ ! -f "$ENV_FILE" ]; then
  if [ ! -f "$EXAMPLE_FILE" ]; then
    echo "ensure-env: no $ENV_FILE and no $EXAMPLE_FILE to copy from" >&2
    exit 1
  fi
  cp "$EXAMPLE_FILE" "$ENV_FILE"
  echo "created $ENV_FILE from $EXAMPLE_FILE"
fi

random_hex_32() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_hex(32))'
  elif command -v python >/dev/null 2>&1; then
    python -c 'import secrets; print(secrets.token_hex(32))'
  else
    echo "ensure-env: need openssl or python to generate a secret" >&2
    exit 1
  fi
}

# A value is a placeholder if it is empty, is the published compose fallback,
# shouts CHANGE_ME, or is too short to be 32 bytes of hex.  A real secret never
# matches any of these.
is_placeholder() {
  case "$1" in
    "" | CHANGE_ME* | dev-only-insecure-secret-change-me | *change-me*) return 0 ;;
  esac
  [ "${#1}" -lt 32 ]
}

for key in $KEYS; do
  current=$(sed -n "s/^${key}=//p" "$ENV_FILE" | head -n 1)

  if ! is_placeholder "$current"; then
    continue
  fi

  new=$(random_hex_32)
  tmp=$(mktemp)

  if grep -q "^${key}=" "$ENV_FILE"; then
    # Rewrite in place so the key keeps its position and its comment context.
    awk -v k="$key" -v n="$new" '
      $0 ~ "^" k "=" { print k "=" n; next }
      { print }
    ' "$ENV_FILE" >"$tmp"
  else
    cat "$ENV_FILE" >"$tmp"
    printf '%s=%s\n' "$key" "$new" >>"$tmp"
  fi

  mv "$tmp" "$ENV_FILE"
  echo "ensure-env: generated $key (32 bytes) - any existing session is now invalid"
done
