"""Parsers for the text that system tools print.

Pure functions without side effects, so each one is tested against a
sample of real output (tests/test_parsers.py).
"""

import json
import re
from datetime import datetime

# Nginx Proxy Manager access logs.
# Proxy hosts: [time] cache upstream status - method scheme host "uri" [Client ip] ...
#   upstream is "-" when nginx answers by itself (redirect, 444 for scanners).
# Fallback site: [time] status - method scheme host "uri" [Client ip] ...
NPM_LINE = re.compile(
    r"^\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\] "
    r'(?:\S+ (?:\d{3}|-) )?(\d{3}) - (\S+) (\S+) (\S+) "([^"]*)" \[Client ([^\]]+)\]'
)
SCANNER_PATH = re.compile(
    r"\.(php|env|asp|aspx|cgi)(\?|$)|/wp-|xmlrpc\.php|phpmyadmin|/\.git|/\.aws|/vendor/", re.I
)


def parse_npm_line(line):
    """(time, status, uri, client) of an NPM access log line, or None."""
    m = NPM_LINE.match(line)
    if not m:
        return None
    try:
        when = datetime.strptime(m.group(1), "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None
    return when, m.group(2), m.group(6), m.group(7)


def is_scanner_path(uri):
    """True for paths that only vulnerability scanners ask for on an Odoo host."""
    return bool(SCANNER_PATH.search(uri))


def parse_meminfo(text):
    """/proc/meminfo as a dict of bytes."""
    mem = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        parts = value.split()
        if parts and parts[0].isdigit():
            mem[key] = int(parts[0]) * 1024
    return mem


def parse_journal_usage(text):
    """Size from `journalctl --disk-usage`, as printed ("1.2G"), or None."""
    m = re.search(r"take up ([0-9.]+[KMGT]?)", text or "")
    return m.group(1) if m else None


def count_apt_upgrades(text):
    """Number of packages a simulated `apt-get upgrade` would install."""
    return sum(1 for line in (text or "").splitlines() if line.startswith("Inst "))


def parse_jail_list(text):
    """Jail names from `fail2ban-client status`, or None when the output is not there."""
    m = re.search(r"Jail list:\s*(.*)", text or "")
    if not m:
        return None
    return [name.strip() for name in m.group(1).split(",") if name.strip()]


def parse_jail_status(text):
    """Counters from `fail2ban-client status <jail>`; "?" where a counter is missing."""

    def counter(label):
        m = re.search(label + r":\s*(\d+)", text or "")
        return m.group(1) if m else "?"

    return {
        "banned_now": counter("Currently banned"),
        "banned_total": counter("Total banned"),
        "failed_now": counter("Currently failed"),
    }


def count_ssh_logins(text):
    """Key logins, password logins and failed attempts in sshd journal lines."""
    text = text or ""
    return {
        "key": text.count("Accepted publickey"),
        "password": text.count("Accepted password"),
        "failed": text.count("Failed password") + text.count("Invalid user"),
    }


def is_loopback(address):
    """True for 127.0.0.0/8 and ::1, with or without an interface suffix (127.0.0.53%lo)."""
    host = address.split("%", 1)[0].strip("[]")
    return host.startswith("127.") or host == "::1"


def parse_listening_sockets(text):
    """(port/proto, public, process) for each listening socket in `ss -H -ltnup`.

    A port that listens on several addresses of the same kind is listed once.
    """
    seen = set()
    sockets = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        proto, local = parts[0], parts[4]
        address, _, port = local.rpartition(":")
        m = re.search(r'users:\(\("([^"]+)"', line)
        process = m.group(1) if m else ""
        public = not is_loopback(address)
        if (proto, port, public) in seen:
            continue
        seen.add((proto, port, public))
        sockets.append((f"{port}/{proto}", public, process))
    return sockets


def parse_whois_expiry(text):
    """Expiry date (YYYY-MM-DD) from whois output, or None."""
    label = r"(?i)(registry expiry date|expiry date|expiration date|paid-till|expires on)"
    m = re.search(label + r"[:\s]+(\d{4}-\d{2}-\d{2})", text or "")
    return m.group(2) if m else None


def parse_cron_row(text):
    """The answer of the cron backlog query: overdue, total, database bytes, connections."""
    fields = (text or "").split()
    if len(fields) != 4 or not all(f.isdigit() for f in fields):
        return None
    backlog, total, size, connections = (int(f) for f in fields)
    return {"backlog": backlog, "total": total, "size": size, "connections": connections}


def count_odoo_errors(text, since):
    """ERROR lines in an Odoo log newer than since ("YYYY-MM-DD HH:MM:SS", UTC).

    Returns (errors, missing_column). "does not exist" in an error usually
    means a database that still runs on an older version of a module.
    """
    errors = [line for line in (text or "").splitlines() if " ERROR " in line and line[:19] >= since]
    missing = sum(1 for line in errors if "does not exist" in line)
    return len(errors), missing


def parse_json_lines(text):
    """One JSON object per line, as printed by `docker ... --format '{{json .}}'`."""
    items = []
    for line in (text or "").splitlines():
        try:
            items.append(json.loads(line))
        except ValueError:
            continue
    return items
