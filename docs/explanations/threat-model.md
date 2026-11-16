# Threat model

This page says what Steward protects, who it protects it from, and where each protection stops. It is written so you can decide whether the protections fit your situation. Each check cites the claim that backs it in [the claims ledger](../CLAIMS.md).

## Assets

- **Your books.** Transactions, balances, notes, the plan, and the names of everyone in the household. This is the data that matters most.
- **The encryption key**, `steward.key`. Whoever has it and a copy of the books can read them.
- **Passwords and passkeys** for signing in, and the sessions they create.
- **The Anthropic API key**, held by the gateway. Whoever has it can spend your Anthropic credit.
- **The SimpleFIN link.** It lets whoever holds it read your bank data.
- **Uploaded files and PDF statements.** They contain account numbers and addresses.

## Who might attack

- **Someone on the internet.** This matters only if you choose to put Steward on a public address. Out of the box it answers only on the machine it runs on. [S13](../CLAIMS.md#s13)
- **A website open in a household member's browser** that tries to make the browser act on Steward.
- **Someone on your network or tailnet** who can reach Steward's port but is not a member.
- **A member of the household** who tries to see a book they do not belong to, or to change a book they can only read.
- **A hostile PDF or imported file.**
- **A copy of your backups or disk** in the wrong hands.
- **Claude, or Anthropic's systems, learning who you are** from the questions you ask.

## Trust boundaries

1. **Browser to Steward.** Every book route the browser uses checks the sign-in and whether the person belongs to that book. [S16](../CLAIMS.md#s16)
2. **Steward to the gateway.** Every gateway route but pairing answers only with Steward's pairing token. Pairing takes a one-time code, and Claude Code's route, once you turn it on, takes its own token; asked with the wrong method, that route says only "Use POST." [S17](../CLAIMS.md#s17) Steward sends the gateway typed data and your checked question. In the compose install the gateway publishes no port, and Steward reaches it on `gateway-private`, a network with no way out. [S12](../CLAIMS.md#s12) The gateway and Ollama also join `gateway-egress`, the way out to Claude and Hugging Face. On a machine of its own, the gateway listens only on Tailscale or 127.0.0.1. [S12](../CLAIMS.md#s12) Your tailnet's access controls should let only Steward reach port 8430.
3. **The gateway to Claude.** Steward never connects to Claude itself; only the gateway does. [P14](../CLAIMS.md#p14) Each part is recorded before the gateway may send it, so you can see every part of your data that was sent. [P7](../CLAIMS.md#p7)
4. **Steward to SimpleFIN.** Steward pulls bank data from SimpleFIN. Claude and the gateway never receive your SimpleFIN link. [P13](../CLAIMS.md#p13)
5. **Steward to the PDF reader.** The reader opens PDF statements in a sandbox, never unconfined. [S6](../CLAIMS.md#s6)

## What each check stops, and what it doesn't

| Check | What it stops | What it doesn't |
|---|---|---|
| Encrypted books. [S1](../CLAIMS.md#s1) | Someone who copies the data folder without the key. | A running machine with the key beside the data. Anyone who can read both can read the books. |
| The key on its own mount, kept out of backups. [S2](../CLAIMS.md#s2) | A stolen backup, which opens nothing alone. | Losing the key. Without it the books cannot be read by anyone, including you. |
| Writes only from Steward's pages. [S3](../CLAIMS.md#s3) | Another site making your browser change your data. | A request from something that is not a browser. |
| The page runs only Steward's code. [S4](../CLAIMS.md#s4) | Injected scripts and inline code. | A flaw in Steward's own code. |
| Per-device limits, and a lockout per account. [S5](../CLAIMS.md#s5) | Fast guessing of a password. | A device that is always behind one shared proxy address, which counts as one. The per-device limits are counted in memory, so a restart resets them. Anyone who can reach the sign-in page can lock an account's password sign-in for 15 minutes with 5 wrong tries, and the locked answer shows that the username exists. Passkeys still work. |
| The PDF sandbox. [S6](../CLAIMS.md#s6) | A hostile PDF reaching the network, other programs, or any file outside the reader's own runtime. The reader runs behind a system-call filter and a Landlock file wall, and opens a PDF only with both in place. | A host without both, such as a kernel older than 5.13. There, statements go to the gateway or wait instead of being opened unconfined. A taken-over reader can still learn whether a path outside its runtime exists, and its size, owner, permissions and times, but never what a file holds or where a link points. |
| A one-time setup link, no open sign-up. [S7](../CLAIMS.md#s7) | Someone else making the first account. | The link in the wrong hands during its 30 minutes. |
| Signed images and an SBOM. [S8](../CLAIMS.md#s8) | An image that did not come from the project's release build. | A flaw in a release that was built correctly. |
| The email password is never shown again. [S9](../CLAIMS.md#s9) | The password leaking through the app or its answers. | A mail server that you point it at and that is not yours. |
| A pairing code lasts 10 minutes and 5 tries. [S10](../CLAIMS.md#s10) | Guessing a code to pair a gateway. | Someone who sees the code while it is shown. |
| The Sample book. [S11](../CLAIMS.md#s11) | Made-up data reaching Claude or a bank. | Anything about your own books. This protects the made-up data only. |
| The gateway's listening addresses. [S12](../CLAIMS.md#s12) | The gateway being reachable from your network or the internet. | A machine that other people can already log in to. |
| Claude Code's door on the gateway is off unless you turn it on. [S15](../CLAIMS.md#s15) | Any program on the gateway machine reaching your figures through Claude Code by default. | Once it's on, anything that runs as you on that machine and can read Claude Code's settings. |
| Steward answers only on its own machine. [S13](../CLAIMS.md#s13) | Reaching Steward from the network by accident. | Whatever way in you add yourself. See [access](../guides/access.md). |
| A real install refuses a demo sign-in. [S14](../CLAIMS.md#s14) | Leaving a known demo password on a real install. | A weak password that you chose. |
| Quiet logs. [P10](../CLAIMS.md#p10) | Amounts, notes, transaction descriptions and searches written into the logs of Steward and its HTTPS proxy. | Any other program's logs, such as a proxy of your own. |
| Steward never calls Claude. [P14](../CLAIMS.md#p14) | A bug in Steward sending data to Claude directly. | The gateway doing so, which is its job. See [privacy](privacy.md) for what it sends and what the checks can miss. |

Encryption at rest does not help against a machine that is running, because the key must be available to open the books. Anyone with access to that machine as its administrator has what Steward has.

## Out of scope

Steward does not defend against an administrator of the machine it runs on, a compromised browser on a device you sign in from, or a household member who photographs their own screen. It does not make a public address safe: if you put Steward on the internet, you take on the work of keeping that address safe.

To report a problem in Steward, read [the security policy](../../SECURITY.md).
