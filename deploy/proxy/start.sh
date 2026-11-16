#!/bin/sh
# steward-proxy's entrypoint: checks its settings, then runs Caddy with the baked-in Caddyfile that STEWARD_TLS names:
# dns-cloudflare (the default), http or internal. {$STEWARD_DOMAIN} is pasted into the Caddyfile as text, so only a
# plain host name gets through.
set -eu
tls=${STEWARD_TLS:-dns-cloudflare}
case "$tls" in
  dns-cloudflare | http | internal) ;;
  *)
    echo "STEWARD_TLS must be dns-cloudflare, http or internal. It is: '$tls'. Set it in proxy.env (docs/guides/access.md, \"Your own domain\")." >&2
    exit 1 ;;
esac
d=${STEWARD_DOMAIN:-}
case "$d" in
  "" | *[!a-z0-9.-]* | .* | *. | *..* | -* | *- | *-.* | *.-*) ok=no ;;
  *.*) ok=yes ;;
  *) if [ "$tls" = internal ]; then ok=yes; else ok=no; fi ;;
esac
if [ "$ok" = no ] || [ "${#d}" -gt 253 ]; then
  echo "STEWARD_DOMAIN must be a plain lowercase host name such as steward.example.com: no https://, no port, no spaces. It is: '$d'. Set it in proxy.env (docs/guides/access.md, \"Your own domain\")." >&2
  exit 1
fi
# An IP address passes the check above, starts, and then fails every handshake: a browser sends no name for one, so
# Caddy can't choose the certificate (install gate INS-1). Passkeys need a name too.
case "$d" in
  *[!0-9.]*) ;;
  *)
    echo "STEWARD_DOMAIN is an IP address: '$d'. Use a name for this machine, such as steward.lan or $d.nip.io (docs/guides/access.md, \"LAN only\")." >&2
    exit 1 ;;
esac
if [ "$tls" = dns-cloudflare ] && [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "CLOUDFLARE_API_TOKEN is empty. Put a Cloudflare API token in proxy.env (docs/guides/access.md, \"Your own domain\")." >&2
  exit 1
fi
exec caddy run --config "/etc/caddy/Caddyfile.$tls" --adapter caddyfile
