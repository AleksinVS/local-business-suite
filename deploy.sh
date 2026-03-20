#!/bin/bash

# Deployment Script for Local Business Suite
# Usage: ./deploy.sh [environment]
# Example: ./deploy.sh production

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
ENV=${1:-production}
VPS_HOST="188.120.246.243"
VPS_USER="admin"
VPS_PORT="2222"
SSH_KEY="$HOME/.ssh/openclaw_vps_ed25519"
PROJECT_DIR="/home/admin/local-business-suite"
COMPOSE_CMD="docker-compose"

echo -e "${YELLOW}=== Deploying Local Business Suite to ${ENV} ===${NC}"
echo -e "VPS: ${VPS_HOST}"
echo -e "SSH: ${VPS_USER}@${VPS_HOST}:${VPS_PORT}"
echo ""

# Check SSH connection
echo -e "${YELLOW}Checking SSH connection...${NC}"
if ! ssh -i "${SSH_KEY}" -p "${VPS_PORT}" -o ConnectTimeout=5 "${VPS_USER}@${VPS_HOST}" "echo 'SSH OK'"; then
    echo -e "${RED}❌ SSH connection failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ SSH connection OK${NC}"
echo ""

# Create project directory on VPS
echo -e "${YELLOW}Creating project directory...${NC}"
ssh -i "${SSH_KEY}" -p "${VPS_PORT}" "${VPS_USER}@${VPS_HOST}" "mkdir -p ${PROJECT_DIR}"
echo -e "${GREEN}✓ Directory created${NC}"
echo ""

# Copy files to VPS
echo -e "${YELLOW}Copying files to VPS...${NC}"
rsync -avz --progress \
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
    ./ \
    "${VPS_USER}@${VPS_HOST}:${PROJECT_DIR}/"
echo -e "${GREEN}✓ Files copied${NC}"
echo ""

# Copy .env.production to VPS if it exists locally
if [ -f ".env.production" ]; then
    echo -e "${YELLOW}Uploading .env.production...${NC}"
    scp -i "${SSH_KEY}" -P "${VPS_PORT}" .env.production \
        "${VPS_USER}@${VPS_HOST}:${PROJECT_DIR}/.env.production"
    echo -e "${GREEN}✓ Environment file uploaded${NC}"
else
    echo -e "${RED}⚠️  Warning: .env.production not found${NC}"
fi
echo ""

# Build and start containers on VPS
echo -e "${YELLOW}Building and starting containers...${NC}"
ssh -i "${SSH_KEY}" -p "${VPS_PORT}" "${VPS_USER}@${VPS_HOST}" << EOF
cd ${PROJECT_DIR}

# Stop existing containers
${COMPOSE_CMD} -f docker-compose.prod.yml down

# Build and start
${COMPOSE_CMD} -f docker-compose.prod.yml up -d --build

# Wait for health check
echo "Waiting for health check..."
sleep 10

# Show logs
${COMPOSE_CMD} -f docker-compose.prod.yml logs --tail=20
EOF

echo -e "${GREEN}✓ Deployment completed!${NC}"
echo ""
echo -e "${GREEN}Access your app at: http://${VPS_HOST}${NC}"
echo -e "${YELLOW}View logs: ssh -i ${SSH_KEY} -p ${VPS_PORT} ${VPS_USER}@${VPS_HOST} 'cd ${PROJECT_DIR} && docker-compose -f docker-compose.prod.yml logs -f'${NC}"
echo ""
