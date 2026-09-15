# Word 模板化 + PDF 全能力操作设计

> **日期**: 2026-09-05  
> **状态**: 设计中  
> **作者**: Claude Code  
> **分支**: main + release/win7

---

## 1. 背景与目标

### 1.1 现状

Sage 项目已有完整的 Office CRUD 能力：

| 功能 | PPT | Word | Excel | PDF |
|------|:---:|:----:|:-----:|:---:|
| 读取 | ✅ | ✅ | ✅ | ❌ |
| 生成 | ✅ | ✅ | ✅ | ❌ |
| 编辑 | ✅ | ✅ | ✅ | ❌ |
| 模板填充 | ❌ | ❌ | ❌ | ❌ |

**缺失能力**：
- Word 模板化：无法识别/填充 `{{变量名}}` 占位符
- PDF：完全缺失读取、生成、表单填充能力

### 1.2 目标

新增以下能力：

1. **Word 模板化**
   - 模板分析：识别 `{{变量名}}` 占位符，返回位置、类型、格式约束
   - 模板填充：根据数据字典填充模板生成文档

2. **PDF 全能力**
   - 读取：提取文本、表格、图片、元数据
   - 生成：从结构化数据创建 PDF
   - 表单填充：读取/填写 PDF 表单字段（AcroForm）

### 1.3 非目标（本设计不覆盖）

- Excel/PPT 模板化（未来可扩展）
- PDF 数字签名
- Office 文件转换（如 Word → PDF）
- OCR 扫描件识别

---

## 2. 技术方案

### 2.1 依赖选择

| 功能 | 库 | 版本 | 说明 |
|------|-----|------|------|
| Word 模板 | `docxtpl` | >=0.20 | python-docx 扩展，原生支持 `{{var}}` |
| PDF 读取 | `PyMuPDF (fitz)` | >=1.25 | 文本/表格/图片提取，性能优秀 |
| PDF 生成 | `reportlab` | >=4.0 | 成熟的 PDF 生成库 |
| PDF 表单 | `PyMuPDF` | 同上 | 支持 AcroForm 表单字段读写 |

**依赖大小**：~5MB wheel 总和

### 2.2 双分支兼容性

| 分支 | Python | Pydantic | 策略 |
|------|--------|----------|------|
| main | 3.10 | 2.x | 直接使用最新库版本 |
| release/win7 | 3.8 | 1.x | 验证兼容性，必要时降级版本 |

**风险点**：
- `docxtpl` 依赖 `python-docx`（已兼容）
- `PyMuPDF` 有 C 扩展，需确认 Python 3.8 wheel 可用性
- `reportlab` 纯 Python，无兼容性问题

---

## 3. 架构设计

### 3.1 模块结构

```
backend/office/
├── word.py              # 现有：read_docx, generate_docx
├── word_template.py     # 新增：模板分析+填充
├── pdf.py               # 新增：PDF 读取+生成
├── pdf_forms.py         # 新增：PDF 表单操作
├── models.py            # 扩展：新数据模型
├── errors.py            # 扩展：新错误类型
└── __init__.py          # 导出新函数
```

### 3.2 API 路由

```
backend/api/office_routes.py 扩展：

POST /api/v1/office/word/analyze-template   # 分析 Word 模板
POST /api/v1/office/word/fill-template      # 填充 Word 模板
POST /api/v1/office/pdf/read                # 读取 PDF
POST /api/v1/office/pdf/generate            # 生成 PDF
POST /api/v1/office/pdf/read-form           # 读取 PDF 表单字段
POST /api/v1/office/pdf/fill-form           # 填充 PDF 表单
```

### 3.3 LLM 工具集成

```
backend/tools/office_tools.py 扩展：

- office_analyze_word_template  # LLM 分析模板占位符
- office_fill_word_template     # LLM 填充模板生成文档
- office_read_pdf               # LLM 读取 PDF 内容
- office_generate_pdf           # LLM 生成 PDF
- office_read_pdf_form          # LLM 读取 PDF 表单
- office_fill_pdf_form          # LLM 填充 PDF 表单
```

---

## 4. 数据模型设计

### 4.1 Word 模板分析

