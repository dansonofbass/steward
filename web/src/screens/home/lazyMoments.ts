import { lazyScreen } from '../../lib/lazyScreen';

// Phase 17: Home's and Profile's moments draw their lines from lib/lines.ts, which stays out of the initial bundle, so
// they load on demand in one small chunk (scripts/bundle-size.mjs: HomeMoments).
export const PaydayMoment = lazyScreen(() => import('./HomeMoments').then((m) => ({ default: m.PaydayMoment })));
export const HomeTree = lazyScreen(() => import('./HomeMoments').then((m) => ({ default: m.HomeTree })));
export const ProfileGrowth = lazyScreen(() => import('./HomeMoments').then((m) => ({ default: m.ProfileGrowth })));
export const GatewayBack = lazyScreen(() => import('./HomeMoments').then((m) => ({ default: m.GatewayBack })));
export const LazyBackgroundLine = lazyScreen(() => import('./BackgroundLine').then((m) => ({ default: m.BackgroundLine })));
