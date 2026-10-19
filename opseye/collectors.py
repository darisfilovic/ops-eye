"""Collectors: each one reads one part of the host and writes a section of the report.

Every collector takes (report, env, cache). One that raises does not hide
the others: cli.collect catches the exception and lists it under the page.
"""

import http.client
import os
import shutil
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import parsers
from .report import SEV_ORDER, level_above, level_below, worst
from .util import env_list, human_bytes, parse_size, run, tail_text

# Ports that may listen on a public address without a warning.
PUBLIC_PORTS_ALLOWED = {"22/tcp", "80/tcp", "443/tcp", "68/udp", "546/udp"}
DAY = 24 * 3600


def collect_server(r, env, cache):
    t = r.t
    sec = r.section("server")

    load = Path("/proc/loadavg").read_text().split()[:3]
    cpus = os.cpu_count() or 1
    sec["kv"].append((t["load"], " / ".join(load), "ok"))
    sec["kv"].append((t["cpus"], str(cpus), "ok"))
    if float(load[0]) > cpus:
        r.flag("warn", f"{t['load']}: {load[0]} > {cpus}", "adv_mem")

    mem = parsers.parse_meminfo(Path("/proc/meminfo").read_text())
    total, avail = mem["MemTotal"], mem["MemAvailable"]
    used_pct = 100 * (total - avail) / total
    sev = level_below(avail / total, warn=0.15, crit=0.08)
    used = f"{human_bytes(total - avail)} {t['used']} / {human_bytes(total)} ({used_pct:.0f} %)"
    sec["kv"].append((t["memory"], used, sev))
    r.flag(sev, f"{t['memory']}: {used_pct:.0f} % {t['used']}", "adv_mem")

    swap_total, swap_free = mem.get("SwapTotal", 0), mem.get("SwapFree", 0)
    if swap_total:
        swap = f"{human_bytes(swap_total - swap_free)} {t['used']} / {human_bytes(swap_total)}"
        sec["kv"].append((t["swap"], swap, "ok"))

    du = shutil.disk_usage("/")
    pct = 100 * du.used / du.total
    sev = level_above(pct, warn=80, crit=90)
    disk = (
        f"{human_bytes(du.used)} {t['used']} / {human_bytes(du.total)} ({pct:.0f} %), "
        f"{human_bytes(du.free)} {t['free']}"
    )
    sec["kv"].append((t["disk"], disk, sev))
    r.flag(sev, f"{t['disk']}: {pct:.0f} %", "adv_disk")

    journal = parsers.parse_journal_usage(run(["journalctl", "--disk-usage"]))
    if journal:
        sev = "warn" if parse_size(journal) > 1024**3 else "ok"
        sec["kv"].append((t["journal"], journal, sev))
        r.flag(sev, f"{t['journal']}: {journal}", "adv_journal")

    uptime = float(Path("/proc/uptime").read_text().split()[0])
    since = datetime.now().astimezone() - timedelta(seconds=uptime)
    sec["kv"].append((t["uptime"], f"{since:%d.%m.%Y %H:%M} ({uptime / 86400:.0f} d)", "ok"))

    if Path("/var/run/reboot-required").exists():
        sec["kv"].append((t["reboot"], t["reboot_needed"], "warn"))
        r.flag("warn", t["reboot_needed"], "adv_reboot")
    else:
        sec["kv"].append((t["reboot"], t["reboot_no"], "ok"))

    pending = cache.get(
        "apt_pending",
        3600,
        lambda: parsers.count_apt_upgrades(
            run(["apt-get", "-s", "-o", "Debug::NoLocking=true", "upgrade"], timeout=60)
        ),
    )
    sev = "warn" if pending > 20 else "ok"
    sec["kv"].append((t["updates"], str(pending) if pending else t["updates_none"], sev))
    r.flag(sev, f"{t['updates']}: {pending}", "adv_updates")

    auto = (run(["systemctl", "is-active", "unattended-upgrades"]) or "").strip()
    sec["kv"].append((t["auto_updates"], auto or "?", "ok" if auto == "active" else "warn"))

    stamp = Path("/var/lib/apt/periodic/update-success-stamp")
    if stamp.exists():
        last = datetime.fromtimestamp(stamp.stat().st_mtime)
        sec["kv"].append((t["last_apt"], f"{last:%d.%m.%Y %H:%M}", "ok"))


