# Keep the encryption key safe

Read this before you rely on Steward for anything you cannot re-enter, and again when you change where the key lives.

Your books are encrypted at rest with SQLCipher, using AES-256. [S1](../CLAIMS.md#s1) The key is a 64-character hex string. Without it no book and no backup opens, and Steward cannot recover it for you.

## What the encryption protects

With the key in the same folder as the data, encryption protects copies and backups, not a running box. Someone who can read the whole data folder can read the key beside it. Steward's backups never hold the key, so a backup on another disk or in cloud storage is useless without it. To protect the running machine as well, keep the key on its own mount.

## Keep a copy

1. Find the key. By default it is `data/steward.key`.
2. Save its 64 characters in your password manager, in a note you will recognize.
3. Check the saved copy against the file, character for character.

This is the one thing a backup cannot give you back. If the machine and your copy are both lost, the books are gone.

## Put the key on its own mount

Use `STEWARD_KEY_FILE` to keep the key outside the data folder, for example as a Docker secret. Backups never hold it. [S2](../CLAIMS.md#s2)

1. For a new install, run `docker compose run --rm steward steward keygen`. It prints a new key and writes nothing. For an install that already has books, move `data/steward.key` instead, because a different key cannot open them.
2. Save the key where `STEWARD_KEY_FILE` will point, such as `/run/secrets/steward_key`.
3. Make the file mode 600 or 400, readable by uid 1000, the user Steward runs as. Steward refuses a key file that other users can read.
4. Set `STEWARD_KEY_FILE` in `.env` and run `docker compose up -d`.

See [commands](../reference/commands.md#steward-keygen) and [configuration](../reference/configuration.md#stewards-settings). For what a copy of the data folder alone gives an attacker, see [the threat model](../explanations/threat-model.md).
