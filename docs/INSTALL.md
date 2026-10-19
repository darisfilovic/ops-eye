# Installing ops-eye on a new server

Installing and running ops-eye requires written permission from the author
(see [LICENSE](../LICENSE)).

Tested on Ubuntu 24.04 with Docker Compose v2. Needs on the host: `docker`,
`python3` (3.10 or newer, standard library only), `fail2ban`, `whois`,
`openssl`, `ss` (iproute2). Nginx Proxy Manager must write its logs to a
host directory (the `data/logs` bind mount of its compose file).

1. Clone and configure

   ```
   git clone https://github.com/darisfilovic/ops-eye.git /root/ops-eye
   cd /root/ops-eye
   cp .env.example .env
   ```

   Edit `.env`: `NPM_LOGS_DIR`, `EXCLUDE_IPS` (your own address), the Odoo
   container names, `ODOO_DATABASES` (the same list as `db_name` in
   odoo.conf), `ODOO_LOG`, `DOMAINS`, `REGISTERED_DOMAINS`, `OPS_LANG`.

2. Start the containers and the accounts

   ```
   bin/ops-eye up
   bin/ops-eye setup           # Portainer admin, Beszel user and host registration
   bin/ops-eye install-timer   # status page every 5 minutes
   bin/ops-eye check           # the report in the terminal
   ```

   The password for Portainer (`admin`) and Beszel (`admin@ops-eye.local`)
   is `OPS_ADMIN_PASSWORD` in `.env`.

3. Host configuration

   ```
   host/install-host-configs.sh            # dry run
   host/install-host-configs.sh --apply    # journald limit, log rotation, sysctl, fail2ban scanner jail, Docker log limits
   host/install-maintenance-timer.sh       # weekly cleanup, Sunday 03:00
   host/cockpit/install.sh                 # Cockpit on 127.0.0.1:9090
   ```

   The weekly cleanup only lists filestore directories of dropped Odoo
   databases; with `CLEAN_ORPHAN_FILESTORE=yes` in `.env` it removes them.

   Docker log limits apply to containers created after
   `systemctl restart docker`; do that in a quiet moment.

4. Nginx Proxy Manager: follow `nginx/README.md` (include files, Advanced
   block per Odoo host, Force SSL and HTTP/2 on every host).

5. Optional GeoIP: MaxMind keys in `.env`, then `bin/ops-eye geoip`.

6. SSH last, by hand, only after a key login is confirmed in the journal:
   `host/sshd/ops-eye.conf`.

## Reaching the tools

Everything listens on `127.0.0.1`. From your computer:

```
ssh -L 8092:127.0.0.1:8092 -L 7880:127.0.0.1:7880 -L 8090:127.0.0.1:8090 \
    -L 8091:127.0.0.1:8091 -L 9000:127.0.0.1:9000 -L 9090:127.0.0.1:9090 root@server
```

Then open `http://127.0.0.1:8092/` (status page), 7880 (GoAccess; add
`/redirection/` for hits on the bare IP), 8090 (Beszel), 8091 (fail2ban),
9000 (Portainer), 9090 (Cockpit). VS Code Remote SSH forwards the same ports
from its Ports tab.

## Updating

```
cd /root/ops-eye && git pull
bin/ops-eye up            # pulls nothing by itself; run docker compose pull first for new images
```

## Removing

```
bin/ops-eye down
systemctl disable --now ops-eye-page.timer ops-eye-maintenance.timer
rm /etc/systemd/system/ops-eye-*.{service,timer}
```

The `data/` directory keeps the Beszel history and Portainer settings; remove
it only if you do not want them back.
