# 日志系统基线修复 — 设计 spec

**日期:** 2026-08-12
**作者:** Claude (brainstorming 后)
**状态:** 设计已批准,待实施
**对应分支:** `feature/fix-logging-foundation`
**对应 PR:** TBD

## 背景

2026-08-12 对 `sage` 项目日志系统做了全面审计(详见对话历史),审计结论:

**Electron 主进程层** NDJSON 落盘(`<userData>/logs/sage-YYYY-MM-DD.ndjson`)、7 天清理、10MB 滚动、IPC 100 msg/s 限流、渲染进程 console 桥接主进程 — **是真正好用的基建**。前端白屏(`render-process-gone` / `did-fail-load`)、Electron 启动失败(`showStartupFailureDialog`)两类故障可 < 5 分钟定位。

**后端 Python 层** 写了等于没写:

- `backend/utils/logging.py:248` `setup_logging()` 定义完整、零调用者
- `backend/main.py:425-433` `uvicorn.run(...)` 缺这一行 → 后端根 logger 永远 WARNING 级别
- `setup_logging` 不调 → `LOG_FILE_MAX_DAYS=7` 自动清理、`LOG_DIR` 路径解析、文件 handler 全部不生效
- `electron/backendLauncher.ts:239-249` 只注入 `SAGE_USER_DATA_DIR` 不注入 `SAGE_LOG_DIR` → `sage doctor` 的 `log_dir_size` 检查路径与实际写日志路径不一致,packaged 模式下永远 INFO
- `electron/logger.ts:48` `CURRENT_LEVEL` 是模块加载时常量 → 用户在 Settings 改日志级别不生效

**链路串联差**:

- 后端日志格式(`backend/utils/logging.py:18`)只含 `trace_id`(来自 OTel span,无活跃 span 时填 `-`),没有 `session_id` 字段 → 不能 grep 串起整链
- `[REQ {request_id}]`(`backend/api/legacy_routes.py:1455`)和 `[HEX REQ {request_id}]`(`backend/api/hex_routes.py:140`)格式不统一

## 根因分类

- **"基座定义完整、零调用者"**:`setup_logging()`、`init_tracing()`、Storage/Artifacts/Export 的 logger
- **"路径不一致"**:Electron 注入的 env var 与后端路径解析、doctor 检查路径三方不串通
- **"运行时配置未真正生效"**:`CURRENT_LEVEL` 模块常量、`SAGE_LOG_LEVEL` 未注入 backend
- **"前端 store 失败不进 NDJSON"**:`store.ts` 4 个核心 action 失败仍走 `console.error`
- **"office 模块黑盒"**:刚合并的 office 模块 0 处 logger 调用

## 目标

让已有基建真正生效,使后端 500 / 日志级别切换 / doctor 日志检查 / 前端 store 失败 / office 调用 5 类场景的排障时间从 10-30 分钟降到 2-5 分钟。

## 非目标

- 不接入 OTel exporter(Jaeger/Tempo)— 属架构升级,需要服务依赖
- 不升级后端日志格式加入 `session_id` 字段 — 牵涉日志格式升级,影响所有下游 grep/解析
- 不接入 Sentry / Bugsnag — 隐私和服务端依赖
- 不改 `process.on('uncaughtException')` / `crashReporter` — 与 Electron 升级/打包系统一起做更稳
- 不重写 `setup_logging()` 本身 — 它已经写得够好,只是没人调
- 不改后端日志格式(`backend/utils/logging.py:18` 的 format string)— 同上

## 设计

### 修复 1:`backend/main.py` 启动前调 `setup_logging()`

**文件:** `backend/main.py`
**位置:** `uvicorn.run(...)` 之前(line 425 附近)
**改动:** +1 行

```python
from backend.utils.logging import setup_logging

setup_logging(level="INFO", json_format=True)
uvicorn.run(app, host='127.0.0.1', port=port, log_config=None)
```

**为何 `log_config=None`**:让 uvicorn 走根 logger(已被 `setup_logging` 配置),不再被 uvicorn 自家的 access log 格式覆盖。access log 仍会打(走 root logger),但格式与项目其他日志一致。

**入参选择**:`level="INFO"` 与 `DEFAULT_LOG_LEVEL`(logging.py:31)硬编码值一致;`json_format=True` 是 dev/Electron 通用选择,符合 NDJSON 消费。