```python
class TemplatePlaceholderType(str, Enum):
    TEXT = "text"           # 普通文本
    IMAGE = "image"         # 图片占位
    TABLE = "table"         # 表格循环
    DATE = "date"           # 日期格式
    RICH_TEXT = "rich_text" # 富文本

class PlaceholderLocation(str, Enum):
    BODY = "body"           # 正文段落
    TABLE = "table"         # 表格单元格
    HEADER = "header"       # 页眉
    FOOTER = "footer"       # 页脚
    TEXT_BOX = "text_box"   # 文本框

class TemplatePlaceholder(BaseModel):
    name: str                              # 变量名（不含 {{}}）
    raw_tag: str                           # 原始标签（如 "{{客户姓名}}"）
    type: TemplatePlaceholderType
    location: PlaceholderLocation
    paragraph_index: Optional[int] = None  # 段落索引
    table_index: Optional[int] = None      # 表格索引
    row_index: Optional[int] = None        # 行索引
    col_index: Optional[int] = None        # 列索引
    format_hint: Optional[str] = None      # 格式提示（如日期格式）

class WordTemplateAnalysis(BaseModel):
    file_path: str
    placeholders: List[TemplatePlaceholder]
    summary: OfficeDocumentSummary
    has_jinja_control: bool                # 是否有 {% if %} 等控制标签
```

### 4.2 Word 模板填充

```python
class WordTemplateFillRequest(BaseModel):
    workspace_path: str
    template_path: str                     # 模板文件路径
    output_filename: str                   # 输出文件名
    data: Dict[str, Any]                   # 填充数据
    # 可选：图片数据（base64 或路径）
    images: Optional[Dict[str, str]] = None
    # 可选：覆盖样式
    style_overrides: Optional[Dict[str, Any]] = None

class WordTemplateFillResult(BaseModel):
    output_path: str
    filename: str
    file_size_bytes: int
    filled_count: int                      # 实际填充的占位符数量
    unfilled_placeholders: List[str]       # 未填充的占位符（数据缺失）
```

### 4.3 PDF 读取

```python
class PdfPageContent(BaseModel):
    page_number: int
    text: str
    tables: List[List[List[str]]]          # 表格列表，每个表格是二维数组
    images: List[Dict[str, Any]]           # 图片元数据（位置、尺寸）

class PdfReadResult(BaseModel):
    summary: OfficeDocumentSummary
    pages: List[PdfPageContent]
    metadata: Dict[str, Any]               # PDF 元数据（作者、创建时间等）
    form_fields: Optional[List[Dict]] = None  # 如果有表单字段

class PdfDocType(str, Enum):
    PDF = "pdf"  # 新增到 OfficeDocType
```

### 4.4 PDF 生成

```python
class PdfPageSpec(BaseModel):
    title: Optional[str] = None
    paragraphs: List[str] = []
    tables: List[List[List[str]]] = []     # 表格数据
    images: Optional[List[str]] = None     # 图片路径列表

class PdfGenerateRequest(BaseModel):
    workspace_path: str
    filename: str
    pages: List[PdfPageSpec]
    # 页面设置
    page_size: str = "A4"                  # A4 / Letter / Legal
    orientation: str = "portrait"          # portrait / landscape
    margins: Optional[Dict[str, float]] = None  # 边距（cm）

class PdfGenerateResult(BaseModel):
    output_path: str
    filename: str
    file_size_bytes: int
    page_count: int
```

### 4.5 PDF 表单

```python
class PdfFormField(BaseModel):
    name: str                              # 字段名
    type: str                              # text / checkbox / radio / dropdown
    value: Optional[Any] = None            # 当前值
    options: Optional[List[str]] = None    # 下拉/单选选项
    required: bool = False
    read_only: bool = False

class PdfFormReadResult(BaseModel):
    file_path: str
    fields: List[PdfFormField]
    has_xfa: bool                          # 是否有 XFA 表单（动态表单）

class PdfFormFillRequest(BaseModel):
    workspace_path: str
    template_path: str
    output_filename: str
    data: Dict[str, Any]                   # 字段名 → 值
    flatten: bool = False                  # 填充后是否扁平化（不可编辑）
```

---

## 5. 错误处理

### 5.1 新增错误类型

