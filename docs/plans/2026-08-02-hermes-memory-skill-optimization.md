# 2026-08-02 记忆沉淀与技能使用优化（借鉴 hermes-agent）

## 背景与目标

对比 hermes-agent 的自改进架构，sage 在"记忆沉淀"与"技能使用"存在真实差距：

| 领域 | hermes-agent | sage 现状 | 差距 |
|------|-------------|-----------|------|
| 用户画像 | `USER.md` 独立存储，冻结快照，始终注入 | `MemoryContext.core` 字段存在但仅来自检索命中（importance≥8），无持久画像库 | **大** |
| 记忆写入路径 | 分类路由（profile vs 环境事实） | 统一写入三层记忆，无画像/事实分流 | **中** |
| 技能使用跟踪 | `.usage.json` 持久化 use/view/patch 统计 | `bump_usage()` 存在但**未接入执行路径**，仅内存态，DB `skills.usage_count` 列闲置 | **大** |
| 技能学习闭环 | nudge + curator + background review | 无 | 待后续 |

**本计划范围**（本次实施）：
1. **UserProfileStore 用户画像** — 新建持久画像库 + 冻结快照 + 分类路由
2. **技能使用跟踪** — 接入执行路径 + DB 持久化
3. **技能 Nudge** — 复杂轮次后提示（低风险）
4. 记忆提取异步化、curator、background review、/learn 命令 → 记为后续工作（见 §5）

## 涉及的文件

### 新增
- `backend/memory/user_profile.py` — UserProfileStore（冻结快照 + 字符上限 + 去重）
- `backend/tests/unit/test_user_profile.py` — 用户画像单测
- `backend/tests/unit/test_skill_usage_tracking.py` — 技能使用跟踪单测

### 修改
- `backend/data/database.py` — 新增 `user_profile` 表
- `backend/adapters/out/memory/adapter.py` — `store_profile()` 扩展方法 + `retrieve()` 从画像库填充 `core`
- `backend/application/services/chat_service.py` — `extract_and_store_memory` 分类路由 + 技能 nudge
- `backend/adapters/out/skill/inproc.py` — bump_usage 接入执行路径 + DB 持久化
- `backend/api/legacy_routes.py` — legacy 路径受益于统一写入（无需大改）
- `backend/domain/memory.py` — MemoryContext 文档同步（core 语义）

## 技术方案

### 1. UserProfileStore（USER.md 概念）

借鉴 hermes `tools/memory_tool.py` 的 `MemoryStore` frozen snapshot 模式：

```python
class UserProfileStore:
    DEFAULT_CHAR_LIMIT = 1400  # 用户画像注入上限（冻结快照）
    def load(self) -> None              # 会话启动时加载，计算冻结快照
    def add(self, content, category, importance) -> Optional[str]  # 写入（去重+限长）
    def list(self) -> List[Dict]
    def delete(self, profile_id) -> bool
    def get_snapshot(self) -> str       # 冻结快照（字符受限）
    def get_core_items(self) -> List[Dict]  # 供 MemoryContext.core 注入
    def invalidate(self) -> None        # 刷新快照（显式调用）
```

- **存储**：新表 `user_profile(id, content, category, importance, created_at, updated_at)`
- **冻结快照**：`load()` 时计算，写入不更新快照（hermes 语义：中途写入不改 system prompt，保 prefix cache）
- **去重**：写入前检查相似内容（编辑距离/子串），避免画像膨胀
- **安全**：复用 `backend/memory/safety.py::get_scanner()` 严格扫描

### 2. 分类路由

`extract_and_store_memory` 中按 `category` 分流（结构性探测 `store_profile`，不扩展 Protocol）：

```python
if fact.get("category") in ("preference", "goal") and hasattr(memory_port, "store_profile"):
    await memory_port.store_profile(...)
else:
    await memory_port.store(...)
```

### 3. 技能使用跟踪

- `InprocSkillAdapter.execute/execute_command/auto_activate` 成功路径调 `bump_usage(name)`
- 新增轻量持久化：`bump_usage` 时 best-effort 更新 DB `skills.usage_count/last_used_at`（失败只 warning，不影响热路径）
- 前端 `list_skills` 已读 `adapter.usage_count()`，自动受益

### 4. 技能 Nudge（hex 路径）

`ChatService._run_turn_inner` 维护轮次内工具调用计数；工具调用 ≥ 阈值且无技能自动激活时，在 assistant 回复后追加提示（best-effort）。

## 实施步骤

- [x] 步骤 1：计划文档 + 分支
- [x] 步骤 2：database.py 新增 user_profile 表
- [x] 步骤 3：新建 user_profile.py（UserProfileStore）
- [x] 步骤 4：MemoryAdapter 接入（store_profile + core 填充）
- [x] 步骤 5：extract_and_store_memory 分类路由
- [x] 步骤 6：技能使用跟踪接入执行路径 + DB 持久化
- [x] 步骤 7：技能 Nudge
- [x] 步骤 8：单元测试 + 全量验证（pytest 3127 ✓ + vitest 1173 ✓ + tsc 0 ✓）

## 代码审查修复（review agent 反馈）

| 严重度 | 问题 | 修复 |
|--------|------|------|
| HIGH | skill_usage 只写不读, "重启不归零"不成立 | 适配器 `__init__` 从表回填 `_usage_count` |
| MEDIUM | 画像条目挤掉检索命中的高重要性 core 事实 | core 独立预算（画像 3 + 检索 2） |
| MEDIUM | hex 路径未用冻结快照 + 未截断 | `get_core_items()` 改为基于快照条目（char 受限） |
| MEDIUM | 画像库不可用时偏好事实丢失 | `store_profile` 降级到 `store()` |
| MEDIUM | MagicMock 结构探测误判 | 类级 `hasattr(type(...))` 探测 |
| LOW | nudge 文本喂给记忆提取器 | 提取器入参剥离 nudge 后缀 |
| LOW | importance 未钳制 | `add()` 钳制到 1-10 |

## 风险评估

| 风险 | 应对 |
|------|------|
| 画像库膨胀（重复写入） | 去重 + 字符上限 + 快照截断 |
| store_profile 未实现（mock） | 结构性探测 `getattr`，缺失降级到通用 store |
| 技能 usage DB 写入失败 | best-effort，绝不抛错 |
| Nudge 破坏对话 | best-effort，注入失败降级为空 |
| prompt cache 破坏 | 画像用冻结快照，中途写入不更新快照 |

## 后续工作（不在本次范围）

- 记忆提取异步化（legacy 已非阻塞，hex 收益有限，留待 API_MODE=hex 启用后）
- Skill curator 生命周期（active/stale/archived）
- Background review 自主进化
- /learn 命令（需 skill_manage 创建工具 + 前端 UI）
- 工具输出裁剪（压缩前置）
