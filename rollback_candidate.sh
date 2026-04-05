#!/usr/bin/env bash
set -euo pipefail

# =============================================================
# rollback_candidate.sh — Revert Wallet 1 to V4 production
# =============================================================
# Restores the Wallet 1 service to run executor_stochvol_2.py
# (the V4 production executor).
# =============================================================

APP_DIR="/root/crypto-algo-bot"
PYTHON_BIN="/root/miniconda3/bin/python"
SERVICE_FILE="/etc/systemd/system/stochvol-bot-2.service"
SERVICE_CANDIDATE="stochvol-bot-2"

echo "==> rollback: reverting Wallet 1 to V4 production"
cd "$APP_DIR"

# ── Restore service file ────────────────────────────────────
if [ -f "${SERVICE_FILE}.bak" ]; then
    echo "==> restoring service file from backup"
    cp "${SERVICE_FILE}.bak" "$SERVICE_FILE"
else
    echo "==> no backup found, manually setting production executor"
    sed -i "s|ExecStart=.*|ExecStart=$PYTHON_BIN live/executor_stochvol_2.py|" "$SERVICE_FILE"
fi

systemctl daemon-reload

# ── Restart ─────────────────────────────────────────────────
echo "==> restarting Wallet 1 with V4 production"
systemctl restart "$SERVICE_CANDIDATE"

sleep 8

echo "==> service status"
systemctl is-active "$SERVICE_CANDIDATE"

echo "==> last logs (should show V4, NOT V5-candidate)"
tail -10 "$APP_DIR/live/stochvol2.log" || true

echo ""
echo "==> rollback: complete"
