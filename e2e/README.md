# E2E Tests

Unified E2E test directory (A3 from OpenWorker).

## Structure

```
e2e/
├── hermetic/      # 完全脱网，mock backend
│   ├── navigation-history.e2e.ts
│   ├── settings-schema-canonicalization.e2e.ts
│   └── welcome-screen.e2e.ts
├── live/          # 真实后端 (smoke only)
│   ├── sidebar-skills-nav.spec.ts
│   ├── wiki-chat-stream.spec.ts
│   ├── wiki-folder-picker.spec.ts
│   └── wiki-ingest-stream.spec.ts
└── electron/      # Electron 特有测试
    ├── skillmd-compliance.spec.ts
    └── smoke.spec.ts
```

## Categories

### hermetic/

完全脱网测试，使用 mock backend。每次 push 都跑，不依赖真实 LLM API。

```bash
npm run test:e2e:hermetic
```

### live/

需要真实后端的 smoke 测试。只在 main/release 分支跑，避免 CI 因 LLM API 抖动而红。

```bash
npm run test:e2e:live
```

### electron/

Electron 特有测试（IPC bridge、打包等）。

```bash
npm run test:e2e:electron
```

## Migration Notes

- 旧目录: `tests/e2e/`, `tests/electron/`, `e2e/`
- 新目录: `e2e/hermetic/`, `e2e/live/`, `e2e/electron/`
- Playwright config 已更新为 3 个 project

From OpenWorker's hermetic E2E pattern (60+ specs with mocked /v1 + WebSocket).
