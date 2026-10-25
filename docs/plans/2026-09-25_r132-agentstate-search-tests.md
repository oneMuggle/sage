# R132：Agent ReAct 状态机 + 搜索技能单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；domain 纯净层约定（零外部依赖）
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`domain/agent.py`（73 行，ReAct 状态机枚举 + 迁移表 + frozen 决策值
对象——编排核心的状态合法性契约）与 `skills/builtin/search.py`
（73 行，搜索技能：context 工具分派 / 结果格式化 / 失败透传）此前
零测试。

## 覆盖矩阵（约 19 例）

### `backend/tests/unit/domain/test_agent_state.py`（12 例）

1. 六态枚举值齐全；2. initial() = IDLE；3. **迁移表逐边断言**：
   IDLE→THINKING ✓、THINKING→{ACTING,DONE,FAILED} ✓、ACTING→
   {OBSERVING,FAILED} ✓、OBSERVING→{THINKING,DONE,FAILED} ✓；
4. **非法迁移**：IDLE→ACTING/DONE/FAILED ✗、ACTING→THINKING ✗、
   DONE/FAILED → 任意 ✗（终态）；5. AgentDecision frozen 不可变 +
   字段缺省 None。

### `backend/tests/unit/skills/test_builtin_search.py`（7 例）

1. schema 契约：name=search、triggers 含中英文、required=[query]；
2. context 无 web_search → "搜索工具不可用"；3. 成功路径：fake 工具
   返回 results → 格式化文本（序号标题/缩进 snippet/🔗 url）、metadata
   含 query 与 count；4. 空结果 → "没有找到相关结果"；5. 工具失败 →
   error 透传；6. limit 缺省 5 透传；7. title 缺省 "无标题"、无 url
   不输出链接行。

## 验证

- pytest 新文件 + 邻近用例；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
