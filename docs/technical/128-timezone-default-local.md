# 时区统一：默认本地时区，失败回落北京时间

> 日期：2026-11-03
> 分支：`feat/default-local-timezone`
> 方案：显示层默认本地时区（`'local'`），解析失败逐级回落到北京时间（`Asia/Shanghai`，固定 +08:00 兜底）；存储层保持 UTC 不变

## 1. 定位与目标

Sage 的时间处理此前存在四类问题：

1. **日志默认 UTC** —— 用户看到的日志时间与本地墙钟不一致，需要手动配置；
2. **API 时间格式不一致** —— 趋势图等接口返回 naive datetime，前端无法判断时区；
3. **前端格式化分散** —— 10+ 个组件各自实现 `formatTime` / `formatDate`，输入单位（秒/毫秒）不统一；
4. **使用已弃用 API** —— `datetime.utcnow()` 在 Python 3.12+ 触发 `DeprecationWarning`，且返回 naive 值。

**目标**：

- **显示层**：默认本地时区，获取失败回退北京时间；
- **存储层**：保持 UTC epoch / ISO-8601 存储不变，仅在读取与展示时转换；
- **一致性**：日志、API 趋势、定时任务、前端渲染共用同一套解析链。

## 2. 时区解析链

### 2.1 后端

`backend/domain/time_utils.py`（domain 层原语，仅依赖标准库）：

| 符号 | 说明 |
| --- | --- |
| `LOCAL_TIMEZONE` | `"local"`，表示"取系统本地时区，失败回落北京时间" |
| `utc_now()` | 返回 timezone-aware 的当前 UTC 时间，替代 `datetime.utcnow()` |
| `ensure_utc(dt)` | naive 视为 UTC 补时区，aware 原样返回（读取历史数据用） |

`backend/utils/timezones.py`（基础设施层解析工具，向后兼容再导出 domain 原语）：

| 输入 | 结果 |
| --- | --- |
| `'local'` | `tzlocal.get_localzone()` → `astimezone()` 当前偏移 → `beijing_timezone()` |
| `'UTC'` / 空串 / `None` | `datetime.timezone.utc` |
| IANA 名（如 `Asia/Shanghai`） | `ZoneInfo(name)` → `beijing_timezone()` |
| 非法 IANA | `beijing_timezone()` |

`beijing_timezone()` 优先 `ZoneInfo("Asia/Shanghai")`，Windows 缺 tzdata 时回落到固定 `+08:00` 偏移（中国自 1991 年起无夏令时，两者等价）。

其余辅助函数：

- `local_now()` —— 当前本地时间（aware）；
- `resolve_timezone(name)` —— 名称 → `tzinfo`，非法输入不抛错；
- `beijing_timezone()` —— 北京时间 `tzinfo`。

### 2.2 前端

`src/shared/lib/timeFormatter.ts` 统一格式化出口，**输入契约：所有 `ts` 均为毫秒**（秒级时间戳由调用方乘 1000）。

| 函数 | 输出 |
| --- | --- |
| `formatDate(ts)` | `2026/11/03` |
| `formatDateTime(ts)` | `2026/11/03 14:23` |
| `formatTimeOfDay(ts)` | `14:23:45` |
| `formatLocalString(ts)` | `2026/11/03 14:23:45` |
| `formatRelativeTime(ts)` | `刚刚` / `X 分钟前` / `X 小时前` / `昨天 HH:MM` / `X 天前` / `MM/DD` |

非法输入统一返回占位符（`—` / 空串 / 原值），不抛错。

## 3. 涉及文件

### 3.1 后端

