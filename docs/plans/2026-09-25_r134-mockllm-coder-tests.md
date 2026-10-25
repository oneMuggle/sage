# R134：MockLLMAdapter + 编程技能单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；LLMPort 内存实现（sage-core 共享包）/ 
  内置技能
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`adapters/out/llm/mock_adapter.py`（98 行，LLMPort 内存实现：顺序消费
responses、耗尽回退 default、调用记录、assert_called_with、reset）与
`skills/builtin/coder.py`（90 行，编程技能五动作 prompt 构建 + LLM
分派 + 无 LLM 模拟回退）此前零测试。

## 覆盖矩阵（约 19 例）

### `backend/tests/unit/adapters/test_mock_llm_adapter.py`（11 例）

1. chat 顺序消费 responses；2. 耗尽后回退 default_content；
3. calls 记录 messages/tools/tool_choice；4. chat_stream 逐字符 yield
default_content 并记录 stream=True；5. assert_called_with：messages
精确比较、kwargs 字段比较、未调用抛 AssertionError、不匹配抛
AssertionError；6. reset 清记录 + 索引归零（responses 可重放）；
7. 结构一致：实例可赋给 LLMPort 注解（模块尾部已断言）。

### `backend/tests/unit/skills/test_builtin_coder.py`（8 例）

1. schema：name=coder、required=[action]、action 枚举五值；
2. 五动作 prompt 构建（write 用 requirement、其余用 code 围栏）；
3. language 缺省 python；4. 未知 action → "未知操作"；5. 无 LLM →
mock 回退（metadata.mock=True）；6. 有 LLM → complete(prompt) 结果
作为 content、metadata 无 mock 键；7. LLM 抛异常 → "代码生成失败"。

## 验证

- pytest 新文件 + 邻近用例；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