def collect_containers(r, env, cache):
    t = r.t
    sec = r.section("containers")
    out = run(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=30)
    if out is None:
        r.errors.append("docker ps")
        return
    stats_out = run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout=40)
    stats = {s["Name"]: s for s in parsers.parse_json_lines(stats_out) if "Name" in s}
    rows = []
    for c in parsers.parse_json_lines(out):
        name = c.get("Names", "")
        running = c.get("State") == "running"
        st = stats.get(name, {})
        mem = st.get("MemUsage", "").split("/")[0].strip()
        state = t["running"] if running else t["not_running"]
        sev = "ok" if running else "crit"
        rows.append([name, state, c.get("Status", ""), mem, st.get("CPUPerc", ""), c.get("Image", ""), sev])
        r.flag(sev, f"{t['containers']}: {name} {t['not_running']}", "adv_container")
    rows.sort(key=lambda row: (SEV_ORDER[row[-1]], row[0]))
    sec["tables"].append(
        {
            "head": [t["name"], t["state"], t["status"], t["mem"], t["cpu"], t["image"]],
            "rows": rows,
            "num_cols": [3, 4],
            "state_col": False,
        }
    )


CRON_QUERY = (
    "select count(*) filter (where nextcall < now() - interval '5 minutes')||' '||count(*)||' '||"
    "pg_database_size(current_database())||' '||"
    "(select count(*) from pg_stat_activity where datname=current_database()) from ir_cron where active"
)


def collect_odoo(r, env, cache):
    t = r.t
    sec = r.section("odoo")
    container, user = env.get("ODOO_DB_CONTAINER"), env.get("ODOO_DB_USER", "odoo")

    # Odoo runs scheduled jobs only for databases listed in db_name, and a
    # database missing there shows no error: its jobs simply never start.
    rows = []
    for db in env_list(env, "ODOO_DATABASES"):
        out = None
        if container:
            out = run(["docker", "exec", container, "psql", "-U", user, "-d", db, "-Atc", CRON_QUERY])
        row = parsers.parse_cron_row(out)
        if row is None:
            rows.append([db, "?", "", "", "crit"])
            r.flag("crit", f"{t['database']} {db}: {t['err_collect']}", "adv_cron")
            continue
        sev = "crit" if row["backlog"] else "ok"
        backlog = f"{row['backlog']} {t['cron_total']} {row['total']}"
        rows.append([db, backlog, human_bytes(row["size"]), str(row["connections"]), sev])
        r.flag(sev, f"{t['database']} {db}: {t['cron_backlog']} {row['backlog']}", "adv_cron")
    if rows:
        sec["tables"].append(
            {
                "head": [t["database"], t["cron_backlog"], t["db_size"], t["connections"]],
                "rows": rows,
                "num_cols": [2, 3],
                "state_col": True,
            }
        )

    log = env.get("ODOO_LOG")
    if log and Path(log).exists():
        # Odoo writes its log timestamps in UTC whatever the host time zone is.
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        errors, missing = parsers.count_odoo_errors(tail_text(log), since)
        sev = "warn" if missing or errors > 50 else "ok"
        sec["kv"].append((t["log_errors"], str(errors), sev))
        if missing:
            sec["kv"].append((t["log_missing_col"], str(missing), "warn"))
        r.flag(sev, f"{t['log_errors']}: {errors}", "adv_errors")

    domain_rows = []
    for domain in env_list(env, "DOMAINS"):
        code, ms = http_check(f"https://{domain}/web/health")
        sev_http = "ok" if code == 200 and ms < 5000 else "warn" if code == 200 else "crit"
        days = cache.get(f"cert:{domain}", 12 * 3600, lambda d=domain: cert_days(d))
        sev_cert = "warn" if days is None else level_below(days, warn=15, crit=8)
        http_text = f"{code} ({ms} ms)" if code else "?"
        cert_text = f"{days} {t['days']}" if days is not None else "?"
        domain_rows.append([domain, http_text, cert_text, worst(sev_http, sev_cert)])
        r.flag(sev_http, f"{domain}: {t['http']} {http_text}", "adv_http")
        r.flag(sev_cert, f"{domain}: {t['cert']} {cert_text}", "adv_cert")
    if domain_rows:
        sec["tables"].append(
            {
                "head": [t["domain"], t["http"], t["cert"]],
                "rows": domain_rows,
                "num_cols": [],
                "state_col": True,
            }
        )


