import { beforeEach, describe, expect, it } from 'vitest';
import { forgetGatewayWatch, gatewayTurned } from './gateway';

const bg = (waiting: boolean, pending = 12) => ({ pending, done: 3, waiting });
beforeEach(forgetGatewayWatch);

describe('The gateway coming back (phase 17 spec 3.7)', () => {
  it('turns once: waiting, then catching up with rows to go', () => {
    expect(gatewayTurned('ours', bg(true))).toBe(false);
    expect(gatewayTurned('ours', bg(false))).toBe(true);
    expect(gatewayTurned('ours', bg(false))).toBe(false);
  });

  it("isn't back when there is nothing to catch up on, or when this visit never saw it away", () => {
    gatewayTurned('ours', bg(true));
    expect(gatewayTurned('ours', bg(false, 0))).toBe(false);
    expect(gatewayTurned('other', bg(false))).toBe(false);
  });

  it('each book is watched on its own', () => {
    gatewayTurned('ours', bg(true));
    expect(gatewayTurned('other', bg(false))).toBe(false);
    expect(gatewayTurned('ours', bg(false))).toBe(true);
  });
});
