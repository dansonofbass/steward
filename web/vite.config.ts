import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { preloadFonts } from './scripts/preload-fonts';

export default defineConfig({
  plugins: [react(), preloadFonts()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8420' } },
  build: { outDir: 'dist', sourcemap: false, target: 'es2022' },
  test: {
    environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'], include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // Half the cores (flaky-test audit S6): the suite shares the machine with the gateway and agents, and a suite that
    // starves its own workers turns its ceilings into flakes.
    pool: 'forks', minWorkers: 1, maxWorkers: '50%',
    // The ceilings, written down (Vitest's defaults; S5): a test or hook that hangs fails here.
    testTimeout: 5_000, hookTimeout: 10_000,
  },
});
