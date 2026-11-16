import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadFocus, preloadFocusWhenIdle } from './load';

afterEach(() => { vi.unstubAllGlobals(); });

describe('loading the Focus chunk (review focus P26)', () => {
  it("a chunk that can't load becomes Missing, which hands Review back to the list", async () => {
    const { default: Missing } = await loadFocus(() => Promise.reject(new Error('gone')));
    const onMissing = vi.fn();
    render(<Missing rows={[]} chips={[]} today={new Date()} back={null} onBegin={() => ''} onDone={() => {}} onFail={() => {}} onNote={() => {}} onMissing={onMissing} />);
    expect(onMissing).toHaveBeenCalledOnce();
  });

  it('preloads when the browser is idle, and can be called off', () => {
    const idle = vi.fn((_cb: () => void) => 7);
    const cancel = vi.fn();
    vi.stubGlobal('requestIdleCallback', idle);
    vi.stubGlobal('cancelIdleCallback', cancel);
    const stop = preloadFocusWhenIdle();
    expect(idle).toHaveBeenCalledOnce();
    stop();
    expect(cancel).toHaveBeenCalledWith(7);
  });
});
