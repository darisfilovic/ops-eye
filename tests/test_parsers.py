"""Parsers against samples of real tool output. Addresses are documentation ranges."""

from datetime import datetime, timezone

from opseye import parsers

PROXY_OK = (
    '[19/Oct/2026:15:00:08 +0000] - 200 200 - GET https erp.example.com "/web/health" '
    '[Client 203.0.113.7] [Length 30] [Gzip -] [Sent-to web] "curl/8.5.0" "-"'
)
# nginx answered by itself (444 rule for scanners): the upstream status is "-".
PROXY_444 = (
    '[19/Oct/2026:15:00:09 +0000] - - 444 - GET https erp.example.com "/.env" '
    '[Client 198.51.100.23] [Length 0] [Gzip -] [Sent-to web] "Mozilla/5.0" "-"'
)
FALLBACK = (
    '[19/Oct/2026:17:00:10 +0200] 200 - GET http 192.0.2.10 "/" '
    '[Client 198.51.100.9] [Length 612] [Gzip -] "zgrab/0.x" "-"'
)
FALLBACK_BAD_REQUEST = (
    '[19/Oct/2026:15:00:11 +0000] 400 - - http localhost "-" '
    '[Client 198.51.100.9] [Length 154] [Gzip -] "-" "-"'
)


def test_npm_proxy_line():
    when, status, uri, client = parsers.parse_npm_line(PROXY_OK)
    assert when == datetime(2026, 10, 19, 15, 0, 8, tzinfo=timezone.utc)
    assert (status, uri, client) == ("200", "/web/health", "203.0.113.7")


def test_npm_line_answered_by_nginx():
    _, status, uri, client = parsers.parse_npm_line(PROXY_444)
    assert (status, uri, client) == ("444", "/.env", "198.51.100.23")


def test_npm_fallback_lines_keep_their_time_zone():
    when, status, _, client = parsers.parse_npm_line(FALLBACK)
    assert when == datetime(2026, 10, 19, 15, 0, 10, tzinfo=timezone.utc)
    assert (status, client) == ("200", "198.51.100.9")
    assert parsers.parse_npm_line(FALLBACK_BAD_REQUEST)[1] == "400"


def test_npm_line_that_is_not_a_log_line():
    assert parsers.parse_npm_line("nginx: [warn] conflicting server name") is None
    assert parsers.parse_npm_line("") is None


def test_scanner_paths():
    for uri in ("/.env", "/wp-login.php", "/index.php?x=1", "/.git/config", "/vendor/phpunit/x"):
        assert parsers.is_scanner_path(uri), uri
    for uri in ("/web/login", "/web/assets/1/web.assets_web.min.js", "/odoo/action-123", "/environment"):
        assert not parsers.is_scanner_path(uri), uri


def test_meminfo():
    text = "MemTotal:        8000000 kB\nMemAvailable:    2000000 kB\nHugePages_Total:       0\n"
    mem = parsers.parse_meminfo(text)
    assert mem["MemTotal"] == 8000000 * 1024
    assert mem["MemAvailable"] == 2000000 * 1024


def test_journal_usage():
    text = "Archived and active journals take up 1.2G in the file system."
    assert parsers.parse_journal_usage(text) == "1.2G"
    assert parsers.parse_journal_usage("") is None


def test_apt_upgrades():
    text = (
        "Reading package lists...\n"
        "Inst libssl3t64 [3.0.13-0ubuntu3.5] (3.0.13-0ubuntu3.6 Ubuntu:24.04/noble-updates [amd64])\n"
        "Inst openssl [3.0.13-0ubuntu3.5] (3.0.13-0ubuntu3.6 Ubuntu:24.04/noble-updates [amd64])\n"
        "Conf libssl3t64 (3.0.13-0ubuntu3.6 Ubuntu:24.04/noble-updates [amd64])\n"
    )
    assert parsers.count_apt_upgrades(text) == 2
    assert parsers.count_apt_upgrades(None) == 0


