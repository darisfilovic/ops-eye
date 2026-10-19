# Nginx Proxy Manager includes

NPM overwrites the generated conf files, so nothing is edited there. Two
kinds of customisation survive:

1. Files in `/data/nginx/custom/` (the `data` directory mounted into the NPM
   container). `http_top.conf` is included at the top of the http block,
   `server_proxy.conf` at the end of every proxy host's server block.
2. The Advanced tab of each proxy host in the NPM UI.

Install the include files:

```
cp nginx/npm/http_top.conf nginx/npm/server_proxy.conf /path/to/npm/data/nginx/custom/
docker exec <npm-container> nginx -t && docker exec <npm-container> nginx -s reload
```

If a `http_top.conf` already exists (rate limit zones), merge: keep the
existing zone names and add the gzip block and the `$ops_bad_bot` map.

Then paste `odoo-host-advanced.conf` into the Advanced tab of every Odoo
host, and enable Force SSL, HTTP/2 and HSTS on the SSL tab.

Check afterwards:

```
curl -sI -H 'Accept-Encoding: gzip' https://host/web/assets/... | grep -i content-encoding   # gzip
curl -sI https://host/wp-login.php      # empty reply (444)
curl -sI https://host/xmlrpc/2/common   # still answers: integrations use it
```

The `npm-scanner` fail2ban jail in `host/fail2ban` bans addresses that hit
the 444 rules twice in an hour.
