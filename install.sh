#!/usr/bin/env bash
set -euo pipefail

# Repo files
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SRC="$REPO_DIR/rtl433-tpms.service"
LOGROTATE_SRC="$REPO_DIR/rtl433-tpms.logrotate"
PROM_EXPORTER_SRC="$REPO_DIR/rtl433-prom-exporter.py"

# System destinations
UNIT_DST="/etc/systemd/system/rtl433-tpms.service"
LOGROTATE_DST="/etc/logrotate.d/rtl433-tpms"
PROM_EXPORTER_DST="/opt/rtl433-prom-exporter.py"

SERVICE_NAME="rtl433-tpms.service"
LOG_DIR="/var/log/rtl_433/tpms"

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: run as root (use sudo)." >&2
    exit 1
  fi
}

require_file() {
  local p="$1"
  if [[ ! -f "$p" ]]; then
    echo "ERROR: missing required file: $p" >&2
    exit 1
  fi
}

install_if_changed() {
  local src="$1"
  local dst="$2"
  local mode="${3:-0644}"

  if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
    echo "OK: unchanged: $dst"
    return 0
  fi

  install -m "$mode" -o root -g root "$src" "$dst"
  echo "INSTALLED: $dst"
}

ensure_logrotate_no_overwrite() {
  # Ensure dateformat has time to prevent collisions on manual -f runs.
  # This edits the repo file *in place* only if needed (so git shows the change).
  local f="$LOGROTATE_SRC"

  if grep -qE '^\s*dateext\b' "$f"; then
    if grep -qE '^\s*dateformat\s+-.*%H%M%S' "$f"; then
      echo "OK: logrotate dateformat includes %H%M%S (no overwrite on manual runs)"
      return 0
    fi

    if grep -qE '^\s*dateformat\s+' "$f"; then
      echo "FIX: updating existing dateformat to include _%H%M%S in $f"
      # Replace any existing dateformat with a safe one
      sed -i -E 's|^\s*dateformat\s+.*$|  dateformat -%Y-%m-%d_%H%M%S|' "$f"
    else
      echo "FIX: adding dateformat with _%H%M%S to $f"
      # Add dateformat right after dateext
      sed -i -E '/^\s*dateext\b/a\  dateformat -%Y-%m-%d_%H%M%S' "$f"
    fi
  else
    # If dateext isn't used, we can't guarantee uniqueness via dateformat.
    echo "WARNING: $f has no 'dateext'. Add dateext+dateformat to prevent overwrites on manual runs." >&2
  fi
}

main() {
  require_root
  require_file "$UNIT_SRC"
  require_file "$LOGROTATE_SRC"

  # Optional: enforce the "no overwrite if logrotate -f is run manually" requirement
  ensure_logrotate_no_overwrite

  echo "==> Installing systemd unit"
  install_if_changed "$UNIT_SRC" "$UNIT_DST" 0644

  echo "==> Installing prometheus exporter"
  install_if_changed "$PROM_EXPORTER_SRC" "$PROM_EXPORTER_DST" 0644

  echo "==> Installing logrotate config"
  install_if_changed "$LOGROTATE_SRC" "$LOGROTATE_DST" 0644

  echo "==> Ensuring log directory exists: $LOG_DIR"
  mkdir -p "$LOG_DIR"
  # If your service runs as user pi, this is correct; adjust if you changed User=
  chown -R pi:pi "$LOG_DIR" || true
  chmod 0755 "$LOG_DIR"

  echo "==> Reloading systemd"
  systemctl daemon-reload

  echo "==> Enabling + restarting service"
  systemctl enable "$SERVICE_NAME" >/dev/null
  systemctl restart "$SERVICE_NAME"

  echo "==> Service status"
  systemctl --no-pager --full status "$SERVICE_NAME" || true

  echo
  echo "Installed:"
  echo "  Unit:      $UNIT_DST"
  echo "  Logrotate: $LOGROTATE_DST"
  echo
  echo "Manual rotation test (should create unique timestamped files):"
  echo "  sudo logrotate -f $LOGROTATE_DST"
}

main "$@"
