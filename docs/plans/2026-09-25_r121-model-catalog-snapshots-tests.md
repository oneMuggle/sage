# R121：model_catalog snapshots 纯函数单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；model_catalog DSH 专项既有成果
- **范围**：后端 only（backend/tests/unit/api/test_model_catalog_snapshots.py
  新增，零生产代码改动）

## 0. 结论速览

`backend/model_catalog/snapshots.py`（88 行）承载目录快照的字段选择与
合并语义：`selected_fields`（price 展开去重）、`merge_fields`
（"缺失/None 源字段永不抹值" + clear_fields 回滚指令 +
source_updated_at 三态），是快照审计正确性的核心。异常类
CatalogConflict/CatalogNotFoundError 与 API 的 409/404 映射契约、
digest 的稳定性也一并钉死。

## 覆盖矩阵（约 20 例）

1. **selected_fields**：price → 两条子路径展开；重复输入去重保序；
   空列表 / 非法字段 → ValueError；
2. **field_value**：price 子路径从 price dict 读取、缺失 → None；
   普通路径、缺失 → None；
3. **canonical_json**：键排序、紧凑分隔、中文不转义；**digest**：同
   记录集稳定、记录变化 → 摘要变化；
4. **merge_fields**（核心）：
   - 选字段更新：after 新值写入，未选字段保留 before 旧值
     （after 带不同 quantization 也不得串入）；
   - after 值为 None 且不在 clear_fields → 保留旧值（永不抹值）；
   - clear_fields 显式置 None（内部回滚指令）；
   - before=None 新建：未选非 price 字段置 None；price 只保留选中
     子路径（未选子路径不得从 after 串入）；currency 默认 USD 保持；
   - source_updated_at 三态：clear → None；fields 非空且 after 带值 →
     采用 after；fields 非空但 after 为 None → 保留旧值；
   - 结果恒为合法 CandidateModel（model_validate 通过）；
5. **异常类**：CatalogConflict/CatalogNotFoundError 可实例化、继承
   Exception（API 409/404 映射契约的存在性护栏）；
6. **utc_now**：以 Z 结尾、可被 datetime.fromisoformat 解析。

## 验证

- pytest 新文件；ruff（CI 同版本 0.4.4）。

## 明确不做

- 不测 snapshots 的持久化/网络调用（该文件本身无 IO，路由层已有用例）。
