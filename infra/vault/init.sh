#!/bin/sh
# Vault dev-mode bootstrap script.
# In production self-host, replace with proper AppRole setup + unseal procedure.
# See Phase 5 §5.7.1 for the secret-zero bootstrapping design.

set -e

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
ROOT_TOKEN="${VAULT_DEV_ROOT_TOKEN:-dev-root-token}"

echo "Waiting for Vault to be ready..."
until vault status -address="$VAULT_ADDR" > /dev/null 2>&1; do
  sleep 1
done

export VAULT_ADDR VAULT_TOKEN="$ROOT_TOKEN"

# Enable KV v2 at the 'secret' mount (already enabled in dev mode)
vault secrets enable -version=2 kv 2>/dev/null || true

# Create the sprawl policy (least-privilege: only connector creds path)
vault policy write sprawl-api - <<'EOF'
path "secret/data/sprawl/connectors/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "secret/metadata/sprawl/connectors/*" {
  capabilities = ["list", "read", "delete"]
}
EOF

# Enable AppRole auth
vault auth enable approle 2>/dev/null || true

# Create AppRole for api + worker (secret-zero, §5.7.1)
vault write auth/approle/role/sprawl-api \
  token_policies="sprawl-api" \
  token_ttl=1h \
  token_max_ttl=4h

# Output role_id (secret_id generated separately and injected by operator)
ROLE_ID=$(vault read -field=role_id auth/approle/role/sprawl-api/role-id)
echo "Vault AppRole role_id: $ROLE_ID"
echo "Run the following to generate a secret_id (inject as VAULT_SECRET_ID):"
echo "  vault write -f auth/approle/role/sprawl-api/secret-id"
