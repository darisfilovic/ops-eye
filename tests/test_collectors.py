"""Collectors with the system commands replaced by recorded output."""

from datetime import datetime, timedelta, timezone

import pytest

from opseye import collectors
from opseye.i18n import strings_for
from opseye.report import Report

from .test_parsers import SS_OUTPUT


class NoCache:
    def get(self, key, ttl_seconds, compute):
        return compute()


def report():
    return Report(strings_for("en"), host="test")


def fake_run(outputs):
    """A replacement for util.run that answers by the first words of the command."""

    def run(cmd, timeout=20):
        for prefix, output in outputs.items():
            if tuple(cmd[: len(prefix)]) == prefix:
                return output
        return None

    return run


def test_security_flags_public_ports_and_password_logins(monkeypatch):
    monkeypatch.setattr(
        collectors,
        "run",
        fake_run(
            {
                ("fail2ban-client", "status", "sshd"): "Currently failed:\t0\nCurrently banned:\t1\n"
                "Total banned:\t9\n",
                ("fail2ban-client", "status"): "`- Jail list:\tsshd\n",
                ("journalctl",): "Accepted password for root from 203.0.113.5 port 1 ssh2\n",
                ("ss",): SS_OUTPUT,
                ("whois",): "Registry Expiry Date: 2099-01-01T00:00:00Z\n",
            }
        ),
    )
    r = report()
    collectors.collect_security(r, {"REGISTERED_DOMAINS": "example.com"}, NoCache())
    flagged = [text for _, text, _ in r.attention]
    assert "Listening ports: 5432/tcp public (docker-proxy)" in flagged
    assert any("password logins" in text for text in flagged)
    assert not any("443/tcp" in text for text in flagged)
    jails = r.sections[0]["tables"][0]["rows"]
    assert jails == [["sshd", "1", "9", "0", "ok"]]


def test_odoo_cron_backlog_and_unreachable_database(monkeypatch):
    def run(cmd, timeout=20):
        return {"prod": "0 47 1048576 3\n", "staging": "12 45 2048 1\n"}.get(cmd[cmd.index("-d") + 1])

    monkeypatch.setattr(collectors, "run", run)
    monkeypatch.setattr(collectors, "http_check", lambda url: (200, 120))
    monkeypatch.setattr(collectors, "cert_days", lambda host: 5)
    env = {
        "ODOO_DB_CONTAINER": "db",
        "ODOO_DATABASES": "prod, staging, gone",
        "DOMAINS": "erp.example.com",
    }
    r = report()
    collectors.collect_odoo(r, env, NoCache())

    rows = r.sections[0]["tables"][0]["rows"]
    assert [row[0] for row in rows] == ["prod", "staging", "gone"]
    assert [row[-1] for row in rows] == ["ok", "crit", "crit"]
    attention = {text: (sev, advice) for sev, text, advice in r.attention}
    assert attention["Database staging: Overdue cron jobs 12"][0] == "crit"
    assert "db_name" in attention["Database staging: Overdue cron jobs 12"][1]
    assert attention["Database gone: collection failed"][0] == "crit"
    assert attention["erp.example.com: Certificate expires in 5 days"][0] == "crit"


@pytest.mark.parametrize(("days", "expected"), [(None, "warn"), (30, "ok"), (14, "warn"), (7, "crit")])
def test_certificate_levels(monkeypatch, days, expected):
    monkeypatch.setattr(collectors, "run", lambda cmd, timeout=20: None)
    monkeypatch.setattr(collectors, "http_check", lambda url: (200, 100))
    monkeypatch.setattr(collectors, "cert_days", lambda host: days)
    r = report()
    collectors.collect_odoo(r, {"DOMAINS": "erp.example.com"}, NoCache())
    assert r.sections[0]["tables"][0]["rows"][0][-1] == expected


def npm_time(delta):
    return (datetime.now(timezone.utc) - delta).strftime("%d/%b/%Y:%H:%M:%S +0000")


def test_traffic_counts_only_the_last_day(tmp_path):
    recent, old = npm_time(timedelta(hours=1)), npm_time(timedelta(days=2))
    (tmp_path / "proxy-host-1_access.log").write_text(
        f'[{recent}] - 200 200 - GET https erp.example.com "/web" [Client 203.0.113.1] [Length 1]\n'
        f'[{recent}] - - 444 - GET https erp.example.com "/.env" [Client 203.0.113.2] [Length 0]\n'
        f'[{recent}] - 502 502 - GET https erp.example.com "/web" [Client 127.0.0.1] [Length 0]\n'
        f'[{old}] - 200 200 - GET https erp.example.com "/web" [Client 203.0.113.1] [Length 1]\n'
    )
    (tmp_path / "fallback_http_access.log").write_text(
        f'[{recent}] 200 - GET http 192.0.2.10 "/" [Client 203.0.113.3] [Length 612]\n'
    )
    r = report()
    collectors.collect_traffic(r, {"NPM_LOGS_DIR": str(tmp_path), "EXCLUDE_IPS": "127.0.0.1"}, NoCache())
    kv = {label: value for label, value, _ in r.sections[0]["kv"]}
    assert kv["Requests"] == "4"
    assert kv["By status"] == "2xx 2, 4xx 1, 5xx 1"
    assert kv["Scanner hits (.php, .env, wp-, xmlrpc.php)"] == "1"
    assert kv["Hits on the bare IP address"] == "1"
    clients = [row[0] for row in r.sections[0]["tables"][0]["rows"]]
    assert "127.0.0.1" not in clients


def test_traffic_without_log_directory_is_an_error(tmp_path):
    r = report()
    collectors.collect_traffic(r, {"NPM_LOGS_DIR": str(tmp_path / "missing")}, NoCache())
    assert r.errors and r.errors[0].startswith("NPM_LOGS_DIR")


def test_http_check_accepts_only_https():
    with pytest.raises(ValueError):
        collectors.http_check("file:///etc/passwd")
