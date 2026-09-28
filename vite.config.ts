/// <reference types="vitest" />
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';

import { defineConfig, type Plugin } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 读 package.json 拿真实版本号，注入为编译期常量供 UI 展示（sidebar 页脚）。
// 用 createRequire 而非 `import pkg from './package.json'`：后者会把整个
// package.json（含 devDependencies）纳入模块图。
const pkg = createRequire(import.meta.url)('./package.json') as { version: string };

// S1 (P3 安全批次): 仅生产构建向 index.html 注入 CSP meta。
//
// 背景: 生产渲染层走 file:// 加载, 页面渲染 markdown/KaTeX/Shiki 等不可
// 信内容, 此前无 CSP —— 注入脚本后没有第二道防线。dev 不注入 (Vite HMR
// 与 React refresh 需要宽松策略), 生产产物由 e2e smoke 验证。
//
// 策略说明:
// - file:// 页面里 'self' 不匹配 file: 子资源, 必须显式列 file:。
// - script-src 的 'sha256-*' 由构建时对 index.html 里现存内联脚本
//   (主题 boot 脚本) 逐个计算 —— 以后增删内联脚本无需手工维护哈希。
// - img-src 放行 http(s): 避免 markdown 远程图片回归。
// - connect-src: 生产渲染层经 IPC relay 访问后端, 不应有直连; 保留
//   loopback http/ws 以防未知直连路径静默破裂, 收紧留给后续评审。
function cspInjectionPlugin(): Plugin {
  return {
    name: 'sage:csp-injection',
    apply: 'build',
    transformIndexHtml(html) {
      const hashes: string[] = [];
      const inlineScript = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g;
      let m: RegExpExecArray | null;
      while ((m = inlineScript.exec(html)) !== null) {
        const digest = createHash('sha256').update(m[1]).digest('base64');
        hashes.push(`'sha256-${digest}'`);
      }
      const csp = [
        "default-src 'self' file:",
        `script-src 'self' file: ${hashes.join(' ')}`.trim(),
        "style-src 'self' file: 'unsafe-inline'",
        "img-src 'self' file: data: blob: https: http:",
        "font-src 'self' file: data:",
        "connect-src 'self' file: ws://localhost:* ws://127.0.0.1:* http://127.0.0.1:* http://localhost:*",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
      ].join('; ');
      return html.replace(
        '<head>',
        `<head>\n    <meta http-equiv="Content-Security-Policy" content="${csp}">`,
      );
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), cspInjectionPlugin()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  // Phase 1 (2026-06-13): Tauri → Electron migration.
  // - base: './' required for Electron file:// loading (relative paths)
  // - watch.ignored now excludes archive/ (was src-tauri/, archived)
  base: './',
  resolve: {
    // CRITICAL: dedupe react/react-dom so ReactDOM reads the SAME React
    // instance as React. Without this, ESM module resolution can produce
    // two different module records for `react` and `react-dom`, and
    // ReactDOM's __SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED
    // check fails (returns undefined) → TypeError → white screen.
    // Symptom: `Cannot read properties of undefined (reading
    // '__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED')` in
    // vendor-react-*.js line ~17, with rootChildren=0 (React never
    // initialized). v0.4.5-alpha.17 logs showed exactly this.
    dedupe: ['react', 'react-dom', 'react-dom/client'],
  },
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
    // Proxy /api requests to backend in dev mode.
    // Backend port can be overridden via PYTHON_BACKEND_PORT env var.
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${process.env.PYTHON_BACKEND_PORT ?? 8765}`,
        changeOrigin: true,
      },
    },
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
    resolve: {
      // CRITICAL: dedupe react/react-dom so ReactDOM reads the SAME React
      // instance as React. Without this, ESM module resolution can produce
      // two different module records for `react` and `react-dom`, and
      // ReactDOM's __SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED
      // check fails (returns undefined) → TypeError → white screen.
      // Symptom: `Cannot read properties of undefined (reading
      // '__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED')` in
      // vendor-react-*.js line ~17, with rootChildren=0 (React never
      // initialized).
      dedupe: ['react', 'react-dom', 'react-dom/client'],
    },
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
    // 覆盖率棘轮门禁（win7 2026-09-28 随 main #1784 引入）：阈值只防"大幅
    // 回退"，不为凑数写浅测试；后续覆盖率提升时同步上调基线。
    // 本分支此前**完全没有** coverage 块，阈值直接按本分支实测定（见下）。
    //
    // 2026-09-28 (P0-3) 口径修正：此前**没有** coverage.exclude，vendored
    // 第三方代码与独立 package 全部计入分母 —— 实测 5267 条语句（占 6.9%）
    // 来自下列文件，任何渲染层单测都不可能覆盖：
    //   - extension/wiki-clipper/lib/{readability,turndown}.js  第三方 vendored
    //   - backend/.../export_assets/vendor/highlight.min.js     压缩过的 hljs
    //   - packages/drawio-mcp-server/**                          独立 MCP 包
    // 依据：package.json 的 lint 已经用 --ignore-pattern 排除了
    // extension/** 与 backend/**/export_assets —— 覆盖率口径与 lint 口径对齐，
    // 不是为了抬高数字而挑软柿子。artifacts/ 已有 3 个测试文件，故不排除。
    coverage: {
      provider: 'v8',
      // v8 provider 一旦显式指定 exclude 就不再套用默认值，需重列。
      exclude: [
        '**/node_modules/**',
        '**/dist/**',
        '**/dist-electron/**',
        '**/.claude/**',
        '**/.worktrees/**',
        // vendored 第三方 + 独立 package（见上方依据）
        'extension/**',
        'backend/**/export_assets/**',
        'packages/**',
      ],
      thresholds: {
        // 2026-09-28 排除 vendored 后**本分支**实测（426 文件 / 3102 例）：
        // stmts 68.32 / branch 80.72 / funcs 65.61 / lines 68.32。
        //
        // 数值与 main 的 69.79/81.07/67.33/69.79 不同：win7 前端套件比 main
        // 少 256 例（3102 vs 3358），functions 尤其低。阈值必须按本分支实测
        // 定 —— funcs 若照抄 main 的 65，本分支只剩 0.61pt 余量，一次与代码
        // 无关的性能波动就会红 CI。
        //
        // 定 67/79/64/67，各自留 1.3 / 1.7 / 1.6 / 1.3pt 余量，与 main
        // 「留 ~2pt、只防大幅回退」的棘轮意图一致。
        statements: 67,
        branches: 79,
        functions: 64,
        lines: 67,
      },
    },
    // Phase 4: exclude Playwright Electron smoke tests (run separately via
    // `npx playwright test tests/electron/smoke.spec.ts`, not Vitest).
    // Phase 6 (2026-06-27): also exclude ./e2e/ (wiki-folder-picker Playwright spec).
    // Phase 7 (2026-08-09): also exclude .claude/worktrees/** — local parallel
    // agent worktrees contain full src copies; without this Vitest discovers
    // duplicate test files and runs each suite 7+ times with cross-environment
    // state pollution (see fix/security-perf-quickwins).
    // 2026-09-15: also exclude .worktrees/** (project-root git worktrees).
    exclude: [
      '**/node_modules/**',
      '**/.claude/**',
      '**/.worktrees/**',
      '**/dist/**',
      '**/dist-electron/**',
      'tests/electron/**',
      'tests/e2e/**',
      'e2e/**',
    ],
  },
});
