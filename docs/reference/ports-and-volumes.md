# Ports, volumes and files

What Steward's compose files open, mount and keep on disk. For the settings that move any of this, see [configuration](configuration.md).

## Ports

| Port | Where | What it is |
|---|---|---|
| `8420` | `127.0.0.1` on the Docker host | Steward itself. It is published on this machine only, so nothing else on the network can reach it until you choose [a way in](../guides/access.md). [S13](../CLAIMS.md#s13) |
| `443` | `STEWARD_PROXY_BIND`, default `127.0.0.1` | HTTPS from the bundled proxy. The `domain` and `lan` profiles publish it. |
| `80` | `STEWARD_PROXY_BIND`, default `127.0.0.1` | The `domain` profile only. Caddy uses it to get the certificate and to send plain HTTP to HTTPS. |
| `8430` | inside the compose network | The gateway. In compose it publishes no port, and only Steward reaches it, on the `gateway-private` network. On a machine of its own it is the port in `gateway.toml`. |
| `8431` | loopback on the gateway's machine | Claude Code's port. It is off unless `mcp = true` in `gateway.toml`, and never used in compose. |

The `tailscale` profile publishes no port. Tailscale reaches Steward from inside the compose network.

## Volumes and folders

Steward's own data is the `./data` folder beside `compose.yml`, mounted at `/data` in the container. Its owner must be uid 1000, the user the image runs as.

| Name | What it holds |
|---|---|
| `./data` | `directory.db` (who can sign in, and the list of books), `steward.db` (the first book), `books/` (every other book), `steward.key` (the encryption key, unless `STEWARD_KEY_FILE` puts it elsewhere) and `backups/`. |
| `./tailscale/serve.json` | The Tailscale profile's settings for what it shows. Mounted read-only. |
| `tailscale-state` | The Tailscale node's identity, so it stays the same machine after a restart. |
| `caddy-data` | The proxy's certificates. |
| `gateway-config` | The gateway's `gateway.toml`, and `gateway.env` with the Claude API key. |
| `gateway-state` | The gateway's pairing, and its record of spending and of what it sent. |
| `gateway-models` | The redaction model the gateway downloads on first start. |
| `ollama-models` | The local models Ollama pulls. |
| `demo-data` | The demo household in `compose.demo.yml`. It is made up, and it is the only thing that file stores. |

Backups go to `backups` in the data folder unless `STEWARD_BACKUP_DIR` says otherwise. To keep them on another disk, uncomment the backups mount in `compose.yml`, which mounts the disk at `/backups`, and set `STEWARD_BACKUP_DIR=/backups` in `.env`. See [backups](../guides/backups.md).

## Removing Steward

- `docker compose down` stops and removes the containers. The data folder, the backups and the key stay where they are.
- Delete the data folder and the backups folder yourself when you want the books gone. The key goes with the data folder unless `STEWARD_KEY_FILE` points elsewhere.
- The named volumes stay too. List them with `docker volume ls`, then remove each one with `docker volume rm`. Compose prefixes the names with the folder's name, so `caddy-data` is `<folder>_caddy-data`.
- For the demo, `docker compose -f compose.demo.yml down -v` removes the containers and `demo-data` together.
