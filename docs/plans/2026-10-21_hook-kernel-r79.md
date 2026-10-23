# R79 — hook 生命周期收编到插件内核

> 日期：2026-10-21
> 轮次：plugin-evo R79
> 上游：`docs/plans/2026-10-21_plugin-kernel-r78.md`（内核骨架，已交付）
> 分支 / worktree：`feat/plugin-kernel-r78` → `.worktrees/feat-plugin-kernel-r78`
> PR：#2206（R78 已入该分支，R79 追加提交）

---

## 1. 目标

把「用户级 + 项目级钩子」的生命周期交给内核托管，消灭 14 处调用点各自拼装的现状；
**执行语义零变更**，并用「旧路径 vs 内核路径」逐字段对照测试作为验收门。

## 2. 现状问题（实测）

| 事实 | 证据 |
| --- | --- |
| 14 处调用点各自 `load_hooks()` + `run_event_hooks()` | `grep -rn "run_event_hooks" backend/api` |
| 钩子列表是临时变量，无人持有 | `legacy_routes.py:530-531`、`:2133-2134` 等 |
| 无法回答"当前生效的有哪些钩子" | 无统一注册表 |
| 卸载/热更新只能靠重启 | 列表随调用点作用域存亡 |
| 合并语义分散在 `merger.py` + 各调用点 | 尚无统一装配入口 |

## 3. 设计

### 3.1 分层归属：**hooks 适配内核，而不是内核 import hooks**

内核只做挂载 / 依赖 / 服务 / 事件四件事（R78 §3 D1）。若让
`backend/application/kernel` import `backend.hooks`，内核立刻变成业务组件。
因此 provider 落在 **`backend/hooks/kernel_provider.py`**，依赖方向为
`hooks → application.kernel`（单向，且不违反架构策略的分层要求）。

### 3.2 `KernelHookProvider`

- `start(hooks)`：把钩子集合装载成一个内核插件 `core-hooks`；`apply` 里把自身
  注册为命名服务 `hooks`，并把服务释放器挂进 `EffectScope`
- `reload(hooks)`：卸载 + 装载（配置热更新）
- `stop()` / `shutdown()`：撤销服务与全部副作用
- `active_hooks()`：唯一事实源；未装载时为空
- `dispatch(event, tool, payload)`：委托 `run_event_hooks`，语义完全一致
- `dispatch_sync(...)`：与 `run_event_hooks_sync` 同样的 fail-open 规则

### 3.3 迁移入口 `fire_hooks(...)`

```python
outcome = await fire_hooks(
    "user_prompt_submit", "", payload,
    hooks_loader=lambda: load_hooks(SettingsRepository()),
    provider=kernel_provider,
)
```

- `SAGE_KERNEL_HOOKS` 关闭（**默认**）或未提供 provider → 旧路径，逐字节等价于今天的调用点
- 开启且提供 provider → 内核路径

调用点迁移只需替换两行，且默认行为不变，可逐点灰度。

### 3.4 本轮**不改任何调用点**

`legacy_routes.py` 正在被 C 系列拆分（dsh-opt R32 仍在交付中），此刻改动会制造
必然的合并冲突。迁移与 R80（tools 收编）同批进行，届时 `fire_hooks` 直接替换
那 14 处即可——本轮已把"替换后行为不变"这件事用对照测试锁死。

## 4. 测试矩阵

| 组 | 覆盖 | 用例数 |
| --- | --- | --- |
| Lifecycle | start / stop / reload / 幂等 / 未装载 / 卸载后 / shutdown / sync 两分支 | 9 |
| **Parity** | 10 组钩子配置 × 旧路径 vs 内核路径逐字段相等；reload 后仍相等 | 11 |
| FireHooks | 默认走旧路径 / 开关走内核 / 无 provider 回退 / 开关解析 | 4 + 7 参数化 |

对照配置覆盖：空列表、feedback、deny、modify、抛错 fail-open、feedback+deny、
modify+deny、双 feedback 聚合、matcher 不命中、event 不匹配。

## 5. 验收门

```bash
cd backend
python -m pytest tests/unit/test_hooks_kernel_provider.py -q
python -m pytest tests/unit/test_hooks*.py -q        # 存量 7 个 hooks 测试无回归
cd .. && node scripts/architecture-check.mjs
ruff check backend/hooks/kernel_provider.py backend/tests/unit/test_hooks_kernel_provider.py
```

## 6. 风险

| 风险 | 处置 |
| --- | --- |
| 改动影响既有 hooks 行为 | 本轮零调用点改动；provider 只新增入口 |
| 双路径语义漂移 | 对照测试逐字段断言（含 fail-open 分支） |
| 内核被业务污染 | provider 放在 hooks 侧，依赖单向 |
| 卸载残留 | 服务注册走 `EffectScope`，`test_stop_clears_hooks_and_service` 直接断言 |
