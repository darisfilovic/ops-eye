"""Command line: collect the state of the host and write the status page."""

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from .collectors import COLLECTORS
from .i18n import strings_for
from .render import render_html, render_text
from .report import Report
from .util import Cache, read_env

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"


def tool_ports(env):
    """Local port of each tool linked from the page, keyed by its label in i18n."""
    return {
        "tool_goaccess": env.get("OPS_GOACCESS_PORT", "7880"),
        "tool_beszel": env.get("OPS_BESZEL_PORT", "8090"),
        "tool_f2b": env.get("OPS_F2B_PORT", "8091"),
        "tool_portainer": env.get("OPS_PORTAINER_PORT", "9000"),
        "tool_cockpit": "9090",
    }


def collect(env, cache, collectors=COLLECTORS):
    lang = env.get("OPS_LANG", "en")
    r = Report(strings_for(lang), host=os.uname().nodename, lang=lang)
    start = time.monotonic()
    for collector in collectors:
        try:
            collector(r, env, cache)
        except Exception as e:  # a broken collector must not hide the rest of the page
            r.errors.append(f"{collector.__name__}: {e.__class__.__name__}: {e}")
    r.elapsed = time.monotonic() - start
    return r


def write_page(r, env, out):
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(render_html(r, tool_ports(env)), encoding="utf-8")
    for name in ("style.css", "theme.js"):
        shutil.copy(STATIC / name, out / name)
    data = json.dumps(r.to_dict(), ensure_ascii=False, indent=1)
    (out / "status.json").write_text(data, encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ops-eye", description="Status page of a Docker host running Odoo.")
    ap.add_argument("--text", action="store_true", help="print the report instead of writing the page")
    ap.add_argument(
        "--env", default=str(ROOT / ".env"), help="settings file (default: .env in the repository)"
    )
    ap.add_argument("--out", default=str(ROOT / "out"), help="directory for index.html and status.json")
    ap.add_argument(
        "--from-json",
        metavar="FILE",
        help="render a saved status.json instead of collecting (screenshots, tests)",
    )
    args = ap.parse_args(argv)
    env = read_env(args.env)
    out = Path(args.out)
    if args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        r = Report.from_dict(data, strings_for(data.get("lang", "en")))
    else:
        r = collect(env, Cache(out / "cache.json"))
    if args.text:
        print(render_text(r))
    else:
        write_page(r, env, out)
    return 0
