#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-services/librechat/.env}"

random_hex() {
  openssl rand -hex "$1"
}

cat > "$TARGET" <<EOF
ALLOW_REGISTRATION=true
APP_TITLE=Local Business Suite AI Chat
ENDPOINTS=openAI
OPENAI_MODELS=gpt-4.1-mini,gpt-4.1,gpt-4o-mini
LIBRECHAT_PUBLIC_URL=http://localhost:3080
CREDS_KEY=$(random_hex 32)
CREDS_IV=$(random_hex 16)
JWT_SECRET=$(random_hex 32)
JWT_REFRESH_SECRET=$(random_hex 32)
MEILI_MASTER_KEY=$(random_hex 32)
EOF

echo "LibreChat env written to $TARGET"
