# steward-proxy: Caddy with the Cloudflare DNS module, Steward's optional HTTPS front door (docs/quickstart/install.md).
# Published by .github/workflows/release.yml as ghcr.io/steward-money/steward-proxy. Versions are pinned here and in tests/test_proxy_files.py; change both together.
FROM caddy:2.11.7-builder@sha256:d842facfd63b960922e57444ff76fd8f0793a66dfdcf481af8026e1f4e6a39b4 AS build
# The builder image sets XCADDY_SETCAP=1, which gives the binary file capabilities; compose drops them all, so it couldn't exec.
ENV XCADDY_SETCAP=0
RUN xcaddy build v2.11.7 --with github.com/caddy-dns/cloudflare@v0.2.4

FROM caddy:2.11.7-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f
# curl is for a compose healthcheck. The proxy gets its own user: not root, not Steward's 1000.
RUN apk add --no-cache curl && addgroup -S -g 1001 proxy && adduser -S -D -H -u 1001 -G proxy proxy
# Copied over the base image's binary, so it carries no file capabilities (compose drops them all).
COPY --from=build /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile.dns-cloudflare Caddyfile.http Caddyfile.internal /etc/caddy/
COPY --chmod=0755 start.sh /usr/local/bin/steward-proxy
# Fail the build, not the box, if the module is missing or a Caddyfile doesn't parse. Validation may make Caddy's
# local CA, so it works in /tmp and removes it in this same layer: no CA key is ever in the image.
RUN caddy list-modules | grep -qx dns.providers.cloudflare \
 && for mode in dns-cloudflare http internal; do \
      XDG_DATA_HOME=/tmp/caddy-validate XDG_CONFIG_HOME=/tmp/caddy-validate STEWARD_DOMAIN=steward.example.com \
      CLOUDFLARE_API_TOKEN=0000000000000000000000000000000000000000 \
      caddy validate --config "/etc/caddy/Caddyfile.$mode" --adapter caddyfile || exit 1; \
    done \
 && rm -rf /tmp/caddy-validate
USER 1001:1001
ENTRYPOINT ["/usr/local/bin/steward-proxy"]
