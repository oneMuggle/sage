# 代码探索工具实施方案

## Context

用户在 Sage 中询问"查看 /home/fz/project/LLM_Simple 中的代码并给出优化建议"时,遇到 `max_iterations_exceeded` 错误。目标项目有 2691 个源文件、515,694 行代码,而 primary agent 只有 15 次 iteration,每次只能读 1 个文件(ReadFileTool 默认 limit=500 行),导致读了约 10 个文件就被截断。

**根本原因**:缺少代码探索工具 + primary agent 工具白名单过窄。

**关键发现**:`grep_search` 和 `glob_search` 工具**已经存在**于 `backend/tools/search_tools.py`,只是没加入 primary agent 的白名单。唯一需要新建的是 `file_summary` 工具。

## Recommended Approach

### 1. 新建 FileSummaryTool

**文件**: `backend/tools/file_summary_tool.py`

提取文件结构骨架(imports/classes/functions/methods)而非全文:
- Python: 用 `ast.parse()` 精确提取
- JavaScript/TypeScript: 用正则提取顶层 exports
- 其他语言: 退化为文件头 30 行 + 行数统计

**设计要点**:
- 继承 `BaseTool`,声明 `risk = RiskClass.READ`
- 复用 `file_tool._contains_binary_marker` 和 `detect_bom_encoding`
- 复用 `MAX_READ_SIZE_BYTES` (5 MiB) 硬上限
- READ 操作不做 workspace 边界检查(与 ReadFileTool 一致)
- 错误走 `ToolResult(success=False)`,execute 永不抛异常
- 支持 `language` 参数覆盖自动检测

**参数**:
```python
{
    "path": {"type": "string", "description": "文件路径"},
    "language": {
        "type": "string",
        "enum": ["python", "javascript", "typescript"],
        "description": "语言提示(可选,缺省按后缀自动检测)"
    }
}
```

**返回**:
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

### 2. 注册 FileSummaryTool

**文件**: `backend/tools/__init__.py`

修改:
- 添加 import: `from .file_summary_tool import FileSummaryTool`
- 在 `register_all_tools()` 中注册: `registry.register(FileSummaryTool(policy=policy))`
- 添加到 `__all__` 列表

### 3. 扩展 Primary Agent 工具白名单

**文件**: `backend/agents/profiles.py`

修改 `create_default_agents()` 中 `primary` agent 的 `tools` 列表(第 69 行):

```python
tools=[
    "calculator",
    "memory_search",
    "memory_save",
    "list_dir",
    "read_file",
    # 代码探索三件套(全部 READ 操作,无副作用风险)
    "grep_search",    # 正则内容搜索(GrepSearchTool,已存在)
    "glob_search",    # glob 文件名搜索(GlobSearchTool,已存在)
    "file_summary",   # 文件结构摘要(FileSummaryTool,新建)
],
```

### 4. 编写单元测试

**文件**: `backend/tests/unit/test_file_summary_tool.py`

**测试用例** (14 个):

#### Schema 测试
1. `test_file_summary_schema_has_required_fields` - schema 完整性 + risk=read

#### Python 提取测试
2. `test_python_extracts_classes_functions_imports` - 完整提取 classes/functions/imports/methods
3. `test_python_syntax_error_returns_error_field_not_exception` - 语法错误优雅降级(error 字段,success=True)
4. `test_python_async_function_extracted` - async def 也被提取

#### JavaScript/TypeScript 测试
5. `test_javascript_extracts_exports` - 正则提取 export class/function/const 箭头
6. `test_javascript_default_export_class` - default export class 识别

#### Fallback 测试
7. `test_unknown_language_returns_head_and_line_count` - 不支持语言退化为文件头 + 行数

#### Language Hint 测试
8. `test_language_hint_overrides_extension` - 显式 language 参数覆盖后缀检测

#### 错误路径测试
9. `test_binary_file_rejected` - 二进制文件拒绝
10. `test_file_too_large_rejected` - 超过 5 MiB 拒绝
11. `test_nonexistent_path_returns_error` - 路径不存在错误
12. `test_unknown_kwargs_rejected` - 未知参数干净错误(FIX-2 模式)
13. `test_empty_path_rejected` - 空 path 拒绝

#### 集成测试
14. `test_policy_injection_works` - ToolPolicy 注入

## Files to Modify

| 序号 | 操作 | 文件路径 |
|------|------|----------|
| 1 | 新建 | `backend/tools/file_summary_tool.py` |
| 2 | 修改 | `backend/tools/__init__.py` |
| 3 | 修改 | `backend/agents/profiles.py` |
| 4 | 新建 | `backend/tests/unit/test_file_summary_tool.py` |

## Implementation Details

### FileSummaryTool 核心实现

