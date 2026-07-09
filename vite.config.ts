/// <reference types="vitest" />
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Phase 1 (2026-06-13): Tauri → Electron migration.
  // - base: './' required for Electron file:// loading (relative paths)
  // - watch.ignored now excludes archive/ (was src-tauri/, archived)
  base: './',
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ['**/src-tauri/**', '**/archive/**', '**/dist-electron/**'],
    },
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
          'vendor-markdown': ['react-markdown', 'remark-gfm', 'react-syntax-highlighter'],
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
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    css: false,
    // Phase 4: exclude Playwright Electron smoke tests (run separately via
    // `npx playwright test tests/electron/smoke.spec.ts`, not Vitest).
    // Phase 6 (2026-06-27): also exclude ./e2e/ (wiki-folder-picker Playwright spec).
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/dist-electron/**',
      'tests/electron/**',
      'e2e/**',
    ],
  },
});