```python
# backend/office/errors.py 扩展

class OfficeTemplateError(OfficeError):
    """Word 模板解析/填充失败"""
    pass

class OfficeTemplateParseError(OfficeTemplateError):
    """模板文件解析失败"""
    pass

class OfficeTemplateFillError(OfficeTemplateError):
    """模板填充失败（数据缺失、类型不匹配等）"""
    pass

class OfficePdfError(OfficeError):
    """PDF 操作失败"""
    pass

class OfficePdfParseError(OfficePdfError):
    """PDF 解析失败"""
    pass

class OfficePdfGenerateError(OfficePdfError):
    """PDF 生成失败"""
    pass

class OfficePdfFormError(OfficePdfError):
    """PDF 表单操作失败"""
    pass
```

### 5.2 错误映射

所有新错误类型添加到 `office_error_to_http_status()` 映射：

| 错误类型 | HTTP 状态码 |
|---------|-----------|
| OfficeTemplateParseError | 400 Bad Request |
| OfficeTemplateFillError | 422 Unprocessable Entity |
| OfficePdfParseError | 400 Bad Request |
| OfficePdfGenerateError | 500 Internal Server Error |
| OfficePdfFormError | 422 Unprocessable Entity |

---

## 6. 安全考量

### 6.1 路径校验

所有新 API 复用现有路径安全机制：

```python
# 模板文件路径校验
file_path = _validate_file_in_workspace(req.template_path, req.workspace_path)

# 输出路径校验
output_path = resolve_output_path(req.workspace_path, OfficeDocType.WORD, req.output_filename)
```

### 6.2 模板注入防护

`docxtpl` 默认启用 Jinja2 沙箱，但需要：

1. 禁用危险标签：`{% import %}`, `{% include %}`
2. 限制变量访问：禁止 `__class__`, `__subclasses__` 等
3. 文件大小限制：模板文件 > 50MB 拒绝

### 6.3 PDF 表单防护

1. 只允许填充已知字段名
2. 拒绝填充 `read_only=True` 的字段
3. 输出文件大小限制

---

## 7. 测试策略

### 7.1 单元测试

| 模块 | 测试文件 | 覆盖内容 |
|------|---------|---------|
| word_template.py | test_word_template.py | 占位符识别、填充逻辑、边界情况 |
| pdf.py | test_pdf.py | 文本提取、表格提取、PDF 生成 |
| pdf_forms.py | test_pdf_forms.py | 表单字段读取、填充、扁平化 |

### 7.2 集成测试

```
backend/tests/integration/test_office_template_integration.py
backend/tests/integration/test_pdf_operations_integration.py
```

覆盖：
- API 路由端到端
- LLM 工具调用链路
- 错误场景

### 7.3 E2E 测试

```
electron/tests/e2e/office-template.spec.ts
electron/tests/e2e/pdf-operations.spec.ts
```

覆盖：
- 用户上传模板 → 分析 → 填充 → 下载
- 用户上传 PDF → 读取内容 → 填充表单

---

## 8. 实施计划

### Phase 1: 基础设施（Week 1）

- [ ] 添加依赖到 requirements.txt
- [ ] 验证 release/win7 Python 3.8 兼容性
- [ ] 扩展 models.py 新数据模型
- [ ] 扩展 errors.py 新错误类型

### Phase 2: Word 模板化（Week 2）

- [ ] 实现 word_template.py
  - [ ] analyze_word_template()
  - [ ] fill_word_template()
- [ ] 添加 API 路由
- [ ] 单元测试 + 集成测试

### Phase 3: PDF 读取+生成（Week 3）

- [ ] 实现 pdf.py
  - [ ] read_pdf()
  - [ ] generate_pdf()
- [ ] 添加 API 路由
- [ ] 单元测试 + 集成测试

### Phase 4: PDF 表单（Week 4）

- [ ] 实现 pdf_forms.py
  - [ ] read_pdf_form()
  - [ ] fill_pdf_form()
- [ ] 添加 API 路由
- [ ] 单元测试 + 集成测试

### Phase 5: LLM 工具集成（Week 5）

- [ ] 扩展 office_tools.py
- [ ] 工具 schema 定义
- [ ] 工具测试

### Phase 6: 前端 + E2E（Week 6）

- [ ] 前端模板分析 UI
- [ ] 前端 PDF 预览 UI
- [ ] E2E 测试
- [ ] 用户文档

### Phase 7: release/win7 同步（Week 7）

