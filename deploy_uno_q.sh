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

# 1. Install system-level OpenCV V4L2 camera & Python dependencies (non-fatal if captive portal/firewall)
if command -v apt-get >/dev/null 2>&1; then
  echo "[1/4] Checking Linux V4L2 & Python3 dependencies..."
  sudo apt-get update -y || echo "Peringatan: apt-get update dilewati (menggunakan paket bawaan board)."
  sudo apt-get install -y python3 python3-pip python3-venv v4l-utils libgl1 libglib2.0-0 || echo "Peringatan: Paket sistem sudah terpasang atau dilewati."
  sudo usermod -aG video,dialout "${USER}" 2>/dev/null || true
fi

# 2. Setup virtual environment and install Python packages
echo "[2/4] Setting up Python virtual environment..."
if [ ! -d "${APP_DIR}/.venv" ]; then
  python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

# 3. Configure permanent udev rule for Qualcomm USB Host Mode & Video permissions
echo "[3/5] Configuring permanent udev hardware rules for USB Host Mode..."
UDEV_FILE="/etc/udev/rules.d/99-uno-q-usb-host.rules"
sudo bash -c "cat > ${UDEV_FILE}" <<'EOF'
# Force Qualcomm DWC3 USB controller into Host Mode immediately on boot and hotplug
SUBSYSTEM=="usb_role", RUN+="/bin/sh -c 'echo host > /sys%p/role 2>/dev/null || true'"

# Grant full read/write permissions for USB webcams and serial devices
KERNEL=="video*", MODE="0666", GROUP="video"
KERNEL=="ttyHS*|ttyMSM*|ttyACM*|ttyUSB*", MODE="0666", GROUP="dialout"
EOF

sudo udevadm control --reload-rules 2>/dev/null || true
sudo udevadm trigger 2>/dev/null || true

# 4. Configure permanent early-boot oneshot service to guarantee USB Host Mode on startup
echo "[4/5] Configuring early-boot USB Host service (uno-q-usb-host.service)..."
USB_HOST_SERVICE="/etc/systemd/system/uno-q-usb-host.service"
sudo bash -c "cat > ${USB_HOST_SERVICE}" <<'EOF'
[Unit]
Description=Arduino UNO Q Permanent USB Host & V4L2 Enabler
DefaultDependencies=no
After=systemd-modules-load.service
Before=basic.target multi-user.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c 'for r in /sys/class/usb_role/*/role; do echo host > "$r" 2>/dev/null || true; done; modprobe uvcvideo 2>/dev/null || true; modprobe videodev 2>/dev/null || true; chmod 666 /dev/video* 2>/dev/null || true'

[Install]
WantedBy=basic.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable uno-q-usb-host.service
sudo systemctl restart uno-q-usb-host.service || true

# 5. Create systemd service so server auto-starts on boot (power-on)
echo "[5/5] Configuring systemd auto-start service (${SERVICE_NAME}.service)..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo bash -c "cat > ${SERVICE_FILE}" <<EOF
[Unit]
Description=Ipomoea Edge-AIoT Unified FastAPI & 5-Stage Vision Server (Arduino UNO Q)
After=network.target uno-q-usb-host.service

[Service]
Type=simple
User=${USER}
SupplementaryGroups=video dialout
WorkingDirectory=${APP_DIR}
Environment="WEBCAM_INDEX=auto"
ExecStartPre=+/bin/bash -c 'for r in /sys/class/usb_role/*/role; do echo host > "\$r" 2>/dev/null || true; done; chmod 666 /dev/video* /dev/ttyHS* /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || true'
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/run_webapp.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"
sudo systemctl restart "${SERVICE_NAME}.service"

echo "[+] Deployment Complete!"
echo "----------------------------------------------------------------"
echo " Local Access (Wi-Fi / Hotspot) : http://$(hostname -I | awk '{print $1}'):8000"
echo " Check Service Status           : sudo systemctl status ${SERVICE_NAME}"
echo " Optional Cloud HTTPS Tunnel    : cloudflared tunnel --url http://localhost:8000"
echo "----------------------------------------------------------------"
