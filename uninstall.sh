#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="rtl433-tpms.service"
UNIT_DST="/etc/systemd/system/rtl433-tpms.service"
LOGROTATE_DST="/etc/logrotate.d/rtl433-tpms"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run as root (use sudo)." >&2
  exit 1
fi

systemctl disable --now "$SERVICE_NAME" || true
rm -f "$UNIT_DST" "$LOGROTATE_DST"
systemctl daemon-reload

echo "Removed:"
echo "  $UNIT_DST"
echo "  $LOGROTATE_DST"