- [ ] Cherry-pick 到 release/win7
- [ ] 解决 Python 3.8 兼容性冲突
- [ ] 验证测试通过

---

## 9. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| PyMuPDF Python 3.8 兼容性问题 | 中 | 高 | 提前验证 wheel 可用性，备选 pdfplumber |
| docxtpl 模板注入漏洞 | 低 | 高 | 启用 Jinja2 沙箱，限制标签 |
| PDF 表单 XFA 不支持 | 中 | 中 | 明确文档说明只支持 AcroForm |
| 大文件性能问题 | 中 | 中 | 文件大小限制，流式处理 |

---

## 10. 未来扩展

本设计不覆盖但未来可扩展：

1. **Excel 模板化**：类似 Word，使用 `openpyxl` 扩展
2. **PPT 模板化**：使用 `python-pptx` 扩展
3. **PDF 数字签名**：使用 `pyHanko` 或 `pysslpdf`
4. **Office → PDF 转换**：使用 `libreoffice --headless` 或 `docx2pdf`
5. **OCR 扫描件识别**：使用 `pytesseract` + `pdf2image`

---

## 11. 验收标准

### 11.1 Word 模板化

- [ ] 能正确识别 `{{变量名}}` 占位符（正文、表格、页眉页脚）
- [ ] 能填充文本、图片、日期数据
- [ ] 未填充的占位符能报告缺失字段
- [ ] 模板注入攻击被阻止

### 11.2 PDF 读取

- [ ] 能提取文本（包括多栏布局）
- [ ] 能提取表格（保持结构）
- [ ] 能提取图片元数据
- [ ] 能读取 PDF 元数据

### 11.3 PDF 生成

- [ ] 能从结构化数据生成 A4 PDF
- [ ] 支持标题、段落、表格
- [ ] 支持中英文混排

### 11.4 PDF 表单

- [ ] 能读取 AcroForm 表单字段
- [ ] 能填充文本、复选框、下拉框
- [ ] 支持表单扁平化

---

## 12. 附录

### 12.1 依赖版本锁定

```txt
# requirements.txt 新增
docxtpl>=0.20.0       # Word 模板，~0.5MB
PyMuPDF>=1.25.0       # PDF 读取+表单，~15MB
reportlab>=4.0.0      # PDF 生成，~3MB

# requirements-py38.txt 新增（release/win7）
docxtpl>=0.20.0       # 验证 Python 3.8 兼容
PyMuPDF>=1.25.0       # 验证 Python 3.8 wheel
reportlab>=4.0.0      # 纯 Python，无兼容性问题
```

### 12.2 API 示例

**Word 模板分析**：

```http
POST /api/v1/office/word/analyze-template
Content-Type: application/json

{
  "workspace_path": "/home/user/workspace",
  "template_path": "/home/user/workspace/contract-template.docx"
}
```

响应：

```json
{
  "file_path": "/home/user/workspace/contract-template.docx",
  "placeholders": [
    {
      "name": "客户姓名",
      "raw_tag": "{{客户姓名}}",
      "type": "text",
      "location": "body",
      "paragraph_index": 5
    },
    {
      "name": "合同金额",
      "raw_tag": "{{合同金额}}",
      "type": "text",
      "location": "table",
      "table_index": 0,
      "row_index": 1,
      "col_index": 1
    }
  ],
  "summary": {...},
  "has_jinja_control": false
}
```

**Word 模板填充**：

```http
POST /api/v1/office/word/fill-template
Content-Type: application/json

{
  "workspace_path": "/home/user/workspace",
  "template_path": "/home/user/workspace/contract-template.docx",
  "output_filename": "contract-2026-001.docx",
  "data": {
    "客户姓名": "张三",
    "合同金额": "100,000.00"
  }
}
```

**PDF 读取**：

```http
POST /api/v1/office/pdf/read
Content-Type: application/json

{
  "workspace_path": "/home/user/workspace",
  "file_path": "/home/user/workspace/report.pdf"
}
```

**PDF 表单填充**：

```http
POST /api/v1/office/pdf/fill-form
Content-Type: application/json

{
  "workspace_path": "/home/user/workspace",
  "template_path": "/home/user/workspace/form.pdf",
  "output_filename": "form-filled.pdf",
  "data": {
    "name": "张三",
    "age": 30,
    "agreed": true
  },
  "flatten": false
}
```
