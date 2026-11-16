# Move Steward to a new machine

Read this when Steward is changing machines, or you are rebuilding after losing one.

What to carry across is the `data/` folder, the key, your settings files and the address.

## Before you start

- Keep the same `STEWARD_BASE_URL`. Passkeys are tied to that address, so keep it and they keep working. If it changes, each person adds their device again.
- Know where the key is. By default it is `data/steward.key`. If `STEWARD_KEY_FILE` keeps it elsewhere, copy that file too. A backup does not hold it (see [the encryption key](encryption-key.md)).

## Move

1. On the old machine, back up and stop.

   ```
   docker compose exec steward steward backup
   docker compose down
   ```

2. Copy the `data/` folder to the new machine, with the key if it lives elsewhere. If you are rebuilding from a backup instead, restore the copies as in [backups](backups.md) before you start Steward, and put the key from your password manager in place.
3. On the new machine, set the owner and the key's mode.

   ```
   sudo chown -R 1000:1000 data
   chmod 600 data/steward.key
   ```

4. Copy `compose.yml`, `.env` and any `proxy.env` and `tailscale.env`. Tailscale needs a new auth key, because a new machine joins as a new device. Delete the old device from your tailnet first, or the new one gets a numbered name.
5. Point your name at the new machine if you use your own domain (see [access](access.md)).
6. Start Steward, then check the books.

   ```
   docker compose up -d
   docker compose exec steward steward restore-check
   ```

Start Steward only after the data and the key are in place. On an empty `data/` it would make a new key and an empty directory, and your books would not open with them.

The gateway's pairing is stored in the same `data/` folder, so it moves with it. If the gateway runs on another machine, it keeps its own pairing.

See [ports and volumes](../reference/ports-and-volumes.md) for everything Steward keeps on disk.
