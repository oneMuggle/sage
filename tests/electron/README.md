# tests/electron/ — Sage 桌面端 E2E 测试

## 1. 架构总览

```
                     ┌────────────────────────────────────────┐
                     │  Playwright test runner (Node.js)      │
                     │  --project={electron-*}                │
                     └─────────────────┬──────────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
   ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
   │ tiers/stub/{smoke,   │  │ tiers/stub/deep      │  │ tiers/live/{boot,    │
   │ deep}                │  │ tiers/live/deep      │  │ deep}                │
   └──────────┬───────────┘  └──────────┬───────────┘  └──────────┬───────────┘
              ▼                         ▼                          ▼
   ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
   │ stub_backend.py      │  │ stub_backend.py      │  │ conda sage-backend   │
   │ (in-memory SQLite)   │  │ (in-memory SQLite)   │  │ (sqlite + LLM API)   │
   │ 无 conda、无 LLM     │  │ 无 conda、无 LLM     │  │ 需 conda + LLM key   │
   └──────────────────────┘  └──────────────────────┘  └──────────────────────┘
```

## 2. 目录结构

```
tests/electron/
├── README.md                          # 本文档
├── conftest.py                        # stub_backend() + real_backend() fixtures
├── _real_backend.py                   # RealBackend 子进程管理类
├── stub_backend.py                    # 入口：HTTP server + routing
├── stub_modules/                      # 按功能拆分的 stub handler
│   ├── common.py
│   ├── chat.py
│   ├── orchestration.py
│   ├── wiki.py
│   ├── memory.py
│   └── evolution.py
├── test_stub_backend.py               # ~45 个 stub unit case (pytest)
├── test_real_backend_fixture.py       # real_backend fixture 验证
├── fixtures/                          # seed JSON
└── tiers/
    ├── stub/smoke/                    # 5 spec × ~50 行（含 3 个平迁老 spec）
    ├── stub/deep/                     # 5 spec × ~300 行
    └── live/
        ├── boot-smoke/                # 3 spec（不调 LLM）
        └── deep/                      # 5 spec（含 1 个平迁，含 @nightly/@release tag）
```

## 3. 4 个开发阶段

| 阶段 | 命令 | 时长 | 后端 | LLM |
|---|---|---|---|---|
| 本地 dev loop | `npm run test:smoke` | 30-60s | stub | n/a |
| PR 门禁 | `npm run test:pr` | 5-10min | stub + real(no LLM) | no |
| Nightly | `npm run test:nightly` | 30-60min | real | yes (chat + memory only) |
| 手动/Release | `npm run test:release` | 60-120min | real | yes (all 5) |

## 4. 运行示例

```bash
# 开发期间快速验证
npm run test:smoke

# 提交 PR 前本地跑一遍（需要 conda sage-backend）
conda activate sage-backend && python backend/main.py &
npm run test:pr

# Nightly（需要 OPENAI_API_KEY）
OPENAI_API_KEY=sk-... npm run test:nightly

# 交互式调试 stub smoke（UI 模式）
npm run test:dev
```

## 5. 添加新 spec

### stub smoke（无 conda）
1. 在 `tests/electron/tiers/stub/smoke/<feature>.spec.ts` 新建文件
2. 用 `helpers/electron-launcher.ts` 起 stub + electron
3. 用 page 操作 + stub API 断言

### live deep（需 conda + LLM key）
1. 在 `tests/electron/tiers/live/deep/<feature>.spec.ts` 新建文件
2. 用 `{ tag: '@nightly' }` 或 `{ tag: '@release' }` 限定激活范围
3. spec body 中 `test.skip(true, ...)` 当 `OPENAI_API_KEY` 缺失

## 6. 故障排查

### stub 启动失败
- 检查 `/home/fz/anaconda3/envs/sage-backend/bin/python` 可执行
- 检查 `stub_backend.py` 没被其他进程占用
- 启动时会打印 `STUB_URL=http://127.0.0.1:<port>`，捕获失败要看 stderr

### real backend 启动失败
- `conda activate sage-backend && python backend/main.py` 手动跑一遍
- 端口冲突：`lsof -i :8765` 找占用进程
- LLM key 缺失：live-deep spec 自动 skip

### Electron 冷启动慢
- CI 上 `retries: 1`，spec 用 `beforeAll` 复用实例
- 本地 `npx playwright test --ui` 可视化调试
