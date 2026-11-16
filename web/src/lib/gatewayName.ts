// Spec 2026-11-05, section 7: what Steward calls the gateway machine (STEWARD_GATEWAY_NAME, "the gateway" when unset).
// Copy says {gateway}; gw() puts the name in, capitalized where it starts a sentence. RequireAuth takes the name from
// each new /me answer before any screen renders, as it does the person's own switches; no screen before sign-in
// names the gateway.
export const DEFAULT_GATEWAY_NAME = 'the gateway';
let name = DEFAULT_GATEWAY_NAME;

export function setGatewayName(next: string | null | undefined): void { name = next?.trim() || DEFAULT_GATEWAY_NAME; }
export function forgetGatewayName(): void { name = DEFAULT_GATEWAY_NAME; }
export const gatewayName = (): string => name;

const AT_START = /(^|[.!?]\s+|\n\s*)\{gateway\}/g;

/** text with every {gateway} filled with the name, capitalized at the start of the text or of a sentence. */
export function gw(text: string): string {
  const cap = name.charAt(0).toUpperCase() + name.slice(1);
  return text.replace(AT_START, (_all, lead: string) => lead + cap).split('{gateway}').join(name);
}
