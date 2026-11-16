import { lazyScreen } from '../lib/lazyScreen';

/** The panel (P26): its own chunk, loaded on the first open and preloaded when an Ask button is hovered or focused. */
export const AskPanel = lazyScreen(() => import('../screens/chat/panel/AskPanel'));
export const preloadAsk = (): void => { void AskPanel.preload().catch(() => {}); };
