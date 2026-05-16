#!/bin/bash

set -euo pipefail

echo "Configuring Docker access for the current user..."

if ! getent group docker >/dev/null 2>&1; then
  sudo groupadd docker
fi

if id -nG "$USER" | grep -qw docker; then
  echo "User '$USER' is already in docker group."
else
  echo "Adding '$USER' to docker group..."
  sudo usermod -aG docker "$USER"
fi

echo "Docker service status:"
sudo systemctl --no-pager --full status docker | sed -n '1,20p'

echo
echo "Log out and log back in for group changes to apply."
echo "Until then, use: sudo docker-compose -f docker-compose.prod.yml up -d --build"
