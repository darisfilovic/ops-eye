#!/usr/bin/env bash
# Installs the weekly cleanup timer. Run as root.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for unit in ops-eye-maintenance.service ops-eye-maintenance.timer; do
  sed "s#__OPS_EYE_ROOT__#$ROOT#g" "$ROOT/host/systemd/$unit" > "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now ops-eye-maintenance.timer
systemctl list-timers ops-eye-maintenance.timer --no-pager