def http_check(url):
    """(status code, milliseconds) of a GET request, or (None, None) when it fails."""
    if not url.startswith("https://"):
        raise ValueError(f"not an https URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "ops-eye/1.0"})  # noqa: S310 (https checked above)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as resp:  # noqa: S310
            code = resp.status
    except urllib.error.HTTPError as e:
        code = e.code
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return None, None
    return code, int((time.monotonic() - start) * 1000)


def cert_days(host, port=443, timeout=10):
    """Days until the certificate of host expires, or None when it cannot be read.

    The handshake verifies the chain, so an expired or otherwise invalid
    certificate also comes back as None and shows up on the page as unknown.
    """
    ctx = ssl.create_default_context()
    try:
        with (
            socket.create_connection((host, port), timeout=timeout) as sock,
            ctx.wrap_socket(sock, server_hostname=host) as tls,
        ):
            not_after = tls.getpeercert()["notAfter"]
    except (OSError, ssl.SSLError, KeyError):
        return None
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), timezone.utc)
    return (expires - datetime.now(timezone.utc)).days


def collect_traffic(r, env, cache):
    t = r.t
    sec = r.section("traffic")
    logdir = Path(env.get("NPM_LOGS_DIR", ""))
    if not logdir.is_dir():
        r.errors.append(f"NPM_LOGS_DIR {logdir}")
        return
    exclude = set(env_list(env, "EXCLUDE_IPS"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    total = fallback = scanners = 0
    by_class = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
    clients = {}
    logs = sorted(logdir.glob("proxy-host-*_access.log")) + sorted(logdir.glob("fallback_http_access.log"))
    for path in logs:
        is_fallback = path.name.startswith("fallback")
        for line in tail_text(path).splitlines():
            hit = parsers.parse_npm_line(line)
            if hit is None or hit[0] < cutoff:
                continue
            _, status, uri, client = hit
            total += 1
            by_class[status[0] + "xx"] = by_class.get(status[0] + "xx", 0) + 1
            fallback += is_fallback
            scanners += parsers.is_scanner_path(uri)
            if client not in exclude:
                clients[client] = clients.get(client, 0) + 1

    sec["kv"].append((t["requests"], f"{total:,}".replace(",", "."), "ok"))
    errors_5xx = by_class.get("5xx", 0)
    sev = "warn" if errors_5xx > 50 else "ok"
    classes = ", ".join(f"{k} {v}" for k, v in sorted(by_class.items()) if v)
    sec["kv"].append((t["by_status"], classes, sev))
    r.flag(sev, f"5xx: {errors_5xx}", "adv_5xx")
    sec["kv"].append((t["scanners"], str(scanners), "info" if scanners else "ok"))
    sec["kv"].append((t["fallback"], str(fallback), "info" if fallback else "ok"))

    top = sorted(clients.items(), key=lambda item: -item[1])[:5]
    if top:
        sec["tables"].append(
            {
                "head": [t["top_ips"], t["requests_n"]],
                "rows": [[ip, str(n), "ok"] for ip, n in top],
                "num_cols": [1],
                "state_col": False,
            }
        )


def collect_security(r, env, cache):
    t = r.t
    sec = r.section("security")

    jails = parsers.parse_jail_list(run(["fail2ban-client", "status"]))
    if jails is None:
        r.errors.append("fail2ban-client")
    else:
        rows = []
        for jail in jails:
            s = parsers.parse_jail_status(run(["fail2ban-client", "status", jail]))
            rows.append([jail, s["banned_now"], s["banned_total"], s["failed_now"], "ok"])
        sec["tables"].append(
            {
                "head": [t["jail"], t["banned_now"], t["banned_total"], t["failed_now"]],
                "rows": rows,
                "num_cols": [1, 2, 3],
                "state_col": False,
            }
        )

    ssh = parsers.count_ssh_logins(
        run(["journalctl", "-u", "ssh", "--since", "-24h", "-o", "cat"], timeout=30)
    )
    sev = "warn" if ssh["password"] else "ok"
    logins = (
        f"{ssh['key']} {t['ssh_key']}, {ssh['password']} {t['ssh_pw']}, {ssh['failed']} {t['ssh_failed']}"
    )
    sec["kv"].append((t["ssh"], logins, sev))
    r.flag(sev, f"{t['ssh']}: {ssh['password']} {t['ssh_pw']}", "adv_ssh_pw")

    rows = []
    for port, public, process in parsers.parse_listening_sockets(run(["ss", "-H", "-ltnup"])):
        sev = "warn" if public and port not in PUBLIC_PORTS_ALLOWED else "ok"
        rows.append([port, t["public"] if public else t["local"], process, sev])
        r.flag(sev, f"{t['ports']}: {port} {t['public']} ({process})", "adv_port")

    def port_order(row):
        number = row[0].split("/")[0]
        return SEV_ORDER[row[-1]], int(number) if number.isdigit() else 0

    rows.sort(key=port_order)
    sec["tables"].append(
        {"head": [t["port"], t["bind"], t["process"]], "rows": rows, "num_cols": [], "state_col": True}
    )

    for domain in env_list(env, "REGISTERED_DOMAINS"):
        label = f"{t['domain_expiry']} ({domain})"
        expiry = cache.get(
            f"whois:{domain}",
            12 * 3600,
            lambda d=domain: parsers.parse_whois_expiry(run(["whois", d], timeout=20)),
        )
        if not expiry:
            sec["kv"].append((label, "?", "warn"))
            continue
        days = (datetime.strptime(expiry, "%Y-%m-%d") - datetime.now()).days
        sev = level_below(days, warn=45, crit=14)
        sec["kv"].append((label, f"{days} {t['days']}", sev))
        r.flag(sev, f"{domain}: {t['domain_expiry']} {days} {t['days']}", "adv_domain")


def collect_docker_space(r, env, cache):
    t = r.t
    sec = r.section("docker_space")
    out = run(["docker", "system", "df", "--format", "{{json .}}"], timeout=60)
    if out is None:
        r.errors.append("docker system df")
        return
    items = parsers.parse_json_lines(out)
    reclaimable = sum(parse_size(d.get("Reclaimable", "0")) for d in items)
    too_much = reclaimable > 5 * 1024**3
    rows = []
    for d in items:
        big = too_much and parse_size(d.get("Reclaimable", "0")) > 1024**3
        rows.append([d.get("Type", ""), d.get("Size", ""), d.get("Reclaimable", ""), "warn" if big else "ok"])
    if too_much:
        r.flag("warn", f"{t['docker_space']}: {t['reclaimable']} {human_bytes(reclaimable)}", "adv_disk")
    sec["tables"].append(
        {
            "head": [t["type"], t["size"], t["reclaimable"]],
            "rows": rows,
            "num_cols": [1, 2],
            "state_col": True,
        }
    )


COLLECTORS = [
    collect_server,
    collect_containers,
    collect_odoo,
    collect_traffic,
    collect_security,
    collect_docker_space,
]
