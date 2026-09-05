# Task 4 Report: Word 模板分析

## 状态

已完成 Task 4：实现 `analyze_word_template` 及其单元测试。未实现 Task 5 的 `fill_word_template`。

## TDD 证据

### RED

先创建测试并运行：

```text
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office/test_word_template.py::test_analyze_simple_template -v
```

测试收集失败，错误为：

```text
ModuleNotFoundError: No module named 'backend.office.word_template'
```

### GREEN

实现模块后运行：

```text
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office/test_word_template.py -v
```

结果：`5 passed`。

同时运行完整 office 单元测试：

```text
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office -q
```

结果：`258 passed, 8 warnings`。

警告为项目现有 Pydantic class-based config 弃用警告，与本任务无关。

## 实现内容

- 在正文段落中扫描 `{{...}}` 占位符，并记录正文段落索引。
- 在表格单元格中扫描占位符，并记录表格、行、列索引。
- 在页眉和页脚中扫描占位符并记录位置。
- 按名称推断 `date`/`日期`、`image`/`图片` 和普通文本类型。
- 检测 Jinja 控制标签 `{% ... %}`。
- 将不存在的路径转换为 `OfficeFileNotFoundError`。
- 将非普通文件和 DOCX 解析失败转换为 `OfficeTemplateParseError`。
- 构造 `WordTemplateAnalysis` 和 `PARSED` 状态的 `OfficeDocumentSummary`。

## 文件

- `backend/office/word_template.py`
- `backend/tests/unit/office/test_word_template.py`

## 自检

- `git diff --check` 通过。
- 输入路径在函数边界转换为 `Path`，且不会写回输入文件。
- 实现使用 Python 3.8 兼容的类型标注和语法。
- 未增加路由、请求模型或模板填充逻辑。
- 未发现硬编码凭据、调试输出或未处理的预期解析异常。

## 关注事项

## 审查修复（commit 待生成）

根据 Task 4 审查意见完成以下修复：

- 移除 `word_template.py` 中未使用的 `logging` 和 `logger`。
- 新增 story 表格扫描，页眉/页脚表格单元格现在会提取占位符，并保留 `HEADER`/`FOOTER` location 及表格、行、列索引语义。
- Jinja 控制标签检测现在覆盖正文段落、正文表格单元格、页眉/页脚段落和页眉/页脚表格单元格。
- 扩展测试覆盖正文表格、页眉、页脚及其表格占位符的 location/index/type，并参数化验证正文表格、页眉、页脚控制标签。
- 未实现 Task 5、路由或其他范围外功能。

### 验证结果

- focused tests：`8 passed, 8 warnings`
- office 回归：`261 passed, 8 warnings`
- Ruff：`All checks passed!`
- Python compileall：通过（无输出）
- `git diff --check`：通过（无输出）

warnings 仍为既有 Pydantic class-based config 弃用警告。

## 第二轮审查修复（commit 待生成）

针对 scoped review 的 HIGH 问题完成以下修复：

- `_scan_tables`、`_scan_story_tables` 和 `_story_has_jinja_control` 递归遍历 cell 内嵌套表格；嵌套表格继续使用外层 story 的 `table_index`，并补充正文、页眉、页脚嵌套表格占位符和 Jinja 控制标签测试。
- `analyze_word_template` 先调用 `validate_workspace(Path(workspace_path))`，再调用 `resolve_within(workspace, file_path)`；现有不存在文件行为保持 `OfficeFileNotFoundError`，真实存在的 workspace 外文件抛路径安全错误，返回路径 canonicalized。
- 在 `Document()` 前新增 DOCX ZIP 预检：压缩文件大小上限 50 MiB、成员数上限 10,000、总 uncompressed 大小上限 250 MiB；超限抛 `OfficeSizeLimitError`。
- ZIP 结构检查捕获 `OSError` 和 `zipfile.BadZipFile`，转换为 `OfficeTemplateParseError`；未实现 Task 5 或路由。

### 第二轮验证结果

- focused tests：`12 passed, 8 warnings`
- office 回归：`265 passed, 8 warnings`
- Ruff：`All checks passed!`
- Python compileall：通过（无输出）
- `git diff --check`：通过（无输出）

warnings 仍为既有 Pydantic class-based config 弃用警告。

### 第二轮 Concern

页眉/页脚段落仍无 section index，这是现有 `TemplatePlaceholder` 模型无法表达的字段；本次继续按 brief 契约保持现有 location 语义。ZIP 限制常量为模块级策略值，测试通过 monkeypatch 各自验证三类上限。
