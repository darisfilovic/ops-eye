"""The report that every collector writes into, and its JSON form."""

from datetime import datetime

SEVERITIES = ("crit", "warn", "info", "ok")
SEV_ORDER = {sev: i for i, sev in enumerate(SEVERITIES)}


def worst(*severities):
    """The most serious of the given severities."""
    return min(severities, key=SEV_ORDER.__getitem__)


def level_above(value, warn, crit):
    """Severity of a value that is worse when it grows (disk use in percent)."""
    if value > crit:
        return "crit"
    if value > warn:
        return "warn"
    return "ok"


def level_below(value, warn, crit):
    """Severity of a value that is worse when it shrinks (days to expiry, free memory)."""
    if value < crit:
        return "crit"
    if value < warn:
        return "warn"
    return "ok"


class Report:
    """Sections of the page plus the list of items that need attention.

    A section has key/value rows (label, value, severity) and tables. A table
    is a dict with head (column titles), rows (cells followed by the severity
    of the row), num_cols (indexes of right-aligned columns) and state_col
    (show the severity as a pill in an extra last column).
    """

    def __init__(self, strings, host, lang="en", generated=None):
        self.t = strings
        self.host = host
        self.lang = lang
        self.generated = generated or datetime.now().astimezone()
        self.sections = []
        self.attention = []  # (severity, text, advice)
        self.errors = []
        self.elapsed = 0.0

    def section(self, key):
        sec = {"key": key, "kv": [], "tables": []}
        self.sections.append(sec)
        return sec

    def flag(self, severity, text, advice_key=None):
        """Put an item on the attention list. Only warnings and errors go there."""
        if severity in ("warn", "crit"):
            advice = self.t.get(advice_key, "") if advice_key else ""
            self.attention.append((severity, text, advice))

    def sorted_attention(self):
        return sorted(self.attention, key=lambda item: SEV_ORDER[item[0]])

    def to_dict(self):
        return {
            "generated": self.generated.isoformat(),
            "host": self.host,
            "lang": self.lang,
            "elapsed": round(self.elapsed, 2),
            "attention": [{"severity": s, "text": x, "advice": a} for s, x, a in self.attention],
            "sections": self.sections,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data, strings):
        r = cls(
            strings,
            host=data["host"],
            lang=data.get("lang", "en"),
            generated=datetime.fromisoformat(data["generated"]),
        )
        r.elapsed = data.get("elapsed", 0.0)
        r.attention = [(a["severity"], a["text"], a["advice"]) for a in data.get("attention", [])]
        r.sections = data.get("sections", [])
        r.errors = data.get("errors", [])
        return r
