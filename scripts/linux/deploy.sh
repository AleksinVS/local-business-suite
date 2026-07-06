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
SHARED_NETWORK="${SHARED_NETWORK:-local-business-suite_internal}"

SSH_OPTS=(
  -i "${SSH_KEY}"
  -p "${VPS_PORT}"
  -o BatchMode=yes
  -o ConnectTimeout=8
)

echo -e "${YELLOW}=== Deploying Корпоративный портал ВОБ №3 ===${NC}"
echo "VPS: ${VPS_USER}@${VPS_HOST}:${VPS_PORT}"
echo "Project dir: ${PROJECT_DIR}"

if [ ! -f "deployments/test-host/.env" ]; then
  echo -e "${RED}Missing deployments/test-host/.env for target host${NC}"
  exit 1
fi

echo -e "${YELLOW}Checking SSH connection...${NC}"
ssh "${SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" "echo SSH OK >/dev/null"
echo -e "${GREEN}✓ SSH connection OK${NC}"

echo -e "${YELLOW}Creating remote directories...${NC}"
ssh "${SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" "mkdir -p '${PROJECT_DIR}/deployments/test-host' && mkdir -p '${PROJECT_DIR}/data'"

echo -e "${YELLOW}Syncing project files...${NC}"
rsync -avz --delete --progress \
  -e "ssh -i '${SSH_KEY}' -p ${VPS_PORT}" \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.git' \
  --exclude='data/' \
  --exclude='caddy_data/' \
  --exclude='.env' \
  --exclude='deployments/*/.env' \
  ./ "${VPS_USER}@${VPS_HOST}:${PROJECT_DIR}/"

echo -e "${YELLOW}Uploading host secrets...${NC}"
scp -i "${SSH_KEY}" -P "${VPS_PORT}" deployments/test-host/.env \
  "${VPS_USER}@${VPS_HOST}:${PROJECT_DIR}/deployments/test-host/.env"

echo -e "${YELLOW}Rebuilding containers...${NC}"
ssh "${SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" <<EOF
set -euo pipefail
cd '${PROJECT_DIR}'
# docker-compose.prod.yml host-agnostic: путь к env-файлу хоста задаётся здесь,
# в host-специфичном деплой-скрипте, а не в самом compose (см. AGENTS.md,
# изоляция сред развёртывания).
export LOCAL_BUSINESS_ENV_FILE=deployments/test-host/.env
# Ensure local .env exists for compose if needed (though prod uses env_file)
cp deployments/test-host/.env .env
docker network inspect '${SHARED_NETWORK}' >/dev/null 2>&1 || docker network create '${SHARED_NETWORK}' >/dev/null
${COMPOSE_CMD} -p '${PROD_PROJECT}' -f docker-compose.prod.yml down --remove-orphans
${COMPOSE_CMD} -p '${PROD_PROJECT}' -f docker-compose.prod.yml up -d --build
sleep 10
${COMPOSE_CMD} -p '${PROD_PROJECT}' -f docker-compose.prod.yml ps
EOF

echo -e "${GREEN}✓ Deployment completed${NC}"
echo "App URL: http://${VPS_HOST}"
echo "Health:  http://${VPS_HOST}/health/"
echo "Logs:    ssh -i ${SSH_KEY} -p ${VPS_PORT} ${VPS_USER}@${VPS_HOST} 'cd ${PROJECT_DIR} && ${COMPOSE_CMD} -p ${PROD_PROJECT} -f docker-compose.prod.yml logs -f'"