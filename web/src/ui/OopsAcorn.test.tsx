import { waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { wrapBook } from '../test-utils';
import { OopsAcorn } from './OopsAcorn';

const fx = vi.hoisted(() => ({ acorn: vi.fn(() => () => {}) }));
vi.mock('../celebrate/celebrate', () => fx);
afterEach(() => { vi.clearAllMocks(); });

describe("the oops face (phase 17 spec 3.5 row 2, Steward's own hiccups)", () => {
  it('winces once, with no sound', async () => {
    wrapBook(<OopsAcorn />);
    expect(document.querySelector('svg.acorn')).toHaveAttribute('data-face', 'oops');
    await waitFor(() => expect(fx.acorn).toHaveBeenCalledWith(expect.objectContaining({ motion: 'wince', sound: false })));
  });

  it('a parent book never shows it', () => {
    wrapBook(<OopsAcorn />, { kind: 'parent' });
    expect(document.querySelector('svg.acorn')).toBeNull();
  });
});
