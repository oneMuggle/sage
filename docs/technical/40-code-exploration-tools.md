# 40. 代码探索工具三件套（grep / glob / file_summary）

> **最后更新**: 2026-08-06
> **适用版本**: Sage main @ PR #265
> **背景计划**: [`../plans/2026-08-01_code-exploration-tools.md`](../plans/2026-08-01_code-exploration-tools.md)（已实施,计划已删除）

## 40.1 背景与目标

### 问题

用户在 Sage 中询问"查看 `/home/fz/project/LLM_Simple` 中的代码并给出优化建议"时,触发 `max_iterations_exceeded` 错误。目标项目有约 2691 个源文件 / 约 51.5 万行代码,而 primary agent 当时只有 15 次 iteration、每次只能 `read_file` 读 1 个文件(默认 limit=500 行),读了约 10 个文件就被截断。

### 根本原因

- 缺少代码探索类工具(primary agent 工具集当时仅 5 个)
- `grep_search` / `glob_search` 工具**已经存在**于 `backend/tools/search_tools.py`,只是没加入 primary 白名单
- 唯一需要新建的是 `file_summary`(以"结构骨架"代替"全文读取")

### 三个工具的职责分离

| 工具 | 解决什么 | 输入 | 输出 |
|---|---|---|---|
| `grep_search` | 找代码片段 | 正则 + 路径 | 匹配行 / 文件列表 |
| `glob_search` | 找文件 | glob 模式 + 路径 | 文件路径列表 |
| `file_summary` | 看结构(不读全文) | 文件路径 + 可选语言 hint | imports / classes / functions / methods |

三者组合 = LLM 在 IDE 中"先 Outline 再 Search"的探索工作流。

## 40.2 三个工具详解

### 40.2.1 grep_search（已有,仅加入白名单）

**实现**: `backend/tools/search_tools.py` 的 `GrepSearchTool`

**核心约束**（ReDoS 缓解,不是根治）:
- 正则长度上限 `GREP_MAX_PATTERN_LENGTH = 1000` 字符(超限直接报错)
- content 模式单行长度上限 `GREP_MAX_LINE_LENGTH = 10000` 字符(超长行跳过并计入 `skipped_long_lines`)
- 自动跳过二进制文件(复用 file_tool 的 NUL/BOM 嗅探)
- `truncated=True` 当匹配超过 `GREP_CONTENT_MAX_MATCHES=100` 或 `GREP_FILES_MAX_MATCHES=200`

**默认行为**:
- 默认跳 `node_modules` / `.git` / `__pycache__` / `dist`
- 默认根 = `policy.workspace_root`,未绑定时回退 cwd

### 40.2.2 glob_search（已有,仅加入白名单）

**实现**: `backend/tools/search_tools.py` 的 `GlobSearchTool`

**核心约束**:
- 结果上限 `GLOB_MAX_RESULTS = 200`,超限 `truncated=True`
- 按 mtime 倒序(最近修改的在前)
- 默认跳过 `node_modules` / `.git` / `__pycache__` / `dist`

### 40.2.3 file_summary（PR #265 新建）

**实现**: `backend/tools/file_summary_tool.py` 的 `FileSummaryTool`

**参数**:

```python
{
    "path": {"type": "string", "description": "文件路径"},
    "language": {
        "type": "string",
        "enum": ["python", "javascript", "typescript"],
        "description": "语言提示(可选,缺省按后缀自动检测)"
    },
}
```

**返回结构**:

```python
{
    "path": str,
    "language": str,
    "total_lines": int,
    "original_bytes": int,
    "imports": List[str],
    "classes": List[{"name": str, "line": int, "methods": List[str]}],
    "functions": List[{"name": str, "line": int, "params": List[str]}],
    # 不支持的语言时额外返回:
    "head": str,  # 文件头 30 行
    # Python 语法错误时:
    "error": str  # 解析错误信息(整体仍 success=True)
}
```

**解析策略**:

| 语言 | 方法 | 输出 |
|---|---|---|
| Python | `ast.parse()` 精确提取 | imports / classes(带 methods) / functions(带 params) |
| JS / TS | 正则提取顶层 `export class/function/const` | exports 列表 |
| 其他 | 退化为文件头 30 行 + 行数统计 | head + total_lines |

`language` 参数优先级 > 后缀自动检测 > fallback。

