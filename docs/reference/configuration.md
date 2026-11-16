# Configuration

Steward reads its settings from `STEWARD_*` variables in the environment or in the `.env` file beside `compose.yml`. Every variable is listed below, with the gateway's own settings further down.

- The settings marked "Get Steward ready" can also be set in the app, under Settings › Get Steward ready. A line in `.env` wins over the app, even an empty one.
- Email goes together: one email variable in `.env` puts all of email in `.env`.
- Steward reads `.env` when it starts, so a change takes effect after `docker compose up -d`.

To do something with these settings, start from a guide: [access](../guides/access.md), [email](../guides/email.md), [backups](../guides/backups.md), [bank data](../guides/bank-data.md), [the encryption key](../guides/encryption-key.md) or [the gateway](../guides/gateway.md). The [install quick start](../quickstart/install.md) sets the two you need first.

## Steward's settings

| Variable | Default | In the app | What it does |
|---|---|---|---|
| `STEWARD_DATA_DIR` | required | | The folder that holds the books, the directory and the encryption key. The Docker image sets it to `/data`. |
| `STEWARD_BASE_URL` | required | | The address people open Steward at, like `https://steward.example.com`. Passkeys are tied to it, writes from any other address are refused, and the links in emails and the setup link start with it. |
| `STEWARD_HOST` | `127.0.0.1` | | The address Steward listens on. The Docker image sets `0.0.0.0` inside the container; compose publishes the port on `127.0.0.1` only, so Steward answers on this machine unless you choose a way in. [S13](../CLAIMS.md#s13) |
| `STEWARD_PORT` | `8420` | | The port Steward listens on. The Docker image sets `8420`. |
| `STEWARD_ENV` | `prod` | | `prod` for a real install. `test` is for the automated tests: it turns off the background jobs and sends no email. In `prod`, Steward refuses to start while a demo sign-in is left in the books. [S14](../CLAIMS.md#s14) |
| `STEWARD_SESSION_DAYS` | `30` | | How many days a sign-in lasts before the device asks again. |
| `STEWARD_TRUSTED_PROXIES` | `127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` | | The addresses Steward believes when they say which address and which scheme a request came in on. Tailscale and the bundled proxy connect from these ranges. |
| `STEWARD_KEY_FILE` | `steward.key` in the data folder | | Where the encryption key lives, such as a Docker secret at `/run/secrets/steward_key`. Backups never hold it. |
| `STEWARD_GATEWAY_URL` | none | | The gateway's address, like `http://gateway:8430` in compose. With a paired gateway, Ask, categorizing and PDF reading go through it. Empty means no gateway. |
| `STEWARD_GATEWAY_NAME` | `the gateway` | Get Steward ready | What the screens call the gateway machine. |
| `STEWARD_CATEGORIZER_URL` | none | | For development: the address of a categorizer to use instead of the paired gateway. |
| `STEWARD_CATEGORIZER_TIMEOUT_S` | `2` | | Seconds to wait for the categorizer to answer about one row. |
| `STEWARD_CATEGORIZER_BATCH_TIMEOUT_S` | `60` | | Seconds to wait for the categorizer to answer about a batch of up to 50 rows. |
| `STEWARD_STATEMENT_READING` | `auto` | | Where PDF statements are opened: `local` on this machine, `gateway` on the gateway, or `auto`, which opens them here when this machine can confine the PDF sandbox (a seccomp filter and a Landlock wall, which needs Linux 5.13 or later) and sends them to the gateway when it can't. |
| `STEWARD_STATEMENT_READER` | `false` | | For tests: starts the PDF reader under `STEWARD_ENV=test`. |
| `STEWARD_SYNC_HOURS` | `6` | | Hours between automatic bank syncs. `0` turns automatic sync off. |
| `STEWARD_SIMPLEFIN_HOSTS` | `bridge.simplefin.org,beta-bridge.simplefin.org` | | The bank-feed hosts Steward may connect to, separated by commas. A link for any other host is refused. |
| `STEWARD_TIMEZONE` | empty: then `TZ`, then UTC | Get Steward ready | The household's time zone, like `America/Chicago`. It decides which day a row falls on and when the daily backup runs. |
| `STEWARD_BACKUP_AT` | `03:00` | Get Steward ready | The time of day for the built-in backup, as `HH:MM` in the household's time zone. Empty turns it off. |
| `STEWARD_BACKUP_DIR` | `backups` in the data folder | | Where every backup goes. Put it on another disk by mounting that disk and naming the mounted folder. |
| `STEWARD_BACKUP_PING_URL` | none | Get Steward ready | An `https://` or `http://` address that Steward fetches after each backup, and again with `/fail` added after a failed one. It can't hold a user name or password. |
| `STEWARD_SMTP_HOST` | none | Get Steward ready | The outgoing mail server's name. Email is off until the host, user, password and from address are all set. |
| `STEWARD_SMTP_PORT` | `465` | Get Steward ready | The mail server's port: 465 for TLS from the start, or 587 for STARTTLS. |
| `STEWARD_SMTP_USER` | none | Get Steward ready | The user name the mail server gave you. |
| `STEWARD_SMTP_PASSWORD` | none | Get Steward ready | The mail server's password. Steward never shows it again after you save it. [S9](../CLAIMS.md#s9) |
| `STEWARD_MAIL_FROM` | none | Get Steward ready | The address emails come from. |
| `STEWARD_EXPORT_TMP_DIR` | the system's temporary folder | | Where a book export is assembled before it's offered for download. Leftover folders older than 10 minutes are removed. |
| `STEWARD_WEB_DIR` | Steward's own built web app | | For tests and development: a different folder of built web files to serve. |

## Set outside Steward's settings

These are read by the demo command, the container or the other compose services, not by Steward's settings.

| Variable | Where | What it does |
|---|---|---|
| `STEWARD_ALLOW_DEMO` | The environment of `steward seed-demo` | `1` lets `steward seed-demo` fill a vault whose `STEWARD_ENV` is `prod`. Only the demo compose file sets it, on a throwaway data folder. A real install refuses to start while a demo sign-in is left. [S14](../CLAIMS.md#s14) |
| `STEWARD_DEMO_PORT` | The shell that runs the demo, read by Docker Compose | The port the demo answers on, on this machine only. It is `8420` unless set, the same as Steward's own, so set it to another port, such as `8425`, to run the demo beside an install. See [the demo](../quickstart/demo.md). |
| `TZ` | The container's environment | The time zone to use when `STEWARD_TIMEZONE` is empty and `TZ` names a zone. Otherwise Steward uses UTC. |
| `COMPOSE_PROFILES` | `.env`, read by Docker Compose | Which parts of the compose file start: `tailscale`, `domain` or `lan` for a way in, and `gateway` and `ollama` for Ask. `gateway-nvidia` or `gateway-amd` replaces `gateway` and `ollama` for a GPU gateway. |
| `STEWARD_PROXY_BIND` | `.env`, read by Docker Compose | The address the `domain` and `lan` proxy listens on. `127.0.0.1` is this machine only; set this machine's address on your network so phones can reach it. [S13](../CLAIMS.md#s13) |
| `STEWARD_GPU_LICENSE_ACCEPTED` | `.env`, read by Docker Compose | `nvidia` or `amd`, once you have read that vendor's licenses in [Speed up the gateway with a GPU](../guides/gpu.md#licenses). Until it names the GPU gateway's vendor, Steward won't build or run that gateway. |
| `STEWARD_RENDER_GID` | `.env`, read by Docker Compose | AMD only: the number of this machine's render group, which the AMD gateway joins to reach the GPU. Detection prints it. |
| `STEWARD_DOMAIN` | `proxy.env` | The name Steward is reached at: a plain lowercase host name, with no `https://`, no port and no spaces. |
| `STEWARD_TLS` | `proxy.env` | How the proxy gets its certificate: `dns-cloudflare` (the default), `http` or `internal`. The `lan` profile always uses `internal`. |
| `CLOUDFLARE_API_TOKEN` | `proxy.env` | With `dns-cloudflare`, the Cloudflare API token that proves you own the domain. |
| `TS_AUTHKEY` | `tailscale.env` | A one-off Tailscale auth key for the first sign-in. After that the machine's identity is kept in the `tailscale-state` volume and the line can go. |

## gateway.toml

The gateway reads `gateway.toml` from its config folder. The file is optional, and a missing key takes the default below. A value outside its limit stops the gateway at start, with a message that names the key.

| Key | Default | What it does |
|---|---|---|
| `host` | `127.0.0.1` | The address the gateway listens on. It must be 127.0.0.1 or this machine's Tailscale address (100.64.0.0/10). In compose mode it may also be `0.0.0.0`, inside the container. [S12](../CLAIMS.md#s12) |
| `port` | `8430` | The port the gateway listens on. |
| `network` | `tailscale` | `tailscale` for a machine of its own. `compose` for the gateway's Docker image only: it lets the gateway listen inside its container and use the `ollama` service. It's refused outside a container and with `mcp = true`. [S12](../CLAIMS.md#s12) |
| `timezone` | `America/Los_Angeles` | The budget's month starts at midnight in this time zone. |
| `model` | `claude-opus-5-5` | The model that answers questions. One of `claude-opus-5-5` or `claude-sonnet-5-5`. |
| `max_cap_dollars` | `100` | The most the monthly budget can be raised to, in dollars. At least 10, the starting budget. |
| `prices` | built in | Dollars per million tokens, one `[prices.<model>]` table per model with `input`, `output`, `cache_write` and `cache_read`. Prices are built in for `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-opus-5` and `claude-opus-4-8`. A table of your own replaces the built-in one, and the gateway won't start if any of those four has no price. |
| `ollama_url` | `http://127.0.0.1:11434` | Where the local model runs. It must be on this machine, or the `ollama` service in compose mode, like `http://ollama:11434`. |
| `title_model` | `qwen3.5:9b-q4_K_M` | The local model that writes chat titles. |
| `categorizer_model` | `qwen3.5:9b-q4_K_M` | The local model that categorizes rows. |
| `categorizer_parallel` | `4` | How many prompts the local model runs at once, from 1 to 8. Match it to `OLLAMA_NUM_PARALLEL`. |
| `statement_layout_model` | the value of `categorizer_model` | The local model that works out a statement's layout. |
| `statement_layout_timeout_s` | `120` | Seconds to wait for a layout, from 10 to 600. |
| `statement_vision_model` | `gemma4:12b-it-qat` | The local model that reads scanned pages. |
| `statement_page_timeout_s` | `90` | Seconds to wait for one scanned page, from 10 to 600. |
| `nas_url` | none | For Claude Code only: Steward's address on your tailnet, like `https://steward.tail1234.ts.net`, or on this machine. |
| `mcp` | `false` | `true` lets Claude Code connect over MCP. Off, nothing listens on `mcp_port`. |
| `mcp_port` | `8431` | The port for Claude Code on 127.0.0.1, from 1024 to 65535 and not the gateway's own `port`. |

## The gateway's environment

| Variable | Where | What it does |
|---|---|---|
| `STEWARD_GATEWAY_CONFIG_DIR` | The gateway's environment | The folder with `gateway.toml`, `gateway.env` and the pairing token. The Docker image sets `/etc/steward-gateway`. Unset, the gateway uses `/etc/steward-gateway` when its own account owns that folder, and `~/.config/steward-gateway` otherwise. |
| `STEWARD_GATEWAY_STATE_DIR` | The gateway's environment | The folder with the budget ledger and the pairing window. The Docker image sets `/var/lib/steward-gateway`. Unset, the gateway uses `/var/lib/steward-gateway` when its own account owns the config folder, and `~/.local/state/steward-gateway` otherwise. |
| `ANTHROPIC_API_KEY` | `gateway.env` in the config folder | Your Claude API key. It stays on the gateway and never passes through Steward, which doesn't connect to Claude itself. [P14](../CLAIMS.md#p14) |
