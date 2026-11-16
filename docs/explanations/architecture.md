# Architecture

This page describes the pieces of Steward and what each one does. It is for someone who wants to know how the parts fit before trusting them with their money.

## The pieces

```text
browser ──► Caddy or Tailscale ──► Steward ──► directory.db and one database per book
                                     │   │
                                     │   └──► PDF reader (a confined child process)
                                     │
                                     ├──► SimpleFIN   (bank data, pulled)
                                     ├──► your mail server (SMTP)
                                     └──► gateway ──► Ollama (a local model)
                                            │
                                            └──► Claude
```

Steward is one Python web application, and it serves the web app you see. Caddy or Tailscale sits in front of it and handles HTTPS. The gateway is a separate program that you run on your own hardware, and it is the only piece that reaches Claude. The boundary package holds the privacy rules, and both Steward and the gateway load it, so they apply the same checks.

## Books and the directory

Each book is its own encrypted database file with its own key, members and bank link. People, passwords, passkeys and sessions live apart from the books in `directory.db`, along with who belongs to which book and in what role.

Routes that belong to a book sit under `/api/b/<slug>/` and its pages under `/b/<slug>/`. A person who is not in a book gets 404 for it. A viewer can read a book, ask about it and change their own settings, such as emails. Changes to the book answer 403, and manager-only areas such as imports answer 404. [S16](../CLAIMS.md#s16) Routes about people and the directory, such as sign-in, stay at the top level.

To invite someone, a manager enters an email address. A person who is already in a book you manage is added at once. Anyone else gets an email with a link, `/invite?token=…`, good for 7 days. They join only when they open it, signed in, and accept. The email also has a link to choose a password only when an invite made the account: a new address, or an address an earlier invite added that has never signed in and is waiting only on books you manage. Any other account never gets one, so only its owner sets its password. With email on, Steward's answer about anyone not already in a book you manage is the same whether or not the address had an account, so the invite can't be used to find out. With email off, a manager of the household book gets the email's text to pass on instead, and that text can show it: a new address's text has the password link, and an existing account's doesn't unless an invite made it, as above. Other managers get only a note that email is off.

A parent book has Inventory and Watching. Inventory holds a parent's accounts, income, insurance, documents and contacts. Watching looks at new transactions and at the inventory for patterns worth a second look, and shows what it finds as flags.

## Keys

`steward.key` is the one secret to keep. Each book's key is derived from it with HKDF-SHA256, so no other key needs saving, and the books are encrypted with SQLCipher using AES-256. [S1](../CLAIMS.md#s1) Uploaded files are encrypted with AES-256-GCM under a key derived from the same key. Secrets the app stores, such as the email password, are sealed in the same way and never shown again. See [the encryption key](../guides/encryption-key.md) for where it lives and how to keep it safe.

## The scheduler

Steward runs a few jobs on timers inside its own process.

- A bank sync every few hours, set by `STEWARD_SYNC_HOURS`.
- A check each minute for what is due: the morning Watching run, the daily summary email, queued mail, tax reminders and Steward's own daily backup.
- A check each minute that the gateway is healthy, once it is paired.

A failed job is logged and tried again on its next turn. It does not stop the others.

## The gateway

The gateway holds the Anthropic API key and runs the redaction model. It listens only on Tailscale or on its own machine, or on private networks inside Docker Compose. Steward calls the gateway and never calls Claude itself. [P14](../CLAIMS.md#p14) See [pair the gateway](../guides/gateway.md) for how to run it.

## The privacy boundary

The rules that decide what may leave are in a shared package. Steward applies the exact ones, which replace what the book knows. The gateway applies its model and a second set of checks, and it compares every outgoing part against fingerprints of the book's identifiers. [How Ask stays private](ask.md) follows one question through them, and [privacy](privacy.md) lists what is sent.

## The PDF sandbox

A PDF statement is opened by a child process that is confined before it reads the file, and it is never run unconfined. [S6](../CLAIMS.md#s6) Confined means two things: a system-call filter that allows only what the reader does to itself, and a Landlock wall that lets it read only its own runtime. Without both, Steward sends the statement to the gateway, or it waits. The reader hands back text and the parent checks all of it, so a hostile file can't reach the network, another program, or what your files hold.

## Security checks

- **Writes come only from Steward's own pages.** A write from another site is refused, so another app on the same domain cannot change your data. [S3](../CLAIMS.md#s3)
- **The page runs only Steward's own code.** A Content-Security-Policy blocks inline styles and any script but Steward's own. [S4](../CLAIMS.md#s4)
- **Guessing is slow.** Each device has limits on what it can try without a password. [S5](../CLAIMS.md#s5)

  | What | Limit |
  | --- | --- |
  | Forgot your password | 5 per 15 minutes |
  | Sign in with a passkey | 30 per 15 minutes |
  | Accepting an invite | 10 per 15 minutes |
  | The first-run setup link | 10 per 15 minutes |

  Steward counts these in memory, so a restart forgets them.
- **The first person comes from a one-time link.** There is no open sign-up. [S7](../CLAIMS.md#s7)
- **Logs are quiet.** Steward logs a request as its method, its route's template and its status. Neither Steward nor its HTTPS proxy logs a query string. [P10](../CLAIMS.md#p10)

## The retirement engine and its data

The Plan tab runs a Python engine that never touches the database. It works from a frozen bundle of inputs built from the book. It uses historical US market returns, the Social Security formula and federal and state tax tables. `src/steward/engine/data/SOURCES.md` lists where each table comes from. The tax tables are refreshed each year on a best-effort basis, so check the year a table names before relying on a result for a tax decision.