**安全防护**(复用 file_tool):
- 大小上限 `MAX_READ_SIZE_BYTES = 5 MiB`,超限直接拒绝
- 二进制嗅探(复用 `_contains_binary_marker`)
- BOM 识别(复用 `detect_bom_encoding`,支持 UTF-16 的 `.reg` / `.ps1`)
- 未知 kwargs 干净报错(FIX-2 模式)
- READ 操作不做 workspace 边界检查(与 ReadFileTool 一致)

## 40.3 Primary Agent 白名单集成

**位置**: `backend/agents/profiles.py` 第 69-80 行

```python
# 2026-08-01: 加 grep_search/glob_search/file_summary 三件套,
# 解决大代码库分析时 max_iterations_exceeded 问题(PR #264)
tools=[
    "calculator",
    "memory_search",
    "memory_save",
    "list_dir",
    "read_file",
    # 代码探索三件套(全部 READ 操作,无副作用风险)
    "grep_search",    # 正则内容搜索(GrepSearchTool)
    "glob_search",    # glob 文件名搜索(GlobSearchTool)
    "file_summary",   # 文件结构摘要(FileSummaryTool,新建)
],
```

**为何只改 primary**:
- primary 是 chat 默认 agent,用户直接对话都走它
- 其他 agent(researcher/coder/memory_manager) 已有专责工具集
- 最小改动原则:只暴露必要的工具给 LLM

**为何三个都加而不是只加一个**:
- 三者职责清晰分离(grep 搜内容 / glob 找文件 / file_summary 看结构)
- LLM 不会无脑调用,每个工具有明确适用场景

## 40.4 期望效果

| 指标 | 改造前 | 改造后 |
|---|---|---|
| primary agent 工具数 | 5 | 8 |
| 单次迭代能掌握的文件信息 | 1 个文件 500 行 | 约 30 个文件结构(`file_summary`) |
| 找关键文件 | `list_dir` -> `read_file` 多轮 | `glob_search` 一次到位 |
| 找代码片段 | grep 不在工具集中 | `grep_search` 直接调用 |
| `max_iterations_exceeded` 风险 | 高(读约 10 个文件就截断) | 低(结构地图 + 定向读取) |

### 端到端预期行为

1. Agent 先用 `glob_search` 找 `**/*.py` 定位 Python 文件
2. 用 `file_summary` 快速浏览关键文件结构(如 `main.py`、`agent/` 目录)
3. 用 `grep_search` 搜索特定模式(如 `def main`、`TODO`、性能热点)
4. 针对 3-5 个关键文件用 `read_file` 读全文深入分析
5. 综合给出优化建议
6. **不再触发 `max_iterations_exceeded`**

## 40.5 测试覆盖

| 文件 | 验证 |
|---|---|
| `backend/tests/unit/test_search_tools.py` | grep / glob ReDoS 缓解 + 上限 + 工作区默认根 |
| `backend/tests/unit/test_file_summary_tool.py` | 14 用例: schema / Python ast / JS 正则 / language hint / 大小 / 二进制 / 未知 kwargs / 空路径 |
| `backend/tests/unit/test_agent_profile_wiring.py` | primary agent 加载 + 新工具白名单验证 |

## 40.6 风险与边界

| 风险 | 缓解 |
|---|---|
| ReDoS | JS/TS 正则线性时间(无回溯陷阱);grep 模式长度 + 单行长度硬上限 |
| 内存 | 5 MiB 硬上限,超大文件直接拒绝 |
| LLM 工具选择错 | 三个工具 description 明确分离适用场景 |
| 工具膨胀 | 仅 primary 暴露,其他 agent 不动 |

## 40.7 相关文件

| 文件 | 角色 |
|---|---|
| `backend/tools/search_tools.py` | GrepSearchTool + GlobSearchTool 实现 |
| `backend/tools/file_summary_tool.py` | FileSummaryTool 实现(PR #265 新建) |
| `backend/tools/__init__.py` | 注册到 `ToolRegistry` |
| `backend/agents/profiles.py` | primary agent 工具白名单 |
| `backend/tests/unit/test_*` | 单测覆盖 |

## 40.8 后续可考虑(非本次范围)

- `file_summary` 支持 Rust / Go(目前只能 fallback 到 head 30 行)
- `grep_search` 加入 pcre2 引擎以支持 lookbehind(目前标准 `re`)
- 给 `file_summary` 加 `--include-private` 选项(目前只提取顶级 / export 内容)
