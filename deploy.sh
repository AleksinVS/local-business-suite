#!/bin/bash

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

VPS_HOST="${VPS_HOST:-188.120.246.243}"
VPS_USER="${VPS_USER:-admin}"
VPS_PORT="${VPS_PORT:-2222}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/openclaw_vps_ed25519}"
PROJECT_DIR="${PROJECT_DIR:-/home/admin/local-business-suite}"
COMPOSE_CMD="${COMPOSE_CMD:-sudo docker compose}"
PROD_PROJECT="${PROD_PROJECT:-local-business-suite-prod}"
LIBRECHAT_PROJECT="${LIBRECHAT_PROJECT:-local-business-suite-librechat}"
SHARED_NETWORK="${SHARED_NETWORK:-local-business-suite_internal}"

SSH_OPTS=(
  -i "${SSH_KEY}"
  -p "${VPS_PORT}"
  -o BatchMode=yes
  -o ConnectTimeout=8
)

echo -e "${YELLOW}=== Deploying Local Business Suite ===${NC}"
echo "VPS: ${VPS_USER}@${VPS_HOST}:${VPS_PORT}"
echo "Project dir: ${PROJECT_DIR}"

if [ ! -f ".env.production" ]; then
  echo -e "${RED}Missing .env.production in repo root${NC}"
  exit 1
fi

echo -e "${YELLOW}Checking SSH connection...${NC}"
ssh "${SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" "echo SSH OK >/dev/null"
echo -e "${GREEN}✓ SSH connection OK${NC}"

echo -e "${YELLOW}Creating remote directories...${NC}"
ssh "${SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" "mkdir -p '${PROJECT_DIR}'"

echo -e "${YELLOW}Syncing project files...${NC}"
rsync -avz --delete --progress \
  -e "ssh -i '${SSH_KEY}' -p ${VPS_PORT}" \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.git' \
  --exclude='db' \
  --exclude='media' \
  --exclude='caddy_data' \
  --exclude='logs' \
  --exclude='.env' \
  --exclude='.env.production' \
  ./ "${VPS_USER}@${VPS_HOST}:${PROJECT_DIR}/"

echo -e "${YELLOW}Uploading .env.production...${NC}"
scp -i "${SSH_KEY}" -P "${VPS_PORT}" .env.production \
  "${VPS_USER}@${VPS_HOST}:${PROJECT_DIR}/.env.production"

echo -e "${YELLOW}Rebuilding containers...${NC}"
ssh "${SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" <<EOF
set -euo pipefail
cd '${PROJECT_DIR}'
cp .env.production .env
grep -q '^LIBRECHAT_PUBLIC_URL=' .env || echo 'LIBRECHAT_PUBLIC_URL=http://${VPS_HOST}/librechat' >> .env
export LIBRECHAT_PUBLIC_URL_VALUE='http://${VPS_HOST}/librechat'
if [ ! -f services/librechat/.env ]; then
  bash services/librechat/generate-env.sh services/librechat/.env
fi
python3 - <<'PY'
import os
from pathlib import Path

prod = {}
for line in Path(".env.production").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    prod[key] = value

librechat = {}
target = Path("services/librechat/.env")
for line in target.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    librechat[key] = value

target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(
    "\n".join(
        [
            f"ALLOW_REGISTRATION={librechat.get('ALLOW_REGISTRATION', 'true')}",
            f"ALLOW_SOCIAL_LOGIN={librechat.get('ALLOW_SOCIAL_LOGIN', 'false')}",
            f"APP_TITLE={librechat.get('APP_TITLE', 'Local Business Suite AI Chat')}",
            f"ENDPOINTS={librechat.get('ENDPOINTS', 'openAI')}",
            f"OPENAI_MODELS={librechat.get('OPENAI_MODELS', prod.get('AI_AGENT_MODEL_NAME', 'gpt-4.1-mini'))}",
            f"LIBRECHAT_PUBLIC_URL={prod.get('LIBRECHAT_PUBLIC_URL', os.environ['LIBRECHAT_PUBLIC_URL_VALUE'])}",
            f"CREDS_KEY={librechat.get('CREDS_KEY', '')}",
            f"CREDS_IV={librechat.get('CREDS_IV', '')}",
            f"JWT_SECRET={librechat.get('JWT_SECRET', '')}",
            f"JWT_REFRESH_SECRET={librechat.get('JWT_REFRESH_SECRET', '')}",
            f"MEILI_MASTER_KEY={librechat.get('MEILI_MASTER_KEY', '')}",
            f"OPENAI_API_KEY={prod.get('OPENAI_API_KEY', librechat.get('OPENAI_API_KEY', ''))}",
            f"OPENAI_BASE_URL={prod.get('OPENAI_BASE_URL', librechat.get('OPENAI_BASE_URL', ''))}",
            f"AI_AGENT_MODEL_NAME={prod.get('AI_AGENT_MODEL_NAME', librechat.get('AI_AGENT_MODEL_NAME', 'gpt-4.1-mini'))}",
        ]
    )
    + "\n"
)
PY
docker network inspect '${SHARED_NETWORK}' >/dev/null 2>&1 || docker network create '${SHARED_NETWORK}' >/dev/null
if command -v docker-compose >/dev/null 2>&1; then
  sudo docker-compose -f docker-compose.prod.yml down --remove-orphans || true
  sudo docker-compose -f docker-compose.prod.yml -f docker-compose.librechat.yml down --remove-orphans || true
fi
${COMPOSE_CMD} -p '${PROD_PROJECT}' -f docker-compose.prod.yml down --remove-orphans
${COMPOSE_CMD} -p '${PROD_PROJECT}' -f docker-compose.prod.yml up -d --build
${COMPOSE_CMD} -p '${LIBRECHAT_PROJECT}' -f docker-compose.librechat.yml -f docker-compose.librechat.prod.yml down --remove-orphans
${COMPOSE_CMD} -p '${LIBRECHAT_PROJECT}' -f docker-compose.librechat.yml -f docker-compose.librechat.prod.yml up -d --build
sleep 10
${COMPOSE_CMD} -p '${PROD_PROJECT}' -f docker-compose.prod.yml ps
${COMPOSE_CMD} -p '${LIBRECHAT_PROJECT}' -f docker-compose.librechat.yml -f docker-compose.librechat.prod.yml ps
EOF

echo -e "${GREEN}✓ Deployment completed${NC}"
echo "App URL: http://${VPS_HOST}"
echo "LibreChat: http://${VPS_HOST}/librechat/"
echo "Health:  http://${VPS_HOST}/health/"
echo "Logs:    ssh -i ${SSH_KEY} -p ${VPS_PORT} ${VPS_USER}@${VPS_HOST} 'cd ${PROJECT_DIR} && ${COMPOSE_CMD} -p ${PROD_PROJECT} -f docker-compose.prod.yml logs -f'"
