"""The fail2ban filters in host/fail2ban against sample log lines.

fail2ban removes the part of the line that its datepattern matched before
it applies failregex, and replaces <HOST> with its own address pattern.
These tests do the same with a simpler address pattern.
"""

import configparser
import re
from pathlib import Path

FILTERS = Path(__file__).resolve().parent.parent / "host" / "fail2ban" / "filter.d"


def failregex(name):
    conf = configparser.ConfigParser(interpolation=None)
    conf.read(FILTERS / name)
    pattern = conf["Definition"]["failregex"].strip()
    return re.compile(pattern.replace("<HOST>", r"(?P<host>\S+)"))


def without_npm_date(line):
    # datepattern ^\[%d/%b/%Y:%H:%M:%S matches "[19/Oct/2026:15:00:08".
    return line[len("[19/Oct/2026:15:00:08") :]


def test_npm_scanner_matches_scanner_requests():
    rx = failregex("npm-scanner.conf")
    lines = [
        # proxy host, the request reached Odoo and got 404
        '[19/Oct/2026:15:00:08 +0000] - 404 404 - GET https erp.example.com "/wp-login.php" '
        '[Client 203.0.113.7] [Length 0] [Gzip -] [Sent-to web] "Mozilla/5.0" "-"',
        # proxy host, nginx refused it itself with 444 (upstream status "-")
        '[19/Oct/2026:15:00:08 +0000] - - 444 - GET https erp.example.com "/.env" '
        '[Client 203.0.113.8] [Length 0] [Gzip -] [Sent-to web] "Mozilla/5.0" "-"',
        # fallback site (bare IP address)
        '[19/Oct/2026:15:00:08 +0000] 200 - GET http 192.0.2.10 "/.git/config" '
        '[Client 203.0.113.9] [Length 0] [Gzip -] "zgrab/0.x" "-"',
    ]
    hosts = [rx.search(without_npm_date(line)).group("host") for line in lines]
    assert hosts == ["203.0.113.7", "203.0.113.8", "203.0.113.9"]


def test_npm_scanner_ignores_normal_requests():
    rx = failregex("npm-scanner.conf")
    line = (
        '[19/Oct/2026:15:00:08 +0000] - 200 200 - POST https erp.example.com "/web/login" '
        '[Client 203.0.113.7] [Length 30] [Gzip -] [Sent-to web] "Mozilla/5.0" "-"'
    )
    assert rx.search(without_npm_date(line)) is None


def test_npm_default_scanner_on_combined_log():
    rx = failregex("npm-default-scanner.conf")
    # datepattern ^[^\[]*\[({DATE}) removes the date inside the brackets.
    line = '203.0.113.20 - - [] "GET /.env HTTP/1.1" 444 0 "-" "Mozilla/5.0"'
    assert rx.search(line).group("host") == "203.0.113.20"
    assert rx.search('203.0.113.20 - - [] "GET / HTTP/1.1" 444 0 "-" "Mozilla/5.0"') is None
