# R133：BibTeX 解析工具 + 外部计算领域模型单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；Round 9 引用闭环 / 六边形 compute 端口
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/office_bibtex_tool.py`（74 行，office_parse_bibtex：纯文本解析
封装，READ/无工具上下文）与 `domain/compute.py`（103 行，外部计算领域
模型：ComputeSpec/Request/ErrorType/Error/Result 契约）此前零测试。

## 覆盖矩阵（约 14 例）

### `backend/tests/unit/tools/test_office_bibtex_tool.py`（6 例）

1. schema：name=office_parse_bibtex、required=[text]、risk=READ、
   requires_tool_context=False；2. text 缺失/非字符串/纯空白 →
   text_required；3. 合法 .bib 文本 → count + references 全字段
   （key/type/authors）；4. 解析异常 → parse_failed 前缀；
5. 全噪声文本（无可解析条目）→ parse_failed（OfficeParseError 透传）；
6. 多条目 count 正确。

### `backend/tests/unit/domain/test_compute.py`（8 例）

1. ComputeSpec/Request 缺省工厂字段；2. ComputeErrorType 六分类值；
3. ComputeError details 缺省空 dict；4. ComputeResult 成功形态
（output + error None）；5. 失败形态（error 填充）；6. Enum 为 str
子类可直接比较；7. request_id/timeout_ms 可选语义；8. 错误实例可作
Result 字段往返。

## 验证

- pytest 新文件 + 邻近用例；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