def test_fail2ban_jail_list_and_status():
    status = "Status\n|- Number of jail:\t2\n`- Jail list:\tnpm-scanner, sshd\n"
    assert parsers.parse_jail_list(status) == ["npm-scanner", "sshd"]
    assert parsers.parse_jail_list(None) is None

    jail = (
        "Status for the jail: sshd\n"
        "|- Filter\n"
        "|  |- Currently failed:\t3\n"
        "|  |- Total failed:\t241\n"
        "|  `- Journal matches:\t_SYSTEMD_UNIT=sshd.service + _COMM=sshd\n"
        "`- Actions\n"
        "   |- Currently banned:\t2\n"
        "   |- Total banned:\t57\n"
        "   `- Banned IP list:\t203.0.113.50 198.51.100.77\n"
    )
    assert parsers.parse_jail_status(jail) == {"banned_now": "2", "banned_total": "57", "failed_now": "3"}
    assert parsers.parse_jail_status("")["banned_now"] == "?"


def test_ssh_logins():
    text = (
        "Accepted publickey for root from 203.0.113.5 port 50122 ssh2: ED25519 SHA256:abc\n"
        "Failed password for invalid user admin from 198.51.100.4 port 4242 ssh2\n"
        "Invalid user oracle from 198.51.100.4 port 4243\n"
        "Accepted password for deploy from 203.0.113.6 port 50200 ssh2\n"
    )
    assert parsers.count_ssh_logins(text) == {"key": 1, "password": 1, "failed": 2}


SS_OUTPUT = """\
udp   UNCONN 0      0         127.0.0.54:53        0.0.0.0:*    users:(("systemd-resolve",pid=600,fd=16))
udp   UNCONN 0      0      127.0.0.53%lo:53        0.0.0.0:*    users:(("systemd-resolve",pid=600,fd=14))
tcp   LISTEN 0      4096         0.0.0.0:443       0.0.0.0:*    users:(("docker-proxy",pid=1300,fd=7))
tcp   LISTEN 0      4096            [::]:443          [::]:*    users:(("docker-proxy",pid=1310,fd=7))
tcp   LISTEN 0      4096       127.0.0.1:8092      0.0.0.0:*    users:(("docker-proxy",pid=1400,fd=7))
tcp   LISTEN 0      4096         0.0.0.0:5432      0.0.0.0:*    users:(("docker-proxy",pid=1500,fd=7))
tcp   LISTEN 0      128            [::1]:631          [::]:*    users:(("cupsd",pid=900,fd=7))
"""


def test_listening_sockets():
    assert parsers.parse_listening_sockets(SS_OUTPUT) == [
        ("53/udp", False, "systemd-resolve"),
        ("443/tcp", True, "docker-proxy"),
        ("8092/tcp", False, "docker-proxy"),
        ("5432/tcp", True, "docker-proxy"),
        ("631/tcp", False, "cupsd"),
    ]


def test_loopback_addresses():
    for address in ("127.0.0.1", "127.0.0.53%lo", "127.0.0.54", "[::1]"):
        assert parsers.is_loopback(address), address
    for address in ("0.0.0.0", "[::]", "*", "203.0.113.5"):
        assert not parsers.is_loopback(address), address


def test_whois_expiry():
    assert parsers.parse_whois_expiry("   Registry Expiry Date: 2027-10-15T08:21:33Z\n") == "2027-10-15"
    assert parsers.parse_whois_expiry("paid-till:     2027-03-01T21:00:00Z\n") == "2027-03-01"
    assert parsers.parse_whois_expiry("No match for domain") is None


def test_cron_row():
    assert parsers.parse_cron_row("0 45 163381234 4\n") == {
        "backlog": 0,
        "total": 45,
        "size": 163381234,
        "connections": 4,
    }
    assert parsers.parse_cron_row("") is None
    assert parsers.parse_cron_row(None) is None
    assert parsers.parse_cron_row("psql: error: connection refused") is None


def test_odoo_errors_in_the_last_day():
    log = (
        "2026-10-18 09:00:00,003 42 ERROR demo odoo.http: older than the window\n"
        "2026-10-19 10:00:00,001 42 INFO demo odoo.modules.loading: loading 1 modules\n"
        '2026-10-19 11:00:00,002 42 ERROR demo odoo.sql_db: bad query: column "x" does not exist\n'
        "2026-10-19 12:00:00,004 42 ERROR prod odoo.addons.mail: Mail delivery failed\n"
    )
    assert parsers.count_odoo_errors(log, "2026-10-18 12:00:00") == (2, 1)


def test_json_lines_skip_broken_lines():
    text = '{"Name": "web", "CPUPerc": "1.0%"}\nnot json\n{"Name": "db"}\n'
    assert [item["Name"] for item in parsers.parse_json_lines(text)] == ["web", "db"]
