#!/bin/bash
# Виконати на Mac ПІСЛЯ того, як на ньому пройдено вхід у Claude Code і авторизацію Figma (/mcp).
# Витягує доступи Claude Code з Keychain і кладе їх на сервер. Використання: bash export_claude_creds.sh root@IP
set -e
SERVER="$1"; [ -z "$SERVER" ] && { echo "Використання: bash export_claude_creds.sh root@IP"; exit 1; }
security find-generic-password -s "Claude Code-credentials" -w > /tmp/cc_creds.json
ssh "$SERVER" "mkdir -p /root/.claude"
scp /tmp/cc_creds.json "$SERVER":/root/.claude/.credentials.json
scp ~/.claude.json "$SERVER":/root/.claude.json
ssh "$SERVER" "chmod 600 /root/.claude/.credentials.json"
rm /tmp/cc_creds.json
echo "Доступи скопійовано. На сервері перевірте: cd /root/bot && python3 cc_builder.py test"
