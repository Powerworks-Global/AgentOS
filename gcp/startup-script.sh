#!/bin/bash
set -euo pipefail

# AgentOS pilot VM startup script. Installs the tooling the headless pipeline
# needs, pulls credentials from Secret Manager (never baked into the image or
# this script), and deploys the pilot code from its public repo.

exec > >(tee -a /var/log/agentos-startup.log) 2>&1
echo "[startup] $(date -u) starting"

# --- base packages -----------------------------------------------------
apt-get update -y
apt-get install -y --no-install-recommends \
  git curl ca-certificates gnupg python3 python3-venv python3-pip docker.io

systemctl enable --now docker
usermod -aG docker "$(logname 2>/dev/null || echo root)" || true

# Node.js 22 (matches the version the pilot was developed against)
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y --no-install-recommends nodejs

# GitHub CLI
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  -o /usr/share/keyrings/githubcli-archive-keyring.gpg
chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  > /etc/apt/sources.list.d/github-cli.list
apt-get update -y
apt-get install -y --no-install-recommends gh

# Claude Code CLI (the agentos_pilot's ClaudeAgentOptions drives this binary)
npm install -g @anthropic-ai/claude-code

# --- credentials, pulled at boot from Secret Manager, never written to disk
# outside root-only env files -------------------------------------------
mkdir -p /etc/agentos
chmod 700 /etc/agentos

ANTHROPIC_API_KEY="$(gcloud secrets versions access latest --secret=anthropic-api-key)"
GITHUB_PAT="$(gcloud secrets versions access latest --secret=github-pat)"

cat > /etc/agentos/env <<EOF
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
EOF
chmod 600 /etc/agentos/env

echo "${GITHUB_PAT}" | gh auth login --with-token
gh auth setup-git

# --- deploy the pilot code ----------------------------------------------
mkdir -p /opt/agentos
if [ ! -d /opt/agentos/pilot/.git ]; then
  git clone https://github.com/Powerworks/AgentOS.git /opt/agentos/pilot
fi
cd /opt/agentos/pilot
git pull --ff-only

python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e . -q

echo "[startup] $(date -u) done"
