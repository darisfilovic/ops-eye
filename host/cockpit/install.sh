#!/usr/bin/env bash
# Cockpit bound to 127.0.0.1:9090 only (reach it through an SSH tunnel).
# Gives updates, reboot, services, journal, storage and a terminal in the browser.
set -euo pipefail
apt-get install -y cockpit
mkdir -p /etc/systemd/system/cockpit.socket.d /etc/cockpit
cat > /etc/systemd/system/cockpit.socket.d/listen.conf <<'UNIT'
[Socket]
ListenStream=
ListenStream=127.0.0.1:9090
UNIT
cat > /etc/cockpit/cockpit.conf <<'CONF'
[WebService]
# Plain HTTP is acceptable only because the socket is bound to localhost.
AllowUnencrypted=true
Origins=http://localhost:9090 http://127.0.0.1:9090
CONF
systemctl daemon-reload
systemctl enable --now cockpit.socket
systemctl restart cockpit.socket
ss -ltn | grep 9090
