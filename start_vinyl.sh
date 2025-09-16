#!/usr/bin/env bash
set -euo pipefail

# Auto-load env (local .env or systemd-style /etc/default/vinyl)
if [ -f "/etc/default/vinyl" ]; then
  set -a; source /etc/default/vinyl; set +a
elif [ -f ".env" ]; then
  set -a; source ./.env; set +a
fi

DARKICE_CFG="${DARKICE_CFG:-/etc/darkice.cfg}"
ICECAST_SERVICE="${ICECAST_SERVICE:-icecast2}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")" && pwd)}"
APP_MAIN="${APP_MAIN:-$APP_DIR/main.py}"

echo "[INFO] App dir: $APP_DIR"
echo "[INFO] Using darkice cfg: $DARKICE_CFG"

# 1) Detect capture card (first CAPTURE device)
CARD_LINE=$(arecord -l | awk '/CAPTURE/{p=1} p && /card [0-9]+:/ {print; exit}')
if [[ -z "${CARD_LINE:-}" ]]; then
  echo "[ERROR] No capture devices found (arecord -l)"; exit 1
fi
CARD_IDX=$(echo "$CARD_LINE" | sed -n 's/.*card \([0-9]\+\).*/\1/p')
ALSA_DEV="plughw:${CARD_IDX},0"
echo "[INFO] Using ALSA device: $ALSA_DEV"

# 2) Patch darkice.cfg (device + required keys)
sudo sed -i "s|^device *=.*|device = ${ALSA_DEV}|g" "$DARKICE_CFG"
sudo sed -i 's/^bitrateMode *= *.*/bitrateMode = cbr/' "$DARKICE_CFG"
grep -q '^username' "$DARKICE_CFG" || echo 'username = source' | sudo tee -a "$DARKICE_CFG" >/dev/null

# 3) Start Icecast (if installed)
if systemctl list-unit-files | grep -q "^${ICECAST_SERVICE}.service"; then
  sudo systemctl start "$ICECAST_SERVICE"
fi

# 4) Start DarkIce (kill existing)
sudo pkill -f '^darkice' || true
sudo darkice -c "$DARKICE_CFG" &

# 5) Start Python app
cd "$APP_DIR"
exec "$PYTHON_BIN" "$APP_MAIN"
