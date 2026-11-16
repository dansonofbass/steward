# Privacy

When you ask Claude a question in Steward, Claude sees the figures it needs: balances, income, spending totals, holdings, debts, ages, your state and tax facts, with dates, categories and aliases such as "Account 1", and how each account's data arrives: a bank feed, statements, files or typed in. That is how it answers. An age is sent where a date of birth isn't, so with today's date it gives the year of birth to within one. Steward's promise is about who you are, not about hiding the numbers: your notes and account numbers stay on your machines, the names Steward holds are replaced except in store rows a manager approves, and the checks look for the other details that identify you or your family.

Every claim here links to a row in [the claims ledger](../CLAIMS.md), which names the test or the code that backs it. [How Ask stays private](ask.md) follows one question from the keyboard to the answer.

## What reaches Claude

- **The question you type**, after Steward and the gateway have checked it. The checks look for names, account numbers, email addresses, phone numbers, street addresses and ID numbers, and replace what they find. [P4](../CLAIMS.md#p4) [P5](../CLAIMS.md#p5) [P11](../CLAIMS.md#p11) The page shows what Claude will see as you type. [P16](../CLAIMS.md#p16)
- **Typed answers to Claude's lookups.** Claude asks Steward for data through tools. Each tool returns fields of a fixed type, such as amounts, dates, categories, aliases and fund symbols. It never returns your notes. [P3](../CLAIMS.md#p3)
- **Store and payee names, only in rows a manager approves.** Without that approval Claude gets an alias. A payee can be a person, such as the one a Zelle or Venmo payment went to. Approved rows stay in that conversation and go with its later questions; a new conversation starts without them. [P6](../CLAIMS.md#p6)

Each part is recorded before the gateway may send it, and a part that can't be recorded is never sent. You can read every part of your data that was sent in Settings › Chat, under Everything sent so far. [P7](../CLAIMS.md#p7) The rest of a request isn't listed as text: the gateway's fixed instructions and tool list show only as a fingerprint, on a Getting ready row; the request's settings aren't listed; and a conversation's earlier messages, Claude's replies among them, show as a count. Every member of the book can read the log, and no route in Steward changes or deletes it. [P17](../CLAIMS.md#p17)

## What never reaches Claude

- The names Steward holds, except in store rows a manager approves and in the gaps listed under [What the checks can miss](#what-the-checks-can-miss). A model on your gateway looks for other names and can miss one. [P4](../CLAIMS.md#p4)
- Your notes on transactions and accounts. [P3](../CLAIMS.md#p3)
- Account numbers. [P5](../CLAIMS.md#p5)
- The email addresses, phone numbers, street addresses and ID numbers Steward holds, apart from those gaps. Rules and a model on your gateway look for others and can miss one. [P11](../CLAIMS.md#p11)
- The link that connects Steward to SimpleFIN. None of the code behind Ask, its checks or the gateway reads it. [P13](../CLAIMS.md#p13)
- PDF statements and the summary of a saved plan. [P8](../CLAIMS.md#p8)
- Imported files, their names, and where a row came from. [P12](../CLAIMS.md#p12)

## What stays on your machines

- Steward connects only to the services you set up: SimpleFIN, your gateway, your categorizer, your mail server and your backup ping. [P1](../CLAIMS.md#p1)
- Steward's own code and pages send no telemetry: no analytics, crash reports or outside scripts. [P2](../CLAIMS.md#p2)
- Steward never connects to Claude itself. Only your gateway does. [P14](../CLAIMS.md#p14)
- The gateway is a program on your own hardware. It sees your question after Steward has made its exact replacements, and it runs its own checks before anything leaves.
- Categorizing is local. It uses your gateway's model, or your rules and Review. [P9](../CLAIMS.md#p9)
- Logs carry no amounts, notes, transaction descriptions or searches. Steward logs a request as its method, its route and its status. Neither Steward nor its HTTPS proxy logs a query string. [P10](../CLAIMS.md#p10)
- Emails Steward sends never show an account number. [P15](../CLAIMS.md#p15)

`compose.yml` can also run other programs beside Steward. This is what each of them contacts:

- **Tailscale** (the tailscale profile) talks to Tailscale's servers to connect your devices. Its own log upload to Tailscale is turned off in `compose.yml`, so Tailscale's support can't read those logs. Its HTTPS certificate puts your machine's tailnet name in public certificate logs.
- **The HTTPS proxy** (the domain profile) gets its certificate from Let's Encrypt, which puts your domain in public certificate logs. With `STEWARD_TLS=dns-cloudflare` it also calls Cloudflare's API and asks Cloudflare's DNS at 1.1.1.1. The lan profile's proxy makes its own certificate and contacts nothing.
- **Ollama** (the ollama profile) reads transaction descriptions, statement pages and the questions it turns into chat titles, for the gateway. It stays on a network that reaches the internet, because `ollama pull` downloads models over it.
- **The gateway** downloads its redaction model from Hugging Face at its first start, pinned to one commit, with Hugging Face's telemetry turned off. [P2](../CLAIMS.md#p2)

## The Sample book

The Sample book is made up. It never syncs with a bank, and nothing from it reaches Claude. Asking is refused in it before any call to the gateway. [S11](../CLAIMS.md#s11)

## What Steward replaces

Before a question leaves Steward, it replaces these by exact match:

- The names of the book's members, children and contacts, and in a parent's book the parent's, in full and each part of 3 letters or more. Each member's username and email too.
- Dates of birth saved in Profile, in the usual written forms.
- Account names, and the banks Steward connected to.
- The account numbers, phone numbers, emails and whole addresses saved in the inventory.
- Payees seen in the last 400 days.

A name made only of words that are also months, states or money words, such as August, isn't matched, because those words are common in questions. Everything else you type is left to the gateway's rules and model. [P4](../CLAIMS.md#p4) [P11](../CLAIMS.md#p11)

## What the checks can miss

The checks are rules and a model, and neither is perfect. These are the cases they can miss.

- A bare date with no birth word, such as "June 14, 1985". With a word like born or birthday beside it, the date is replaced. [P5](../CLAIMS.md#p5)
- An ID made of letters and 4 or fewer digits, such as `AB12CD34`. Steward lets up to 4 digits through, because ages, years and small counts need them. [P5](../CLAIMS.md#p5)
- An email written out in words, such as "tom at example dot com".
- A full name the book doesn't know, when the model doesn't recognize it.
- A name made of words that are also states, months or money words, such as "Virginia Roth" or a child called August, whether or not the book holds it. On its own, "June" could be a month or a person.
- A two-letter name, such as "Li", even of someone in the book.
- An address the book holds, typed without its unit, city or ZIP.
- A name the book keeps outside the list above, such as a reimburser, a set-aside or a payee last seen more than 400 days ago.
- Employers, schools, towns and other organizations you type. The model looks only for people, street addresses and dates of birth.
- A person's name as the payee in store rows a manager approves, such as the one a Zelle payment went to. [P6](../CLAIMS.md#p6)
- Anything you type into Claude Code. It goes to Anthropic without passing through Steward. See [Claude Code](../guides/gateway.md#advanced-claude-code).
- Digits typed on purpose in a way meant to get past the rules.

Don't type identifiers into Ask, even ones Steward holds: the exact pass covers only the list under [What Steward replaces](#what-steward-replaces), and the gateway's model and rules can miss the rest. [P4](../CLAIMS.md#p4) [P11](../CLAIMS.md#p11)

## Claude's own terms

What Anthropic does with the questions it receives is set by Anthropic's terms, not by Steward. Read the [commercial terms](https://www.anthropic.com/legal/commercial-terms) and the [privacy center](https://privacy.claude.com) for how your API key's traffic is handled.
