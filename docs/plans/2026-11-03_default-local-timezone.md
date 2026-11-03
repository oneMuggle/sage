# 时区优化：默认本地时区，失败回退北京时间

**日期**：2026-11-03
**分支**：`feat/default-local-timezone`
**状态**：实施完成，待归档

## 背景与目标

当前 Sage 项目时间处理存在以下问题：

1. **日志时区默认 UTC**：用户看到的日志时间与本地时间不一致，需要手动配置
2. **API 时间格式不一致**：趋势图等接口返回 naive datetime（无时区信息），前端无法判断时区
3. **前端时间格式化分散**：10+ 个独立的 `formatTime`/`formatDate` 函数，输入单位不统一（秒/毫秒）
4. **使用了已弃用 API**：`datetime.utcnow()` 在 Python 3.12+ 会产生 deprecation warning

**目标**：
- **显示层**：默认本地时区，获取失败回退北京时间（Asia/Shanghai，固定 +08:00 兜底）
- **存储层**：保持 UTC epoch / ISO 存储不变，仅在读取与展示时转换
- **一致性**：日志、API 趋势、定时任务、前端渲染共用同一套解析链

## 时区解析链（`backend/utils/timezones.py`，新建）

| 输入 | 结果 |
|------|------|
| `'local'` | `tzlocal.get_localzone()` → `astimezone()` 当前偏移 → 固定 +08:00 |
| `'UTC'` / 空串 / `None` | `datetime.timezone.utc` |
| IANA 名（如 `Asia/Shanghai`） | `ZoneInfo(name)` → 固定 +08:00 |
| 非法 IANA | 固定 +08:00 |

辅助函数：
- `local_now()` / `utc_now()` —— 均返回 **timezone-aware** datetime
- `ensure_utc(dt)` —— naive 视为 UTC 补时区，aware 原样返回（读取历史数据用）

## 涉及的文件与模块

### 后端（Python）
1. `backend/utils/timezones.py`（新建）— 时区解析工具
2. `backend/utils/logging.py` — 日志时区默认 `local`，改走 `resolve_timezone`
3. `backend/api/usage_routes.py` — 趋势桶起点改用 `local_now()`，ts 输出带偏移 ISO
4. `backend/domain/autonomous_goals.py` — `utcnow()` → `utc_now()`；`TimeWindow.timezone` 默认 `local`；`from_dict` 走 `ensure_utc`
5. `backend/data/goal_repository.py` — 读取行时 `ensure_utc`
6. `backend/services/goal_service.py` / `backend/services/time_window_manager.py` — 时间窗口用 aware 本地时间，预算做差 `ensure_utc` 归一
7. `backend/services/scheduler.py` — `BackgroundScheduler(timezone=local_timezone())`
8. `backend/main.py` — `SAGE_LOG_TIMEZONE` 默认值 `local`

### Electron（TypeScript）
1. `electron/logTimezone.ts` — 缺失/损坏/空值默认 `'local'`
2. `electron/backendLauncher.ts` / `electron/main.ts` / `electron/logger.ts` — 默认 `'local'`

### 前端（TypeScript）
1. `src/shared/lib/timeFormatter.ts`（新建）— 统一时间格式化工具库
2. 13 个组件替换独立实现（见下）

## 技术方案

### Phase 1: 后端时区配置统一（P0）

#### 1.1 日志时区默认改为 local，失败回退北京时间

- `DEFAULT_LOG_TIMEZONE = "local"`
- `TimezoneFormatter` 始终用 `resolve_timezone()` 返回的 `tzinfo` 做 `astimezone`
- `SageLogger` 日志文件按本地日期切分

#### 1.2 API 时间格式

`backend/api/usage_routes.py`
- `_trend_bucket_starts()`：`datetime.now()` → `local_now()`
- 新增 `_ts_iso()`：输出 `2026-11-03T19:00:00+08:00`（带偏移），前端 `new Date(ts)` 可正确解析
- `_ts_key()` 保持本地墙钟字符串，与 SQLite `strftime(...,'localtime')` 对齐

