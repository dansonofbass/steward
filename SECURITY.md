# Security policy

## Reporting a problem

Report a vulnerability privately. Never open a public issue for one.

1. Use [private vulnerability reporting](https://github.com/steward-money/steward/security/advisories/new) on the Steward repository. This is the first choice.
2. If you cannot use GitHub, email security@stewardmoney.app.

Say what you found, which version or image it affects, and the steps to reproduce it. Do not include real financial data; a made-up vault is enough.

## What to expect

You get a first answer within 7 days. That is best effort: Steward is looked after by a small team. Fixes go into the next release.

Only the latest release is supported. If you run an older one, upgrade first (see [upgrading](docs/guides/upgrade.md)).

## What is in scope

The app, the gateway, the proxy image, the compose files and the release workflow.

Some things are out of scope by design, such as an administrator of the machine Steward runs on. The list is under [Out of scope](docs/explanations/threat-model.md#out-of-scope) in the threat model.

## Signed images

Every release image is signed with no stored key, and comes with an SBOM. [S8](docs/CLAIMS.md#s8) To check one before you run it, follow [verify the images](docs/guides/upgrade.md#verify-the-images).