```python
class FileSummaryTool(BaseTool):
    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_summary",
            description=(
                "提取文件的结构骨架(imports / classes / functions / methods)"
                "而不是完整内容,用于快速理解大文件的结构。"
                "Python 用 ast.parse 精确提取;JS/TS 用正则提取 exports;"
                "其他语言退化为文件头 30 行 + 行数统计。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "language": {
                        "type": "string",
                        "enum": ["python", "javascript", "typescript"],
                        "description": "语言提示(可选)"
                    },
                },
                "required": ["path"],
            },
        )

    def execute(self, path: str, language: Optional[str] = None, **kwargs) -> ToolResult:
        # 1. 未知参数检查(FIX-2)
        # 2. path 非空检查
        # 3. 文件存在性/可读性检查
        # 4. 大小/二进制检查(复用 file_tool 工具函数)
        # 5. 读取文件内容(BOM 识别)
        # 6. 语言检测(显式 hint > 后缀映射)
        # 7. 按语言解析(Python: ast / JS/TS: regex / 其他: fallback)
        # 8. 返回 ToolResult(success=True, content=summary)
```

### 解析函数

```python
def _parse_python(text: str) -> Dict[str, Any]:
    """用 ast.parse 提取 imports/classes/functions"""
    
def _parse_js_ts(text: str) -> Dict[str, Any]:
    """用正则提取 JS/TS 顶层 exports"""
    
def _fallback_head(text: str, total_lines: int) -> Dict[str, Any]:
    """不支持语言时返回文件头 30 行"""
    
def _detect_language(path: str, hint: Optional[str]) -> str:
    """检测语言:hint 优先,否则按后缀映射"""
```

## Verification

### 1. 运行新工具测试
```bash
pytest backend/tests/unit/test_file_summary_tool.py -v
# 预期:14 个测试全部通过
```

### 2. 验证现有搜索工具不受影响
```bash
pytest backend/tests/unit/test_search_tools.py -v
# 预期:所有 grep_search/glob_search 测试通过
```

### 3. 验证 Profile 集成
```bash
pytest backend/tests/unit/test_agent_profile_wiring.py -v
# 预期:primary agent 加载正常,工具白名单包含新工具
```

### 4. 端到端验证(手动)
启动 Sage 应用,在聊天中询问:
```
查看 /home/fz/project/LLM_Simple 中的代码,并给出优化建议
```

**预期行为**:
1. Agent 先用 `glob_search` 找 `**/*.py` 定位 Python 文件
2. 用 `file_summary` 快速浏览关键文件结构(如 `main.py`, `agent/` 目录)
3. 用 `grep_search` 搜索特定模式(如 `def main`, `TODO`, 性能热点)
4. 针对 3-5 个关键文件用 `read_file` 读全文深入分析
5. 综合给出优化建议
6. **不再触发 max_iterations_exceeded**

## Expected Impact

| 指标 | 改造前 | 改造后 |
|------|--------|--------|
| primary agent 工具数 | 5 | 8 |
| 单次迭代能掌握的文件信息 | 1 个文件 500 行 | ~30 个文件结构(file_summary) |
| 找关键文件 | 需 list_dir → read_file 多轮 | glob_search 一次到位 |
| 找代码片段 | grep 不在工具集中 | grep_search 直接调用 |
| max_iterations_exceeded 风险 | 高(读 ~10 个文件就截断) | 低(结构地图 + 定向读取) |

## Risks and Mitigations

1. **ReDoS**: JS/TS 正则为线性时间(无回溯陷阱),且受 `policy.timeout_seconds` 保护
2. **内存**: 复用 `MAX_READ_SIZE_BYTES` (5 MiB) 硬上限,超大文件直接拒绝
3. **LLM 工具选择**: 3 个工具职责清晰分离(grep 搜内容 / glob 找文件 / file_summary 看结构)
4. **向后兼容**: 不动现有工具行为,只在 primary profile 加白名单
5. **UTF-16 文件**: 复用 `detect_bom_encoding` 处理 Windows .reg / .ps1 导出
6. **Profile 白名单测试**: `test_agent_profile_wiring.py` 已覆盖 primary agent 加载流程

## Why This Approach

**为什么不新建 grep_search / glob_search?**
- 这两个工具已存在于 `backend/tools/search_tools.py`,具备生产级质量
- GrepSearchTool 有 ReDoS 缓解(1000 字符正则上限 + 10000 字符行长上限)、二进制嗅探、UTF-16 BOM 识别
- GlobSearchTool 有 node_modules/.git 忽略、mtime 倒序、200 条上限
- 重新实现是重复造轮子,且会丢失已有的安全防护

**为什么只改 primary profile?**
- primary 是 chat 默认 agent,用户直接对话都走它
- 其他 agent(researcher/coder/memory_manager) 各有专责,不需要代码探索工具
- 最小改动原则:只暴露必要的工具给 LLM
