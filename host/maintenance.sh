#!/usr/bin/env bash
# Weekly cleanup that never touches data: dangling Docker images, build cache
# older than a week, anonymous volumes, apt caches and the journal above its
# limit. Prints a short report; run from the ops-eye-maintenance timer or by
# hand.
#
# Odoo keeps attachments of every database in a filestore directory named
# after it, and dropping a database leaves that directory behind. The script
# lists such directories; it removes them only with
# CLEAN_ORPHAN_FILESTORE=yes in .env, because a wrong container name or a
# database that is down for a moment would make every directory look orphaned.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" && set +a
echo "ops-eye maintenance $(date '+%Y-%m-%d %H:%M')"
before=$(df --output=avail -B1 / | tail -1)
docker builder prune -af --filter until=168h 2>&1 | tail -1
docker image prune -f 2>&1 | tail -1
docker volume prune -f 2>&1 | tail -1
apt-get clean
apt-get -y autoremove --purge 2>&1 | tail -1
journalctl --vacuum-size="${JOURNAL_MAX:-300M}" 2>&1 | tail -1
if [ -n "${ODOO_WEB_CONTAINER:-}" ] && [ -n "${ODOO_DB_CONTAINER:-}" ]; then
  fs=/var/lib/odoo/.local/share/Odoo/filestore
  if dbs=$(docker exec "$ODOO_DB_CONTAINER" psql -U "${ODOO_DB_USER:-odoo}" -d postgres -Atc \
      "select datname from pg_database where not datistemplate") && [ -n "$dbs" ]; then
    docker exec "$ODOO_WEB_CONTAINER" ls -1 "$fs" 2>/dev/null | while IFS= read -r dir; do
      grep -qxF -- "$dir" <<< "$dbs" && continue
      if [ "${CLEAN_ORPHAN_FILESTORE:-no}" = yes ]; then
        docker exec "$ODOO_WEB_CONTAINER" rm -rf -- "$fs/$dir" && echo "removed orphan filestore $dir"
      else
        echo "orphan filestore $dir (set CLEAN_ORPHAN_FILESTORE=yes to remove)"
      fi
    done
  else
    echo "database list unavailable, filestore check skipped"
  fi
fi
after=$(df --output=avail -B1 / | tail -1)
echo "freed $(( (after - before) / 1024 / 1024 )) MB"
