"""Small helpers shared by the collectors: settings, commands, sizes, cache."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def read_env(path):
    """Read the KEY=value lines of a .env file. A missing file gives an empty dict."""
    env = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return env
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def env_list(env, key):
    """The comma separated value of key as a list, without empty items."""
    return [item.strip() for item in env.get(key, "").split(",") if item.strip()]


def run(cmd, timeout=20):
    """Run a command given as an argument list, return stdout or None. Never raises.

    No shell is involved, so names that come from .env or from the output of
    other tools (domains, jails) are passed as plain arguments.
    """
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else (p.stdout or None)


def human_bytes(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def parse_size(text):
    """Bytes in a size printed by Docker or journald: '4.0G', '12.09GB', '605.8MB'."""
    m = re.search(r"([0-9.]+)\s*([KMGT]?)i?B?", text or "")
    if not m:
        return 0
    factor = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[m.group(2)]
    return float(m.group(1)) * factor


def tail_text(path, limit=20 * 1024 * 1024):
    """The last limit bytes of a file as text, starting at a whole line."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > limit:
                f.seek(size - limit)
                f.readline()
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


class Cache:
    """A JSON file that remembers slow or rate-limited lookups (whois, certificates, apt)."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, ttl_seconds, compute):
        entry = self.data.get(key)
        if entry and time.time() - entry.get("at", 0) < ttl_seconds:
            return entry.get("value")
        value = compute()
        self.data[key] = {"at": time.time(), "value": value}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data), encoding="utf-8")
        except OSError as e:
            # The value is still used for this run; only the next run repeats the lookup.
            print(f"ops-eye: cache not saved: {e}", file=sys.stderr)
        return value
