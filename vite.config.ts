/// <reference types="vitest" />
import { createRequire } from 'node:module';

import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 读 package.json 拿真实版本号，注入为编译期常量供 UI 展示（sidebar 页脚）。
// 用 createRequire 而非 `import pkg from './package.json'`：后者会把整个
// package.json（含 devDependencies）纳入模块图。
const pkg = createRequire(import.meta.url)('./package.json') as { version: string };

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  // Phase 1 (2026-06-13): Tauri → Electron migration.
  // - base: './' required for Electron file:// loading (relative paths)
  // - watch.ignored now excludes archive/ (was src-tauri/, archived)
  base: './',
  clearScreen: false,
  server: {
    // Keep the development server and Vitest UI on loopback only. Do not
    // expose source files or the module transformer on a shared network.
    host: '127.0.0.1',
    // Allow port override via env so multiple worktrees can run side-by-side
    // (see scripts/worktree.sh + docs/technical/47-git-worktree-workflow.md).
    // Default 1420 preserves single-worktree behavior.
    port: Number(process.env.VITE_DEV_PORT ?? 1420),
    // Fail fast if the (potentially-overridden) port is taken; the worktree
    // helper writes a unique port into .env.local per worktree.
    strictPort: true,
    watch: {
      ignored: ['**/src-tauri/**', '**/archive/**', '**/dist-electron/**'],
    },
  },
  preview: {
    // Preview serves the built renderer; keep it local for the same reason.
    host: '127.0.0.1',
  },
  build: {
    target: 'es2020',
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-query': ['@tanstack/react-query'],
          'vendor-ui': ['@headlessui/react', 'sonner', 'lucide-react'],
          'vendor-flow': ['@xyflow/react'],
          'vendor-markdown': ['react-markdown', 'remark-gfm'],
          'vendor-state': ['zustand'],
        },
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  optimizeDeps: {
    // Exclude windowControlsClient from pre-bundling to prevent
    // CommonJS transformation that breaks ES module imports in
    // Electron renderer process
    exclude: ['src/shared/api/windowControlsClient.ts'],
    include: [],
  },
  esbuild: {
    // Force ES module format to prevent CommonJS transformation
    // that breaks ES module imports in Electron renderer process
    format: 'esm',
  },
  test: {
    // Vitest UI/API is a separate server from Vite's dev server.
    api: {
      host: '127.0.0.1',
    },
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    css: false,
    // Phase 4: exclude Playwright Electron smoke tests (run separately via
    // `npx playwright test tests/electron/smoke.spec.ts`, not Vitest).
    // Phase 6 (2026-06-27): also exclude ./e2e/ (wiki-folder-picker Playwright spec).
    // Phase 7 (2026-08-09): also exclude .claude/worktrees/** — local parallel
    // agent worktrees contain full src copies; without this Vitest discovers
    // duplicate test files and runs each suite 7+ times with cross-environment
    // state pollution (see fix/security-perf-quickwins).
    exclude: [
      '**/node_modules/**',
      '**/.claude/**',
      '**/dist/**',
      '**/dist-electron/**',
      'tests/electron/**',
      'tests/e2e/**',
      'e2e/**',
    ],
  },
});
