# Upgrade Steward

Read this when a new version is out and you want to move to it.

1. Back up first.

   ```
   docker compose exec steward steward backup
   ```

2. Set the new version in `compose.yml`, in the `image:` lines of `steward`, and of `steward-proxy` and `steward-gateway` if you use them.
3. Pull and restart.

   ```
   docker compose pull && docker compose up -d
   ```

Migrations run when Steward starts, so there is nothing else to run. Check `docker compose ps` shows Steward as healthy, then open it.

A migration can change a book in a way the old version cannot read. If a new version fails to start, restore the backup from step 1 before you go back to the old version (see [backups](backups.md)).

## Verify the images

Each release image is signed by the release workflow, with no stored key, and comes with an SBOM. [S8](../CLAIMS.md#s8) To check one before you run it, install cosign and run this with the version you are pulling.

```
cosign verify ghcr.io/steward-money/steward:<version> \
  --certificate-identity-regexp '^https://github\.com/steward-money/steward/\.github/workflows/release\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

It prints the signature's details and exits 0 when the image was built by that workflow from a version tag. Use the same command with `steward-proxy` or `steward-gateway` in place of `steward`.

See [ports and volumes](../reference/ports-and-volumes.md) for what an upgrade leaves alone.
