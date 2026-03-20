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
COMPOSE_CMD="${COMPOSE_CMD:-sudo docker-compose}"

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
  --exclude='.env.production' \
  ./ "${VPS_USER}@${VPS_HOST}:${PROJECT_DIR}/"

echo -e "${YELLOW}Uploading .env.production...${NC}"
scp -i "${SSH_KEY}" -P "${VPS_PORT}" .env.production \
  "${VPS_USER}@${VPS_HOST}:${PROJECT_DIR}/.env.production"

echo -e "${YELLOW}Rebuilding containers...${NC}"
ssh "${SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" <<EOF
set -euo pipefail
cd '${PROJECT_DIR}'
${COMPOSE_CMD} -f docker-compose.prod.yml down --remove-orphans
${COMPOSE_CMD} -f docker-compose.prod.yml up -d --build
sleep 10
${COMPOSE_CMD} -f docker-compose.prod.yml ps
EOF

echo -e "${GREEN}✓ Deployment completed${NC}"
echo "App URL: http://${VPS_HOST}"
echo "Health:  http://${VPS_HOST}/health/"
echo "Logs:    ssh -i ${SSH_KEY} -p ${VPS_PORT} ${VPS_USER}@${VPS_HOST} 'cd ${PROJECT_DIR} && ${COMPOSE_CMD} -f docker-compose.prod.yml logs -f'"
