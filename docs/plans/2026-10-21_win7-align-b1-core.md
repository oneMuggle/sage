# B1：backend/core+adapters 对齐到 main

- 日期：2026-10-21
- 分支：`chore/win7-align-b1-20261021` → `release/win7`
- 属于 main ↔ win7 对齐方案（`docs/mcp-win7-main-alignment-plan.md`）的 P2，第一批

## 1. 范围

P2 原定 B1 = `backend/core+adapters` 的 11 个需动作文件。实测后修正为 **12 个文件**：

| 类别 | 件数 | 说明 |
|---|---|---|
| 源文件（取 main 版本） | 9 | adapters/out 下 7 个 + `core/legacy/llm_client.py` |
| 测试文件（取 main 版本） | 2 | `test_llm_client_reasoning_params.py`、`test_llm_client_remaining.py` |
| 删除 win7 独有测试 | 1 | `test_inproc_adapter_required_validation.py`（302 行，main 上不存在） |

## 2. 为什么和原计划不一样

### 2.1 `agent.py` 被移出本批

原计划包含 `backend/core/legacy/agent.py`（main 侧 184+/91-）。直接搬会挂：

```
AttributeError: STEP_DONE
```

win7 的 `AgentState` 故意没有 `STEP_DONE` 成员，win7 自己的测试里就写着
「win7 差异: AgentState 无 STEP_DONE 成员（step-by-step 事件流未同步）」。
而 `backend/core/legacy/agent_state.py` 与 `backend/api/legacy_routes.py`
在 parity 里都是 **`intentional`**（已登记的必要差异）。

也就是说，`agent.py` 的 `real` 分级是文件级的，但它的依赖是一条**已登记决策**。
搬运它等于单方面反转该决策，还会波及 B2 域的 `legacy_routes.py` 与前端事件流。
因此 `agent.py` 单列为「事件流批次」，需要单独评审。

### 2.2 必须连测试一起搬

只搬源码时，win7 的旧测试会断言旧行为：

| 用例 | 结果 |
|---|---|
| `test_inproc_adapter_required_validation`（2 个） | 该文件 main 上不存在，断言 main 已移除的旧行为 |
| `test_llm_client_reasoning_params` | main 已同步改过 |
| `test_llm_client_remaining` | 同上（URL 尾斜杠归一化） |

基线对照（干净 win7 `9cac234a5` 跑同样 4 个测试文件）：只有 `test_default_skills_dir`
失败，是既有问题，与本批次无关。

结论：**批次的最小单元是「源文件 + 它的测试」，不是目录。**

## 3. 验证

| 闸门 | 结果 |
|---|---|
| `check_py38_compat.py`（py3.8 env） | 0 violations |
| `py38_compat_rewrite.py --check` | 0 changed（已无漂移） |
| `ruff check` | All checks passed |
| `pytest` 相关 4 个测试文件（py3.8 env） | 87 passed，仅剩既有的 `test_default_skills_dir` |

依赖闭包单独核过：这 9 个文件在 main 侧的 intra-repo 依赖，win7 一个都不缺
（不是缺模块，纯粹是测试版本没跟上）。

## 4. 回滚

单批 12 文件，`git revert` 即可；不涉及 schema、不涉及发布流程。
