// Every e2e port in one place. STEWARD_E2E_BASE_PORT moves the whole set (8441-8443 by default; 8471 or 8481 when
// another run holds them). The live gateway on the dev machine holds 8430/8431: never use those.
// Tests must reach the servers of their own run: a hard-coded port talks to whatever else is listening there,
// such as a server left over from an earlier run, with that run's data.
// Read in Node (Playwright and its config); the web tsconfig has no Node types.
declare const process: { env: Record<string, string | undefined> };
const asked = process.env.STEWARD_E2E_BASE_PORT;
const base = Number(asked ?? 8441);
// The set is base..base+2 and base+100..base+102; none of them may be 8430 or 8431.
const all = [base, base + 1, base + 2, base + 100, base + 101, base + 102];
if (!Number.isInteger(base) || base < 1024 || base > 65000 || all.some((p) => p === 8430 || p === 8431)) {
  throw new Error(`STEWARD_E2E_BASE_PORT=${asked} is not a usable e2e port (never 8430/8431)`);
}

/** The demo household. */
export const DEMO_PORT = base;
/** The empty households for Set up Steward, one per Playwright project (onboarding ruling 15). */
export const EMPTY_PORT = { phone: base + 1, desktop: base + 2 } as const;
/** The fake gateway beside the demo server (web/e2e/server.sh: the demo port + 100). */
export const GATEWAY_PORT = DEMO_PORT + 100;

/** The demo vault's keeper (web/e2e/vault_keeper.py: the demo port + 102). POST /restore puts the seeded vault back. */
export const VAULT_PORT = DEMO_PORT + 102;
