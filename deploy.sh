#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/root/crypto-algo-bot"
PYTHON_BIN="/root/miniconda3/bin/python"
ENV_FILE="$APP_DIR/.env"

SERVICE_1="stochvol-bot"
SERVICE_2="stochvol-bot-2"

echo "==> deploy: starting"
cd "$APP_DIR"

echo "==> git status before deploy"
git status --short || true

echo "==> fetching latest"
git fetch origin

echo "==> resetting tracked files to origin/main"
git reset --hard origin/main

echo "==> cleaning untracked junk but preserving runtime state"
git clean -fd \
  -e .env \
  -e 'live/*.log' \
  -e 'live/*.csv' \
  -e 'live/*.json' \
  -e 'data/candles/' \
  -e 'data/*.db'

echo "==> validating .env exists"
test -f "$ENV_FILE"

echo "==> validating required env keys"
grep -q '^TELEGRAM_TOKEN=' "$ENV_FILE"
grep -q '^HL_WALLET1_PRIVATE_KEY=' "$ENV_FILE"
grep -q '^HL_WALLET1_WALLET_ADDRESS=' "$ENV_FILE"
grep -q '^HL_WALLET2_PRIVATE_KEY=' "$ENV_FILE"
grep -q '^HL_WALLET2_WALLET_ADDRESS=' "$ENV_FILE"

echo "==> compile check"
$PYTHON_BIN -m py_compile \
  "$APP_DIR/live/executor_stochvol.py" \
  "$APP_DIR/live/executor_stochvol_2.py" \
  "$APP_DIR/live/heartbeat.py" \
  "$APP_DIR/live/circuit_breaker.py"

echo "==> restarting services"
systemctl restart "$SERVICE_1"
systemctl restart "$SERVICE_2"

echo "==> waiting for services"
sleep 8

echo "==> service status"
systemctl is-active "$SERVICE_1"
systemctl is-active "$SERVICE_2"

echo "==> last logs"
tail -10 "$APP_DIR/live/stochvol.log" || true
tail -10 "$APP_DIR/live/stochvol2.log" || true

echo "==> deploy: success"
