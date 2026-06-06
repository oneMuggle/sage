// eslint.config.js
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import importPlugin from 'eslint-plugin-import';
import globals from 'globals';

export default [
  { ignores: ['dist', 'node_modules', 'src-tauri', 'coverage', '*.config.{js,ts,mjs}'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['scripts/**/*.{js,mjs,cjs,ts,mts,cts}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.node, ...globals.es2022 },
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.es2022 },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      import: importPlugin,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'import/order': [
        'error',
        {
          groups: ['builtin', 'external', 'internal', 'parent', 'sibling', 'index'],
          'newlines-between': 'always',
          alphabetize: { order: 'asc' },
        },
      ],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      // FSD 边界规则（PG1.13 启用为 error — 任何违规将失败 build）
      // 层级（自顶向下）：app > processes > pages > widgets > features > entities > shared
      // 下层不可 import 上层，但可 import 自身 + 下层。
      'import/no-restricted-paths': [
        'error',
        {
          zones: [
            // pages 不可 import app / processes
            { target: './src/pages', from: './src/app' },
            { target: './src/pages', from: './src/processes' },
            // widgets 不可 import pages / app / processes
            {
              target: './src/widgets',
              from: ['./src/pages', './src/app', './src/processes'],
            },
            // features 不可 import widgets / pages / app / processes
            {
              target: './src/features',
              from: ['./src/widgets', './src/pages', './src/app', './src/processes'],
            },
            // entities 不可 import features / widgets / pages / app / processes
            {
              target: './src/entities',
              from: [
                './src/features',
                './src/widgets',
                './src/pages',
                './src/app',
                './src/processes',
              ],
            },
            // shared 是最底层 — 不可 import 任何上层
            {
              target: './src/shared',
              from: [
                './src/entities',
                './src/features',
                './src/widgets',
                './src/pages',
                './src/app',
                './src/processes',
              ],
            },
          ],
        },
      ],
    },
  },
];
