"""Rendering, the JSON round trip and the command line."""

import json
from pathlib import Path

from opseye import cli
from opseye.i18n import STRINGS, strings_for
from opseye.render import render_html, render_text
from opseye.report import Report, level_above, level_below, worst
from opseye.util import read_env

EXAMPLE = Path(__file__).resolve().parent / "fixtures" / "status-example.json"


def example():
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return data, Report.from_dict(data, strings_for(data["lang"]))


def test_levels():
    assert [level_above(v, warn=80, crit=90) for v in (50, 85, 95)] == ["ok", "warn", "crit"]
    assert [level_below(v, warn=15, crit=8) for v in (30, 10, 3)] == ["ok", "warn", "crit"]
    assert worst("ok", "warn", "info") == "warn"
    assert worst("warn", "crit") == "crit"


def test_translations_have_the_same_keys():
    assert set(STRINGS["bs"]) == set(STRINGS["en"])
    assert strings_for("xx") is STRINGS["en"]


def test_attention_lists_errors_first():
    r = Report(strings_for("en"), host="test")
    r.flag("warn", "second")
    r.flag("ok", "never listed")
    r.flag("crit", "first", "adv_cron")
    assert [text for _, text, _ in r.sorted_attention()] == ["first", "second"]
    html = render_html(r, cli.tool_ports({}))
    assert html.index("first") < html.index("second")
    assert "never listed" not in html


def test_quiet_page_when_nothing_needs_attention():
    r = Report(strings_for("en"), host="test")
    assert "Nothing needs attention." in render_html(r, cli.tool_ports({}))
    assert "Nothing needs attention." in render_text(r)


def test_values_are_escaped():
    r = Report(strings_for("en"), host="<b>host</b>")
    sec = r.section("security")
    sec["tables"].append(
        {
            "head": ["Jail"],
            "rows": [['<script>alert("x")</script>', "warn"]],
            "num_cols": [],
            "state_col": True,
        }
    )
    r.flag("crit", "<img src=x onerror=alert(1)>")
    html = render_html(r, cli.tool_ports({}))
    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html
    assert "<b>host</b>" not in html


def test_example_report_renders_both_ways():
    data, r = example()
    html = render_html(r, cli.tool_ports({}))
    assert html.count('<span class="pill pill-crit">') >= 2  # attention row and table row
    assert "staging.example.com" in html
    text = render_text(r)
    assert text.splitlines()[2] == "Needs attention (4)"
    assert "  [!!] Database staging: Overdue cron jobs 12" in text


def test_json_round_trip():
    data, r = example()
    again = json.loads(json.dumps(r.to_dict()))
    assert again == data


def test_command_line_writes_the_page(tmp_path):
    out = tmp_path / "out"
    assert cli.main(["--from-json", str(EXAMPLE), "--env", str(tmp_path / "none"), "--out", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["index.html", "status.json", "style.css", "theme.js"]
    page = (out / "index.html").read_text(encoding="utf-8")
    assert '<script src="theme.js"></script>' in page
    assert '<a href="http://127.0.0.1:7880/">' in page  # GoAccess through the SSH tunnel


def test_broken_collector_does_not_hide_the_others():
    def broken(r, env, cache):
        raise RuntimeError("no /proc here")

    def working(r, env, cache):
        r.section("server")["kv"].append(("Load", "0.1", "ok"))

    r = cli.collect({}, cache=None, collectors=[broken, working])
    assert r.errors == ["broken: RuntimeError: no /proc here"]
    assert r.sections[0]["kv"] == [("Load", "0.1", "ok")]


def test_read_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('# comment\nA=1\nB="two words"\n\nC=\nnot a setting\n', encoding="utf-8")
    assert read_env(env_file) == {"A": "1", "B": "two words", "C": ""}
    assert read_env(tmp_path / "missing") == {}
