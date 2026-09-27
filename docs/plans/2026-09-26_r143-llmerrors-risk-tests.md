# R143：LLM 错误模型 + 工具风险分级单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；A1 工具风险分级（OpenWorker 对标）/
  LLM 错误七分类
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`domain/errors.py`（61 行，LLMErrorType 七分类 + LLMError dataclass
异常：手动 super().__init__ 让 str/args 携带信息 + to_dict 序列化）与
`domain/risk.py`（109 行，A1 工具风险分级：override > declared > 按名
兜底表 > 元数据启发式 > READ 的五级优先链）此前零测试。

## 覆盖矩阵（约 22 例）

### `backend/tests/unit/domain/test_llm_errors.py`（8 例）

1. 七分类枚举值；2. LLMError 是 Exception 且 str(err) 携带 message
（__post_init__ 手动 super 的回归）；3. to_dict 四键（type 序列化为
snake_case 字符串）；4. status_code/retry_after 可选缺省 None；
5. RATE_LIMITED 携带 retry_after 的形态；6. raise/except 往返。

### `backend/tests/unit/domain/test_risk.py`（14 例）

1. 五级优先链逐级断言：overrides 最先（返回 None 则让位）、declared
次之、按名兜底表（write_file/memory_save→WRITE_LOCAL、bash→EXEC、
web_search/web_fetch/http_download→EXTERNAL）、metadata
requires_approval → EXTERNAL（对象属性与 Mapping 键两形态）、最终
READ 兜底；2. is_consequential：READ False、其余 True；3. RiskClass
四值；4. 兜底表 frozenset 内容。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
