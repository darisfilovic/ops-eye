#!/usr/bin/env python3
"""First-run setup for the tools that keep their own accounts.

    python3 bin/setup.py

- Portainer: creates the admin user with the setup token from its log.
- Beszel: creates the superuser and the first user, reads the hub's public
  key, registers this host as a system over the shared unix socket and
  writes BESZEL_KEY into .env, then restarts the agent.

One password for both, generated once and stored as OPS_ADMIN_PASSWORD in
.env. Safe to run again: steps that are already done are skipped.
"""

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def read_env():
    env = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def set_env(key, value):
    if any(ch in value for ch in " #\t"):
        value = '"' + value.replace('"', "") + '"'
    lines = ENV.read_text().splitlines()
    done = False
    for i, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[i] = f"{key}={value}"
            done = True
    if not done:
        lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n")


def api(url, data=None, headers=None, method=None):
    # Both tools are reached only on the loopback address of this host.
    if not url.startswith("http://127.0.0.1:"):
        raise ValueError(f"not a local URL: {url}")
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method or ("POST" if body else "GET"))  # noqa: S310
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": str(e)}


def sh(*args):
    """Run a command without a shell, return stdout and stderr together."""
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p.stdout


def setup_portainer(env, password):
    base = f"http://127.0.0.1:{env.get('OPS_PORTAINER_PORT', '9000')}"
    user = env.get("OPS_ADMIN_USER", "admin")
    status, _ = api(f"{base}/api/auth", {"Username": user, "Password": password})
    if status == 200:
        print("Portainer: admin already set up")
        return
    log = sh("docker", "logs", "ops-eye-portainer")
    token = ""
    for line in log.splitlines():
        if "setup_token=" in line:
            token = line.split("setup_token=", 1)[1].split()[0]
    if not token:
        print("Portainer: no setup token in the log (admin may already exist with another password)")
        return
    status, body = api(
        f"{base}/api/users/admin/init",
        {"Username": user, "Password": password},
        headers={"X-Setup-Token": token},
    )
    print("Portainer:", "admin created" if status == 200 else f"failed ({status}) {body}")


def setup_beszel(env, password):
    base = f"http://127.0.0.1:{env.get('OPS_BESZEL_PORT', '8090')}"
    email = "admin@ops-eye.local"
    status, body = api(
        f"{base}/api/collections/users/auth-with-password", {"identity": email, "password": password}
    )
    if status != 200:
        # The Beszel CLI takes the password only as an argument. Without a shell
        # it is passed as one argument and cannot break out of quotes.
        out = sh("docker", "exec", "ops-eye-beszel", "/beszel", "superuser", "upsert", email, password)
        if "Successfully" not in out:
            print("Beszel: superuser failed:", out.strip()[-200:])
            return
        status, sup = api(
            f"{base}/api/collections/_superusers/auth-with-password",
            {"identity": email, "password": password},
        )
        api(
            f"{base}/api/collections/users/records",
            {
                "email": email,
                "password": password,
                "passwordConfirm": password,
                "username": "admin",
                "role": "admin",
                "verified": True,
            },
            headers={"Authorization": sup.get("token", "")},
        )
        status, body = api(
            f"{base}/api/collections/users/auth-with-password", {"identity": email, "password": password}
        )
        if status != 200:
            print("Beszel: user login failed", body)
            return
        print("Beszel: user created")
    else:
        print("Beszel: user already set up")
    token, uid = body["token"], body["record"]["id"]
    status, key = api(f"{base}/api/beszel/getkey", headers={"Authorization": token})
    key = key.get("key", "")
    if key and env.get("BESZEL_KEY") != key:
        set_env("BESZEL_KEY", key)
        print("Beszel: hub key written to .env")
        # Compose prefers the shell environment over .env, so drop stale values.
        env_clean = {k: v for k, v in os.environ.items() if k not in ("BESZEL_KEY", "BESZEL_TOKEN")}
        subprocess.run(
            ["docker", "compose", "up", "-d", "beszel-agent"], cwd=ROOT, env=env_clean, capture_output=True
        )
        time.sleep(5)
    status, systems = api(f"{base}/api/collections/systems/records", headers={"Authorization": token})
    if status == 200 and any(s.get("host") == "/beszel_socket/beszel.sock" for s in systems.get("items", [])):
        print("Beszel: this host already registered")
        return
    status, body = api(
        f"{base}/api/collections/systems/records",
        {"name": os.uname().nodename, "host": "/beszel_socket/beszel.sock", "port": "45876", "users": [uid]},
        headers={"Authorization": token},
    )
    print("Beszel:", "host registered" if status == 200 else f"registration failed ({status}) {body}")


def main():
    if not ENV.exists():
        print("Copy .env.example to .env first.")
        return 1
    env = read_env()
    password = env.get("OPS_ADMIN_PASSWORD")
    if not password:
        password = secrets.token_urlsafe(15)
        set_env("OPS_ADMIN_USER", env.get("OPS_ADMIN_USER", "admin"))
        set_env("OPS_ADMIN_PASSWORD", password)
        print("Generated OPS_ADMIN_PASSWORD, stored in .env")
        env = read_env()
    setup_portainer(env, password)
    setup_beszel(env, password)
    print("Login for Portainer and Beszel: user admin (Beszel email admin@ops-eye.local), password in .env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
