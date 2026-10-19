#!/usr/bin/env bash
# Installs the systemd timer that regenerates the status page. Run as root.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for unit in ops-eye-page.service ops-eye-page.timer; do
  sed "s#__OPS_EYE_ROOT__#$ROOT#g" "$ROOT/host/systemd/$unit" > "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now ops-eye-page.timer
systemctl start ops-eye-page.service
systemctl list-timers ops-eye-page.timer --no-pager
