import { lazy, type ComponentType, type LazyExoticComponent } from 'react';

type Loaded<T> = { default: T };
type Preload = () => Promise<unknown>;

const preloads = new Set<Preload>();

/** A thenable React.lazy can read at once. React.lazy calls then() and checks the result before it suspends, so a
 *  module that is already loaded renders on its first render instead of suspending. */
function loadedNow<T>(value: T): Promise<T> {
  const thenable = {
    status: 'fulfilled' as const,
    value,
    then(onFulfilled?: (v: T) => unknown) { onFulfilled?.(value); return thenable; },
  };
  return thenable as unknown as Promise<T>;
}

/** React.lazy, plus preload(). In the app it is React.lazy: the chunk loads on the first render, once, and a chunk that
 *  fails to load fails the same way. Tests preload every screen first (test-setup.ts), so no findBy races a chunk
 *  being transformed on a busy machine (flaky-test audit S1). Pass the import() itself, so Vite still splits it. */
export function lazyScreen<T extends ComponentType<any>>(
  load: () => Promise<Loaded<T>>,
): LazyExoticComponent<T> & { preload: () => Promise<Loaded<T>> } {
  let loaded: Loaded<T> | undefined;
  let pending: Promise<Loaded<T>> | undefined;
  const preload = () => (pending ??= load().then((m) => { loaded = m; return m; }));
  preloads.add(preload);
  return Object.assign(lazy(() => (loaded ? loadedNow(loaded) : preload())), { preload });
}

/** Loads every lazy screen registered so far, and any that a loaded module registers in turn (a screen's own lazy
 *  parts). Tests only: the app never calls it. */
export async function preloadAllScreens(): Promise<void> {
  const done = new Set<Preload>();
  for (let next = [...preloads]; next.length > 0; next = [...preloads].filter((p) => !done.has(p))) {
    next.forEach((p) => done.add(p));
    await Promise.all(next.map((p) => p()));
  }
}
