import { describe, expect, it } from 'vitest';
import { forgetGatewayName, gatewayName, gw, setGatewayName } from './gatewayName';

describe('the gateway name (spec 2026-11-05, section 7)', () => {
  it('is "the gateway" until /me names it, and capitalizes at a sentence start', () => {
    expect(gatewayName()).toBe('the gateway');
    expect(gw('{gateway} is answering')).toBe('The gateway is answering');
    expect(gw('Chat needs {gateway}, which is away. {gateway} may be asleep.')).toBe('Chat needs the gateway, which is away. The gateway may be asleep.');
  });
  it('takes the name /me sends, and falls back on an empty one', () => {
    setGatewayName('Otter-PC');
    expect(gw("{gateway}'s check took out 1 part")).toBe("Otter-PC's check took out 1 part");
    setGatewayName('  ');
    expect(gatewayName()).toBe('the gateway');
    setGatewayName('Zebra-Box');
    forgetGatewayName();
    expect(gatewayName()).toBe('the gateway');
  });
  it('never reads the name as a pattern', () => {
    setGatewayName('a$&b');
    expect(gw('Waiting for {gateway}')).toBe('Waiting for a$&b');
  });
});
