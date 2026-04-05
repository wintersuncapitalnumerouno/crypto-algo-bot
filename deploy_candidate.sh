#!/usr/bin/env bash
set -euo pipefail

# =============================================================
# deploy_candidate.sh — Deploy V5 candidate to Wallet 1 ONLY
# =============================================================
# This script:
#   1. Pulls latest code
#   2. Validates candidate files exist and compile
#   3. Switches Wallet 1 service to V5 candidate executor
#   4. Restarts Wallet 1 ONLY — Wallet 2 (control) untouched
#   5. Verifies startup
#
# Rollback:
#   bash rollback_candidate.sh
# =============================================================

APP_DIR="/root/crypto-algo-bot"
PYTHON_BIN="/root/miniconda3/bin/python"
ENV_FILE="$APP_DIR/.env"

SERVICE_CANDIDATE="stochvol-bot-2"   # Wallet 1
SERVICE_CONTROL="stochvol-bot"       # Wallet 2 — NOT touched

CANDIDATE_EXEC="live/executor_stochvol_v5_candidate.py"
PRODUCTION_EXEC="live/executor_stochvol_2.py"
SERVICE_FILE="/etc/systemd/system/stochvol-bot-2.service"

echo "==> candidate deploy: starting"
cd "$APP_DIR"

# ── Pull latest code ────────────────────────────────────────
echo "==> fetching latest"
git fetch origin
git reset --hard origin/main

echo "==> cleaning untracked junk (preserving runtime state)"
git clean -fd \
  -e .env \
  -e 'live/*.log' \
  -e 'live/*.csv' \
  -e 'live/*.json' \
  -e 'data/candles/' \
  -e 'data/*.db'

# ── Validate ────────────────────────────────────────────────
echo "==> validating .env"
test -f "$ENV_FILE"
grep -q '^HL_WALLET1_PRIVATE_KEY=' "$ENV_FILE"
grep -q '^HL_WALLET1_WALLET_ADDRESS=' "$ENV_FILE"

echo "==> validating candidate files exist"
test -f "$APP_DIR/$CANDIDATE_EXEC"
test -f "$APP_DIR/live/signal_engine_v5_candidate.py"
test -f "$APP_DIR/strategies/stochvol/params_v5_candidate.py"

echo "==> compile check (candidate + control)"
$PYTHON_BIN -m py_compile "$APP_DIR/$CANDIDATE_EXEC"
$PYTHON_BIN -m py_compile "$APP_DIR/live/signal_engine_v5_candidate.py"
$PYTHON_BIN -m py_compile "$APP_DIR/strategies/stochvol/params_v5_candidate.py"
$PYTHON_BIN -m py_compile "$APP_DIR/live/executor_stochvol.py"
$PYTHON_BIN -m py_compile "$APP_DIR/live/executor_stochvol_2.py"

# ── Back up current service file ────────────────────────────
echo "==> backing up service file"
cp "$SERVICE_FILE" "${SERVICE_FILE}.bak"

# ── Switch Wallet 1 to candidate executor ───────────────────
echo "==> switching Wallet 1 service to V5 candidate"
sed -i "s|ExecStart=.*executor_stochvol_2.py|ExecStart=$PYTHON_BIN $CANDIDATE_EXEC|" "$SERVICE_FILE"
systemctl daemon-reload

# ── Restart candidate ONLY ──────────────────────────────────
echo "==> restarting candidate (Wallet 1) ONLY"
systemctl restart "$SERVICE_CANDIDATE"

echo "==> waiting for startup"
sleep 8

# ── Verify ──────────────────────────────────────────────────
echo "==> candidate service status"
systemctl is-active "$SERVICE_CANDIDATE"

echo "==> control service status (should be unchanged)"
systemctl is-active "$SERVICE_CONTROL"

echo "==> candidate last logs"
tail -15 "$APP_DIR/live/stochvol2.log" || true

echo ""
echo "==> VERIFY: look for 'V5-candidate' in the logs above"
echo "==> VERIFY: look for 'entry_window=4 | vol_min_ratio=0.2'"
echo ""
echo "==> candidate deploy: success"
echo "==> control (Wallet 2) was NOT restarted"