### 修复 2:`electron/logger.ts` `CURRENT_LEVEL` 改为可运行时切换

**文件:** `electron/logger.ts:48`、`electron/ipc/logIpc.ts:96`
**改动:** ~5 行

**当前问题:** `const CURRENT_LEVEL = resolveLevel()` 在模块加载时冻结。`logIpc.setLevel` 只改了 `process.env`,不重新读常量。

**方案:** 改为 module-level mutable + 导出 setter:

```typescript
// logger.ts
let CURRENT_LEVEL: LogLevel = (process.env.SAGE_LOG_LEVEL ?? 'info') as LogLevel;
export function setLogLevel(level: LogLevel): void {
  CURRENT_LEVEL = level;
}
```

```typescript
// logIpc.ts:setLevel (line 96)
setLogLevel(level as LogLevel);
process.env.SAGE_LOG_LEVEL = level;  // 保持兼容(后端会读)
```

**取舍**:选 "模块可变 + setter" 而非 "每次 log() 重新 read env" — 后者每次日志都做 env 读取,虽有缓存但增加复杂度。setter 只在用户改设置时调一次。

### 修复 3:`electron/backendLauncher.ts` 注入 `SAGE_LOG_LEVEL`

**文件:** `electron/backendLauncher.ts:239-249`
**改动:** +1 行

```typescript
const extraEnv = {
  ...process.env,
  SAGE_USER_DATA_DIR: userDataDir,
  SAGE_LOG_LEVEL: process.env.SAGE_LOG_LEVEL ?? 'info',  // 新增
};
```

**为何**:让用户在前端 Settings 改的级别对 backend Python 日志生效(虽然 `setup_logging()` 还没读这个 env var,但保留向后兼容)。

**取舍**:不注入 `SAGE_LOG_DIR` — 后端 `setup_logging()` 通过 `SAGE_USER_DATA_DIR` 自动推断(见 `backend/utils/logging.py:121-123`),已经能写对位置。

### 修复 4:`backend/cli/checks/log_dir_size.py` 兼容 `SAGE_USER_DATA_DIR`

**文件:** `backend/cli/checks/log_dir_size.py:23-30`
**改动:** ~3 行

**当前问题:** 只认 `$SAGE_LOG_DIR` 或 `backend/logs/`,不认 `SAGE_USER_DATA_DIR`。packaged Electron 模式下 backend 实际写 `<userData>/logs/`,doctor 永远 INFO。

**方案:** 在判定目录路径时优先级改为:

```python
import os
log_dir = (
    os.environ.get("SAGE_LOG_DIR")
    or (os.environ.get("SAGE_USER_DATA_DIR") and os.path.join(os.environ["SAGE_USER_DATA_DIR"], "logs"))
    or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
)
```

**取舍**:不重写整个 check 逻辑 — 只把路径判定一处改对。

### 修复 5:`src/shared/lib/store.ts` 4 处 console.error → clientLogger.error

**文件:** `src/shared/lib/store.ts`
**位置:** line 93、113、128、139
**改动:** +4 import + 4 method body 修改

**当前:**
```typescript
} catch (err) {
  console.error('[store] loadSessions failed', err);
}
```

**改为:**
```typescript
} catch (err) {
  clientLogger.error('store.loadSessions failed', { error: String(err) });
}
```

**为什么是 clientLogger 不是 logger**:`src/shared/log/client.ts` 走 IPC 持久化到 NDJSON(`electron/logger.ts`),`src/shared/lib/logger.ts` 是 dev-only console 兜底。生产排障要看 NDJSON,所以必须用 clientLogger。

**4 处逐条**:
- `createSession` (line ~93)
- `loadSessions` (line ~113)
- `deleteSession` (line ~128)
- `loadMessages` (line ~139)

### 修复 6:`backend/office/*.py` 12 个文件补 `logger = logging.getLogger(__name__)`

**文件:** `backend/office/*.py`(12 个 .py 文件,详见修复记录)
**改动:** 每个文件 +1 行(import 已存在则跳过;不存在则补 `import logging`)

```python
import logging
logger = logging.getLogger(__name__)
```