#### 1.3 aware datetime 改造

- `utc_now()` 返回 `datetime.now(tz=timezone.utc)`（aware），替代 `datetime.utcnow()`（naive）
- 所有读取历史 ISO 串的位置统一 `ensure_utc()`
- 时间窗口判断用 `local_now()`，预算耗时做差两操作数均 `ensure_utc`

#### 1.4 APScheduler 显式本地时区

`BackgroundScheduler(daemon=True, timezone=local_timezone())`

### Phase 2: 前端统一时间工具（P1）

#### 2.1 `src/shared/lib/timeFormatter.ts`

输入契约：**所有 `ts` 均为毫秒**；秒级时间戳由调用方乘 1000。

| 函数 | 输出 |
|------|------|
| `formatDate(ts)` | `2026/11/03` |
| `formatDateTime(ts)` | `2026/11/03 14:23` |
| `formatTimeOfDay(ts)` | `14:23:45` |
| `formatLocalString(ts)` | `2026/11/03 14:23:45` |
| `formatRelativeTime(ts)` | `刚刚` / `X 分钟前` / `X 小时前` / `昨天 HH:MM` / `X 天前` / `MM/DD` |

#### 2.2 替换文件

- `widgets/memory/MemoryBrowser.tsx`
- `widgets/memory/MemoryItem.tsx`
- `widgets/chat/TrajectoryPane.tsx`
- `widgets/chat/TurnGroup.tsx`
- `widgets/chat/progress/EventTimeline.tsx`
- `widgets/session/ArchivesModal.tsx`
- `widgets/evolution/EvolutionLog.tsx`
- `widgets/evolution/EvolutionPanel.tsx`
- `widgets/evolution/LearnedPreferences.tsx`
- `widgets/evolution/RecallMetrics.tsx`
- `widgets/skills/SkillAuditDrawer.tsx`
- `features/autonomous-goals/GoalDetailPage.tsx`
- `src/shared/api/usageApi.ts`（仅文档注释）

## 实施步骤

### Phase 1: 后端修复（P0）
- [x] 1.1 创建 `backend/utils/timezones.py`
- [x] 1.2 修改 `backend/utils/logging.py` 默认时区
- [x] 1.3 修改 Electron 层日志时区默认值
- [x] 1.4 修复 `backend/api/usage_routes.py` naive datetime
- [x] 1.5 修复 `backend/domain/autonomous_goals.py` 弃用 API
- [x] 1.6 修改 `backend/services/scheduler.py` APScheduler 时区
- [x] 1.7 修复 goal 时间窗口 naive/aware 混用
- [x] 1.8 运行后端测试验证

### Phase 2: 前端统一（P1）
- [x] 2.1 创建 `src/shared/lib/timeFormatter.ts`
- [x] 2.2 替换各组件独立实现
- [x] 2.3 新增 `timeFormatter.test.ts` 单元测试
- [x] 2.4 运行前端测试验证

### Phase 3: 集成验证
- [ ] 3.1 启动桌面端验证日志时区
- [ ] 3.2 验证 API 响应时间格式
- [ ] 3.3 验证前端时间显示

## 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 本地时区获取失败 | 低 | 中 | 多级回退：local → 系统时区 → 固定 +08:00 |
| APScheduler 时区变更导致任务时间偏移 | 中 | 低 | 数据库存储 epoch ms，不受时区影响 |
| naive/aware 混用 TypeError | 中 | 高 | 所有历史 ISO 读取走 `ensure_utc`；单测覆盖 |
| 前端时间格式化替换遗漏 | 中 | 低 | 全局搜索 + 统一工具库单测 |

## 依赖

- 无新增外部依赖
- 使用 Python 标准库 `datetime`、`zoneinfo`（py38 用 `backports.zoneinfo`）+ 已有 `tzlocal`
- 使用浏览器 `Intl.DateTimeFormat`（`toLocale*String`）
