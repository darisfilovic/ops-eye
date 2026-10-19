#!/usr/bin/env bash
# Applies the host configuration files in this directory. Dry run by default:
#   host/install-host-configs.sh            # shows what would change
#   host/install-host-configs.sh --apply    # applies it
# Reads NPM_LOGS_DIR and ODOO_LOG from .env for the paths. Never touches sshd.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
# shellcheck disable=SC1091
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" && set +a
NPM_LOGS_DIR="${NPM_LOGS_DIR:-/srv/npm/data/logs}"
APP_LOG_DIR="$(dirname "${ODOO_LOG:-/var/log/app/app.log}")"

put() {  # put <source> <destination> [substitutions...]
  local src="$1" dst="$2"; shift 2
  local tmp; tmp="$(mktemp)"
  sed "s#__NPM_LOGS_DIR__#$NPM_LOGS_DIR#g; s#__APP_LOG_DIR__#$APP_LOG_DIR#g" "$src" > "$tmp"
  if [ -f "$dst" ] && cmp -s "$tmp" "$dst"; then echo "unchanged  $dst"; rm -f "$tmp"; return; fi
  echo "write      $dst"
  if [ "$APPLY" = 1 ]; then install -D -m 0644 "$tmp" "$dst"; fi
  rm -f "$tmp"
}

put host/journald/ops-eye.conf        /etc/systemd/journald.conf.d/ops-eye.conf
put host/logrotate/ops-eye-app        /etc/logrotate.d/ops-eye-app
put host/sysctl/99-ops-eye.conf       /etc/sysctl.d/99-ops-eye.conf
put host/fail2ban/filter.d/npm-scanner.conf   /etc/fail2ban/filter.d/npm-scanner.conf
put host/fail2ban/filter.d/npm-default-scanner.conf /etc/fail2ban/filter.d/npm-default-scanner.conf
put host/fail2ban/jail.d/ops-eye-scanner.conf /etc/fail2ban/jail.d/ops-eye-scanner.conf
[ -f host/fail2ban/action.d/iptables-docker.conf ] && put host/fail2ban/action.d/iptables-docker.conf /etc/fail2ban/action.d/iptables-docker.conf

if [ -f /etc/docker/daemon.json ]; then
  echo "exists     /etc/docker/daemon.json (merge log-opts by hand from host/docker/daemon.json)"
else
  put host/docker/daemon.json /etc/docker/daemon.json
  echo "note       Docker log options apply to containers created after 'systemctl restart docker'"
fi

if [ "$APPLY" = 1 ]; then
  systemctl restart systemd-journald
  journalctl --vacuum-size=300M >/dev/null
  sysctl -q -p /etc/sysctl.d/99-ops-eye.conf
  fail2ban-client -t >/dev/null && fail2ban-client reload >/dev/null && echo "fail2ban reloaded"
  logrotate -d /etc/logrotate.d/ops-eye-app 2>&1 | grep -iE 'error' || echo "logrotate config ok"
else
  echo; echo "dry run; add --apply to write the files"
fi
