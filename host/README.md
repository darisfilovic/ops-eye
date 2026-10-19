# Host configuration

Files that belong outside Docker, kept here so a new server gets the same
setup. Nothing is applied automatically:

| File | Destination | Applied by |
|---|---|---|
| journald/ops-eye.conf | /etc/systemd/journald.conf.d/ | install-host-configs.sh |
| logrotate/ops-eye-app | /etc/logrotate.d/ | install-host-configs.sh (uses the directory of ODOO_LOG) |
| docker/daemon.json | /etc/docker/daemon.json | install-host-configs.sh, only when the file does not exist |
| sysctl/99-ops-eye.conf | /etc/sysctl.d/ | install-host-configs.sh |
| fail2ban/filter.d, jail.d, action.d | /etc/fail2ban/ | install-host-configs.sh (uses NPM_LOGS_DIR); jails npm-scanner (proxy hosts) and npm-default-scanner (bare IP, combined log) |
| sshd/ops-eye.conf | /etc/ssh/sshd_config.d/ | by hand, after a key login is confirmed |
| cockpit/install.sh | Cockpit on 127.0.0.1:9090 | run it |
| maintenance.sh + systemd units | weekly cleanup | install-maintenance-timer.sh |
| systemd/ops-eye-page.* | status page refresh | install-timer.sh |

`install-host-configs.sh` is a dry run until `--apply` is given.
