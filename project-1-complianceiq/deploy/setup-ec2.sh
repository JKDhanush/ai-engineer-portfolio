#!/usr/bin/env bash
# One-time server setup for Ubuntu 24.04 on EC2. Paste into "User data" when launching the instance,
# or run it once over SSH:  bash setup-ec2.sh
set -euxo pipefail

# Docker Engine + Compose plugin from Docker's official repository
apt-get update
apt-get install -y ca-certificates curl git make
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker ubuntu

# 4 GB swap: a safety net while the models load next to Postgres on an 8 GB machine
if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# The code (public repo, read-only clone)
sudo -u ubuntu git clone https://github.com/JKDhanush/ai-engineer-portfolio.git /home/ubuntu/ai-engineer-portfolio || true
echo "Setup done. Next: create project-1-complianceiq/.env on the server (see deploy/README.md)."