| 文件 | 变更 |
| --- | --- |
| `backend/domain/time_utils.py` | **新建**：domain 层时区原语（无外部依赖） |
| `backend/utils/timezones.py` | **新建**：解析链 + 北京回退；再导出 domain 原语 |
| `backend/utils/logging.py` | 日志默认时区改 `local`，`TimezoneFormatter` 走 `resolve_timezone` |
| `backend/api/usage_routes.py` | 趋势桶起点用 `local_now()`；`ts` 输出带偏移 ISO；`_ts_key()` 保持本地墙钟字符串对齐 SQLite `strftime(...,'localtime')` |
| `backend/domain/autonomous_goals.py` | `utcnow()` → `utc_now()`；`TimeWindow.timezone` 默认 `local`；`from_dict` 走 `ensure_utc` |
| `backend/data/goal_repository.py` | 读取行时 `ensure_utc` |
| `backend/services/goal_service.py` / `time_window_manager.py` | 时间窗口用 aware 本地时间；预算做差前 `ensure_utc` 归一 |
| `backend/services/scheduler.py` | `BackgroundScheduler(timezone=local_timezone())` |
| `backend/main.py` | `SAGE_LOG_TIMEZONE` 默认值改 `local` |

### 3.2 Electron

| 文件 | 变更 |
| --- | --- |
| `electron/logTimezone.ts` | 缺失 / 损坏 / 空值默认 `'local'` |
| `electron/backendLauncher.ts` / `main.ts` / `logger.ts` | 默认 `'local'` |

### 3.3 前端

- `src/shared/lib/timeFormatter.ts`（新建，含 `__tests__/timeFormatter.test.ts`）
- 替换独立实现：`MemoryBrowser`、`MemoryItem`、`TrajectoryPane`、`TurnGroup`、`EventTimeline`、`ArchivesModal`、`EvolutionLog`、`EvolutionPanel`、`LearnedPreferences`、`RecallMetrics`、`SkillAuditDrawer`、`GoalDetailPage`
- `src/shared/api/usageApi.ts`（仅文档注释）

## 4. 关键实现细节

### 4.1 naive / aware 混用防御

历史数据的 ISO 串无偏移后缀，直接参与 aware 运算会抛 `TypeError`。所有读取历史时间的入口统一经 `ensure_utc()` 归一；新写入一律使用 `utc_now()`（aware）。

### 4.2 日志文件切分

`SageLogger` 按本地日期切分日志文件，`TimezoneFormatter` 始终使用 `resolve_timezone()` 返回的 `tzinfo` 做 `astimezone`，避免格式化与文件名跨时区不一致。

### 4.3 APScheduler 时区

`BackgroundScheduler(daemon=True, timezone=local_timezone())`。任务触发时间按本地时区解释；持久化的下次运行时间仍以 epoch 存储，不受时区变更影响。

### 4.4 domain 纯净性

domain 层禁止 import `backend.utils`。因此 `LOCAL_TIMEZONE` / `utc_now` / `ensure_utc` 下沉到 `backend/domain/time_utils.py`（仅标准库），`backend/utils/timezones.py` 反向再导出，公开 API 对调用方保持不变。

### 4.5 CI 兼容

- 测试不硬编码宿主时区：`test_default_local` monkeypatch `local_timezone` 为北京时间，避免 CI 本机时区为 UTC 时断言失败；
- py38 兼容：测试通过 `beijing_timezone()` 获取时区，避免直接 `from zoneinfo import ...` 触发 win7 地雷扫描；生产代码保留 `zoneinfo` → `backports.zoneinfo` 守卫。

## 5. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
| --- | --- | --- | --- |
| 本地时区获取失败 | 低 | 中 | 三级回退：tzlocal → `astimezone()` 偏移 → 固定 +08:00 |
| APScheduler 时区变更导致任务时间偏移 | 中 | 低 | 存储 epoch ms，不受时区影响 |
| naive/aware 混用 `TypeError` | 中 | 高 | 历史 ISO 读取统一 `ensure_utc`；单测覆盖 |
| 前端格式化替换遗漏 | 中 | 低 | 全局搜索 + 统一工具库单测 |

## 6. 依赖

- 无新增外部依赖；
- 后端：标准库 `datetime`、`zoneinfo`（py38 用 `backports.zoneinfo`）+ 已有 `tzlocal`（APScheduler 传递依赖）；
- 前端：浏览器原生 `Intl.DateTimeFormat`（`toLocale*String`）。
