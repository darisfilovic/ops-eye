"""The report as a static HTML page and as plain text for the terminal."""

import html

TEXT_MARKS = {"ok": "[ok]", "warn": "[! ]", "crit": "[!!]", "info": "[i ]"}


def esc(value):
    return html.escape(str(value), quote=True)


def _pill(t, sev):
    if sev == "ok":
        return ""
    return f'<span class="pill pill-{sev}">{esc(t[sev])}</span>'


def _cell(tag, value, numeric):
    cls = ' class="num"' if numeric else ""
    return f"<{tag}{cls}>{esc(value)}</{tag}>"


def _top_bar(r):
    t = r.t
    options = "".join(
        f'<option value="{value}">{esc(t[label])}</option>'
        for value, label in (("auto", "theme_auto"), ("light", "theme_light"), ("dark", "theme_dark"))
    )
    return (
        '<header class="top">'
        f'<div><span class="brand">{esc(t["title"])}</span> <span class="host">{esc(r.host)}</span></div>'
        f'<div class="meta">{esc(t["updated"])} {r.generated:%d.%m.%Y %H:%M} <span class="sep">|</span> '
        f'<label>{esc(t["theme"])} <select id="theme">{options}</select></label></div>'
        "</header>"
    )


def _attention(r):
    t = r.t
    items = r.sorted_attention()
    if not items:
        return f'<p class="allok">{esc(t["all_ok"])}</p>'
    rows = "".join(
        f'<tr><td>{_pill(t, sev)}</td><td>{esc(text)}</td><td class="muted">{esc(advice)}</td></tr>'
        for sev, text, advice in items
    )
    return (
        f'<section class="attention"><h2>{esc(t["needs"])} ({len(items)})</h2>'
        f"<table><thead><tr><th>{esc(t['status'])}</th><th>{esc(t['item'])}</th>"
        f"<th>{esc(t['next'])}</th></tr></thead><tbody>{rows}</tbody></table></section>"
    )


def _table(t, table):
    numeric = set(table["num_cols"])
    head = "".join(_cell("th", h, i in numeric) for i, h in enumerate(table["head"]))
    if table.get("state_col"):
        head += "<th></th>"
    body = []
    for row in table["rows"]:
        *cells, sev = row
        tds = "".join(_cell("td", c, i in numeric) for i, c in enumerate(cells))
        if table.get("state_col"):
            tds += f"<td>{_pill(t, sev)}</td>"
        body.append(f'<tr class="row-{sev}">{tds}</tr>')
    return (
        f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _section(t, sec):
    parts = [f"<section><h2>{esc(t[sec['key']])}</h2>"]
    if sec["kv"]:
        parts.append("<dl>")
        for label, value, sev in sec["kv"]:
            parts.append(
                f'<div class="row row-{sev}"><dt>{esc(label)}</dt><dd>{esc(value)} {_pill(t, sev)}</dd></div>'
            )
        parts.append("</dl>")
    parts.extend(_table(t, table) for table in sec["tables"])
    parts.append("</section>")
    return "".join(parts)


def _tools(t, tool_ports):
    rows = "".join(
        f'<div class="row"><dt>{esc(t[key])}</dt>'
        f'<dd><a href="http://127.0.0.1:{esc(port)}/">127.0.0.1:{esc(port)}</a></dd></div>'
        for key, port in tool_ports.items()
    )
    return (
        f'<section><h2>{esc(t["tools"])}</h2><p class="muted">{esc(t["tunnel_hint"])}</p>'
        f"<dl>{rows}</dl></section>"
    )


def render_html(r, tool_ports):
    """The whole page. tool_ports maps the i18n key of each tool to its local port."""
    t = r.t
    parts = [
        "<!doctype html>",
        f'<html lang="{esc(r.lang)}"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="refresh" content="300">',
        f"<title>{esc(t['title'])} {esc(r.host)}</title>",
        '<link rel="stylesheet" href="style.css"></head><body>',
        _top_bar(r),
        "<main>",
        _attention(r),
        *(_section(t, sec) for sec in r.sections),
        _tools(t, tool_ports),
    ]
    if r.errors:
        parts.append(f'<p class="muted">{esc(t["err_collect"])}: {esc(", ".join(r.errors))}</p>')
    parts += [
        f'<footer class="muted">{esc(t["generated_in"])} {r.elapsed:.1f} s</footer>',
        "</main>",
        '<script src="theme.js"></script>',
        "</body></html>",
    ]
    return "\n".join(parts)


def _text_table(table):
    head = [str(h) for h in table["head"]]
    rows = [([str(c) for c in row[:-1]], row[-1]) for row in table["rows"]]
    widths = [max([len(h)] + [len(cells[i]) for cells, _ in rows]) for i, h in enumerate(head)]

    def line(cells):
        return ("  " + "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True))).rstrip()

    out = [line(head)]
    for cells, sev in rows:
        out.append(line(cells) + (f"  {TEXT_MARKS[sev]}" if sev != "ok" else ""))
    return out


def render_text(r):
    t = r.t
    lines = [f"{t['title']} {r.host}  {r.generated:%d.%m.%Y %H:%M}", ""]
    items = r.sorted_attention()
    if items:
        lines.append(f"{t['needs']} ({len(items)})")
        for sev, text, advice in items:
            lines.append(f"  {TEXT_MARKS[sev]} {text}" + (f"  |  {advice}" if advice else ""))
    else:
        lines.append(t["all_ok"])
    for sec in r.sections:
        lines += ["", t[sec["key"]]]
        for label, value, sev in sec["kv"]:
            lines.append(f"  {TEXT_MARKS[sev]} {label}: {value}")
        for table in sec["tables"]:
            lines += _text_table(table)
    if r.errors:
        lines += ["", f"{t['err_collect']}: {', '.join(r.errors)}"]
    lines += ["", f"{t['generated_in']} {r.elapsed:.1f} s"]
    return "\n".join(lines)
