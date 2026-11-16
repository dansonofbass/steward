import { act, render, screen } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { TEST_NOW, useFakeTimers } from './test-clock';

function Late({ ms }: { ms: number }) {
  const [shown, setShown] = useState(false);
  useEffect(() => { const id = setTimeout(() => setShown(true), ms); return () => clearTimeout(id); }, [ms]);
  return shown ? <p>late</p> : null;
}

describe('Testing Library under fake timers (flaky-test audit S3)', () => {
  it('findBy advances fake time itself, so a timer inside its ceiling is found with no real waiting', async () => {
    useFakeTimers();
    render(<Late ms={900} />);
    expect(await screen.findByText('late')).toBeInTheDocument();
  });

  it('its ceiling is fake time: past it the timer is not found, however busy the machine is', async () => {
    useFakeTimers();
    render(<Late ms={5000} />);
    await expect(screen.findByText('late')).rejects.toThrow();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.getByText('late')).toBeInTheDocument();
  });

  it('keeps the frozen date when it fakes the timers', () => {
    expect(Date.now()).toBe(TEST_NOW.getTime());
    useFakeTimers();
    expect(Date.now()).toBe(TEST_NOW.getTime());
  });
});
