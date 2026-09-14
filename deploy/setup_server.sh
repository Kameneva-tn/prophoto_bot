#!/bin/bash
# Одноразове налаштування сервера Ubuntu 24.04 для PROPHOTO-бота. Запускати від root: bash setup_server.sh
set -e
apt-get update -y
apt-get install -y python3-pip python3-venv unzip curl git ca-certificates
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs
npm install -g @anthropic-ai/claude-code
cd /root/bot
pip3 install -r requirements.txt --break-system-packages
mkdir -p /root/.claude
cp deploy/prophoto-bot.service /etc/systemd/system/prophoto-bot.service
systemctl daemon-reload
systemctl enable prophoto-bot
echo
echo "Сервер готовий. Далі: скопіювати доступи Claude Code (див. README, розділ VPS) і виконати: systemctl start prophoto-bot"
