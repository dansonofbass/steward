import { render, screen } from '@testing-library/react';
import { Suspense, type ComponentType } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { lazyScreen, preloadAllScreens } from './lazyScreen';

const Hello = () => <p>hello</p>;
const shown = (C: ComponentType) => render(<Suspense fallback={<p>loading</p>}><C /></Suspense>);

describe('lazyScreen (flaky-test audit S1)', () => {
  it('in the app, loads on the first render behind Suspense, as React.lazy does, and only once', async () => {
    const load = vi.fn(async () => ({ default: Hello }));
    const C = lazyScreen(load);
    expect(load).not.toHaveBeenCalled();
    shown(C);
    expect(screen.getByText('loading')).toBeInTheDocument();
    expect(await screen.findByText('hello')).toBeInTheDocument();
    shown(C);
    expect(screen.getAllByText('hello')).toHaveLength(2);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('once preloaded, renders on the first render with no fallback at all', async () => {
    const load = vi.fn(async () => ({ default: Hello }));
    const C = lazyScreen(load);
    await C.preload();
    shown(C);
    expect(screen.getByText('hello')).toBeInTheDocument();
    expect(screen.queryByText('loading')).toBeNull();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('preloadAllScreens loads every screen, and the lazy parts a screen registers as it loads', async () => {
    let inner: ReturnType<typeof lazyScreen<typeof Hello>> | undefined;
    const outer = lazyScreen(async () => {
      inner = lazyScreen(async () => ({ default: Hello }));
      return { default: Hello };
    });
    await preloadAllScreens();
    shown(outer);
    shown(inner!);
    expect(screen.getAllByText('hello')).toHaveLength(2);
    expect(screen.queryByText('loading')).toBeNull();
  });

  // Last in the file: its failing load stays registered.
  it('a load that fails fails the preload, so a broken import stops the file instead of hiding', async () => {
    const C = lazyScreen(() => Promise.reject(new Error('Failed to fetch dynamically imported module')));
    await expect(C.preload()).rejects.toThrow('Failed to fetch');
  });
});
