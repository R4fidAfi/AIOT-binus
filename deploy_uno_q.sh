#!/usr/bin/env bash
# ==============================================================================
# One-Click Production Deployment Script for Arduino UNO Q (Dragonwing QRB2210)
# OS Target: Debian Linux ARM64 on Arduino UNO Q (2 GB RAM / 16 GB eMMC)
# ==============================================================================
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="ipomoea-edge"

echo "================================================================"
echo " Deploying Ipomoea Edge-AIoT Server on Arduino UNO Q"
echo " Workspace: ${APP_DIR}"
echo "================================================================"

# 1. Install system-level OpenCV V4L2 camera & Python dependencies
if command -v apt-get >/dev/null 2>&1; then
  echo "[1/4] Checking Linux V4L2 & Python3 dependencies..."
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-pip python3-venv v4l-utils libgl1 libglib2.0-0
fi

# 2. Setup virtual environment and install Python packages
echo "[2/4] Setting up Python virtual environment..."
if [ ! -d "${APP_DIR}/.venv" ]; then
  python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

# 3. Create systemd service so server auto-starts on boot (power-on)
echo "[3/4] Configuring systemd auto-start service (${SERVICE_NAME}.service)..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo bash -c "cat > ${SERVICE_FILE}" <<EOF
[Unit]
Description=Ipomoea Edge-AIoT Unified FastAPI & 5-Stage Vision Server (Arduino UNO Q)
After=network.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${APP_DIR}
Environment="WEBCAM_INDEX=0"
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/run_webapp.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"
sudo systemctl restart "${SERVICE_NAME}.service"

echo "[4/4] Deployment Complete!"
echo "----------------------------------------------------------------"
echo " Local Access (Wi-Fi / Hotspot) : http://$(hostname -I | awk '{print $1}'):8000"
echo " Check Service Status           : sudo systemctl status ${SERVICE_NAME}"
echo " Optional Cloud HTTPS Tunnel    : cloudflared tunnel --url http://localhost:8000"
echo "----------------------------------------------------------------"