**取舍**:选 "每个文件 `getLogger(__name__)`"(与 `backend/api/chat_routes.py`、`backend/skills/registry.py` 等 200+ 处现有模式一致),不引入 `office/__init__.py` 的 `get_logger()` 统一收口。

**放置位置**:每个文件顶部,import 区下方。

## 不在范围内(明确)

下列问题本次不处理,但已在审计中记录:

| # | 问题 | 后续处理建议 |
|---|---|---|
| A | `[REQ {request_id}]` 和 `[HEX REQ {request_id}]` 格式不统一 | 后续 docs/superpowers/ideas/ 暂存 |
| B | OTel trace_id 仅在有 span 时填,无活跃 span 时填 `-` | OTel exporter 接入时一起做 |
| C | 后端日志格式无 `session_id` 字段 | session 串联基建专项 PR |
| D | backend stdout 走 debug 级别(Uvicorn access log 看不见) | 与 #2 联动:用户切 debug 后能看见 |
| E | Electron 主进程缺 `uncaughtException` / `crashReporter` | 与 Electron 升级/打包系统变更一起做 |
| F | `electron/logger.ts:91` 与 `electron/logPaths.ts:20` 两处写日志路径轻微冗余 | 风险评估后再处理 |

## 风险评估

| 修复 | 风险 | 缓解 |
|---|---|---|
| #1 | 后端日志格式变化(uvicorn 默认 → 项目自定义) | 排障脚本需 grep 适配;文档归档时说明 |
| #2 | `setLogLevel` 未被所有 `logIpc.ts` 调用点引用 | review 时确认所有 setLevel 调用都走 setter |
| #3 | env 注入冲突(Windows / macOS / Linux userData 路径格式) | SAGE_LOG_LEVEL 是字符串,无路径风险 |
| #4 | doctor 检查改路径后旧日志不计入 size | 旧日志迁移到新路径自动重新计数;无需手动 |
| #5 | clientLogger 与 store 循环 import | store 已 import 其他 shared/* 模块,client.ts 不依赖 store,无循环风险 |
| #6 | office logger 命名冲突 | `getLogger(__name__)` 用模块全路径,无冲突 |

## 依赖

- 无新增 Python / npm 包
- 无需 schema 迁移
- 无需 OTel exporter

## 实施步骤(预览)

按 feature-branch-workflow 规则:

1. `git switch -c feature/fix-logging-foundation`
2. 修复 #1-#6 按顺序 commit(每个 fix 一个 commit,便于 review)
3. 本地验证:`python backend/main.py` 启动后,grep `backend/logs/sage-*.ndjson` 应有 INFO 行;`./sage doctor --json` 的 `log_dir_size` 应 OK
4. `git push -u origin feature/fix-logging-foundation`
5. `gh pr create --title "fix: 日志系统基线修复 — 让已有基建真正生效 (#1-#6)" --body "..."`
6. CI 绿后等用户 merge

## 验收标准

- [ ] `backend/main.py` 启动后,`backend/logs/sage-YYYY-MM-DD.ndjson` 存在且含 INFO 级别行(非空)
- [ ] `electron/dev` 模式 UI 改日志级别后,新的 NDJSON 行使用新级别
- [ ] `electron/dev` 模式 UI 改日志级别后,backend Python 日志(若 SAGE_LOG_LEVEL 透传)也使用新级别
- [ ] `sage doctor --json` 的 `log_dir_size` 在 packaged Electron 模式下能读到真实日志目录大小
- [ ] 触发 store 的 4 个失败路径(session 创建失败/列表加载失败/删除失败/消息加载失败),NDJSON 中能找到对应日志
- [ ] office 模块任意函数被调用,NDJSON 中能找到对应日志
- [ ] 现有 pytest + vitest 全绿(以 CI 为准,不硬编码数字)
- [ ] 无新 console.error 散落到生产代码

## 文档归档

不新增章节,合并入现有文档:

- `docs/technical/29-electron-logging.md` 末尾加 §修复记录,记录 #2 + #3
- `docs/technical/41-sage-doctor.md` 加 §日志路径优先级段落,记录 #4
- `docs/technical/16-observability.md` 不动(本次未涉及 OTel)

## 后续项

待办沉淀到 `docs/superpowers/ideas/`:

- `2026-08-12-logging-foundation-followups.md` — A/B/C/D/E/F 六项的后续处理思路