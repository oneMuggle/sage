# 技能自动整理、优化与去重进化机制

> **状态**：M1–M4 核心功能已实施（74 测试通过），剩余集成与自动化待补
> **日期**：2026-11-25
> **目标**：为 Sage 技能系统引入自动去重、质量评分、渐进式发现与自进化机制

---

## 一、背景与目标

### 1.1 现状诊断

Sage 当前技能系统已具备：

| 模块 | 文件 | 能力 |
|------|------|------|
| **生命周期三态** | `lifecycle.py` | active / stale / archived 即时计算 + 持久化 |
| **LLM 巡检** | `consolidator.py` | 手动触发，LLM 产出 merge/archive/revise 建议 |
| **审计台账** | `audit.py` | append-only 记录，支持增量水位 |
| **Pin 防归档** | `lifecycle.py` | 钉住的技能不出现在 archive 建议中 |
| **文件发现** | `discovery.py` | 扫描 `~/.sage/skills/` 注册 SKILL.md |
| **使用统计** | `usage.py` | `usage_count` + `last_used_at` |
| **Review Queue** | `review_queue.py` | 后台事件队列 + LLM 生成技能草稿 |
| **热重载** | `skill_md/loader.py` | MD5 检测变更，无需重启 |

**缺口（对比主流平台）**：

1. **去重是纯 LLM 建议**：无结构化相似度计算，依赖 prompt 质量
2. **无质量评分**：`usage_count` 是原始计数，无成功率、用户满意度等维度
3. **全量加载**：所有技能元数据一次性注入上下文，技能多时 token 浪费
4. **无自进化闭环**：巡检产出建议后需人工处理，无自动迭代优化
5. **无技能组合**：不能将多个小技能自动组合为更大粒度的能力

### 1.2 目标

对标主流 AI 应用（Claude Tool Search、LangChain Progressive Disclosure、GATE 图演化），分阶段引入：

- **P0**：结构化去重（embedding 相似度 + LLM 确认）
- **P1**：质量评分 + 热/冷路径分层
- **P2**：渐进式发现（按需加载）
- **P3**：执行反馈驱动的自进化闭环

---

## 二、主流平台对标分析

### 2.1 关键参考

| 平台 | 核心机制 | Sage 可借鉴 |
|------|----------|-------------|
| **Claude Tool Search** | Regex/BM25 搜索 + 延迟加载（支持 10000 工具） | 渐进式发现、热/冷分层 |
| **LangChain Skills** | 三级加载（元数据→指令→资源） | 渐进式披露、工具绑定 |
| **GATE (2025)** | Smith-Waterman 结构相似度 + GraphRank 检索 + 自动合并/剪枝 | 去重算法、图演化 |
| **SkillFocus (2026)** | 能力空间分解 + 未解决任务质量优先演化 | 能力维度建模 |
| **BabyAGI** | 反思循环：执行→评估→改进任务列表 | 执行反馈闭环 |
| **SkillWeaver (2025)** | 自主发现→练习→蒸馏为 API | 经验蒸馏 |
| **ChatGPT GPT Store** | 分类浏览 + 社区排行 + 第三方评测 | 质量评分、用户反馈 |
| **Dify** | 集中技能库 + 版本控制 + AI 辅助创建 | 版本管理、编辑一次全局生效 |

### 2.2 Sage 差异化定位

Sage 是**本地桌面 AI 助手**，技能以 SKILL.md 指令文件为主（非代码工具），约束：

- 技能数量级：10–100（不是 10000）
- 技能是 prompt + 触发条件 + 允许工具列表
- 已有 LLM 巡检基础设施（`consolidator.py`）
- 需保持「建议→人工确认」的可审计契约

---

## 三、技术方案

### 3.1 P0：结构化去重

**目标**：用 embedding 相似度替代纯 LLM 文本比对，提高去重准确率。

#### 3.1.1 相似度计算

```python
# backend/skills/similarity.py

class SkillSimilarityService:
    """基于 embedding 的技能相似度计算"""

    def __init__(self, embedding_client):
        self.embedding_client = embedding_client
        self._cache: Dict[str, np.ndarray] = {}

    async def compute_embedding(self, skill: Skill) -> np.ndarray:
        """技能向量化：description + when_to_use + triggers 拼接"""
        text = f"{skill.description}\n{skill.when_to_use}\n{' '.join(skill.triggers)}"
        if skill.name not in self._cache:
            self._cache[skill.name] = await self.embedding_client.embed(text)
        return self._cache[skill.name]

    async def find_duplicates(
        self, skills: List[Skill], threshold: float = 0.85
    ) -> List[Tuple[str, str, float]]:
        """返回超过阈值的技能对及其相似度"""
        embeddings = {s.name: await self.compute_embedding(s) for s in skills}
        pairs = []
        names = list(embeddings.keys())
        for i, a in enumerate(names):
            for b in names[i+1:]:
                sim = cosine_similarity(embeddings[a], embeddings[b])
                if sim >= threshold:
                    pairs.append((a, b, float(sim)))
        return sorted(pairs, key=lambda x: -x[2])
```

#### 3.1.2 增强 ConsolidationService

在现有 LLM 巡检前加一步预筛选：

```python
# 现有 consolidator.py 增强

async def scan(self, skills, pinned_names=None):
    # Step 1: 结构化预筛选（embedding 相似度）
    duplicate_pairs = await self.similarity_service.find_duplicates(skills)

    # Step 2: 将相似度结果注入 LLM prompt（作为先验证据）
    # 让 LLM 确认/否决，而非从零发现
    duplicate_context = "\n".join(
        f"- {a} ↔ {b} (相似度 {sim:.2f})"
        for a, b, sim in duplicate_pairs
    )

    prompt = (
        "以下是技能相似度分析结果（embedding cosine similarity）...\n"
        f"{duplicate_context}\n\n"
        "请基于上述证据，确认哪些应该合并，并补充理由..."
    )
```

**收益**：LLM 不再需要从零发现重复，而是确认/否决结构化预筛结果，准确率提升、token 消耗降低。

#### 3.1.3 降级策略

embedding 模型未配置时降级到 TF-IDF 关键词匹配：

```python
def find_duplicates_tfidf(self, skills, threshold=0.80):
    """无 embedding 时的降级方案"""
    from sklearn.feature_extraction.text import TfidfVectorizer
    texts = [f"{s.description} {s.when_to_use}" for s in skills]
    matrix = TfidfVectorizer().fit_transform(texts)
    # ... 余弦相似度计算
```

---

### 3.2 P1：质量评分与热/冷分层

#### 3.2.1 多维质量评分

```python
# backend/skills/scoring.py

@dataclass
class SkillScore:
    """技能质量评分（0–100）"""
    name: str
    overall: float          # 综合分
    usage_freq: float       # 使用频率（归一化）
    success_rate: float     # 执行成功率
    user_satisfaction: float  # 用户评分（thumbs up/down）
    freshness: float        # 最近使用时间衰减
    description_quality: float  # 描述完整度

class SkillScoringService:
    """
    综合评分公式（可调权重）：
    overall = 0.30*usage_freq + 0.25*success_rate + 0.20*satisfaction
            + 0.15*freshness + 0.10*description_quality
    """

    WEIGHTS = {
        "usage_freq": 0.30,
        "success_rate": 0.25,
        "user_satisfaction": 0.20,
        "freshness": 0.15,
        "description_quality": 0.10,
    }
```

#### 3.2.2 热/冷路径分层

借鉴 Claude Tool Search 的 hot path / cold catalog：

| 分层 | 条件 | 加载策略 |
|------|------|----------|
| **Hot path** | `overall >= 70` 且最近 7 天有使用 | 启动时加载元数据 + 触发条件 |
| **Warm** | `overall >= 40` 或 30 天内有使用 | 启动时仅加载名称 + 描述 |
| **Cold** | `overall < 40` 或 60 天无使用 | 仅索引，按需搜索加载 |

---

### 3.3 P2：渐进式发现（按需加载）

借鉴 LangChain 三级加载：

```
Level 1 (Metadata):   name + description + triggers  → 启动时加载
Level 2 (Instructions): 完整 SKILL.md body           → 技能被选中时加载
Level 3 (Resources):  scripts/, references/          → 执行时按需加载
```

#### 3.3.1 实现路径

```python
# backend/skills/progressive_loader.py

class ProgressiveSkillLoader:
    """三级渐进式技能加载"""

    def __init__(self, registry, scoring_service):
        self.registry = registry
        self.scoring = scoring_service

    async def get_initial_context(self) -> str:
        """启动时：仅加载 hot path 技能的 Level 1 信息"""
        hot_skills = await self.registry.get_hot_path_skills()
        return "\n".join(
            f"- {s.name}: {s.description} [触发: {', '.join(s.triggers[:3])}]"
            for s in hot_skills
        )

    async def load_full_skill(self, name: str) -> str:
        """技能被选中时：加载完整 SKILL.md body"""
        return await self.registry.load_skill_body(name)

    async def search(self, query: str) -> List[Skill]:
        """冷路径搜索：BM25 或 embedding 检索"""
        return await self.registry.search_cold_skills(query)
```

#### 3.3.2 上下文注入策略

```
初始上下文（每次对话）:
  - Hot path 技能元数据（~500 tokens / 10 技能）
  - 技能搜索工具描述

技能选中时:
  - 加载完整 SKILL.md body（~2000–5000 tokens）
  - 加载关联工具定义

执行时:
  - 按需加载 scripts/ 和 references/
```

---

### 3.4 P3：执行反馈驱动的自进化闭环

借鉴 BabyAGI 反思循环 + SkillWeaver 经验蒸馏：

#### 3.4.1 反馈采集

```python
# backend/skills/feedback.py

@dataclass
class SkillExecutionFeedback:
    """单次执行的反馈数据"""
    skill_name: str
    session_id: str
    success: bool               # 任务是否完成
    error_type: Optional[str]   # 失败分类
    user_thumbs: Optional[bool] # 用户点赞/踩
    execution_time_ms: int
    token_cost: int

class SkillFeedbackStore:
    """SQLite 持久化反馈"""

    async def record(self, feedback: SkillExecutionFeedback):
        ...

    async def get_stats(self, skill_name: str) -> SkillStats:
        """聚合统计：成功率、平均耗时、用户满意度"""
        ...
```

#### 3.4.2 自动优化触发

```python
# backend/skills/evolution.py

class SkillEvolutionService:
    """基于反馈的技能自动优化"""

    async def check_and_evolve(self, skill_name: str) -> Optional[EvolutionProposal]:
        """
        触发条件（任一满足）：
        - 成功率 < 60% 且执行次数 >= 5
        - 用户满意度 < 50% 且执行次数 >= 10
        - 平均 token 成本高于同类技能 2 倍

        优化策略：
        1. 描述优化：成功率低但执行成功 → 触发条件/描述不够精确
        2. 内容优化：执行失败 → 分析错误模式，建议修订 SKILL.md
        3. 合并建议：两个技能总是被同时调用 → 建议合并
        """
        stats = await self.feedback_store.get_stats(skill_name)
        triggers = self._evaluate_triggers(stats)
        if not triggers:
            return None
        return await self._propose_evolution(skill_name, stats, triggers)
```

#### 3.4.3 进化流程

```
执行反馈记录
     ↓
定期聚合分析（每小时 / 每天）
     ↓
触发现评估 → 未触发 → 结束
     ↓ 触发
LLM 分析失败模式
     ↓
产出 EvolutionProposal（修订建议）
     ↓
写入审计台账（与现有 consolidation 合并）
     ↓
用户审阅 → 批准 → 自动修订 SKILL.md
                → 拒绝 → 记录拒绝原因，不再重复建议
```

---

## 四、涉及文件与模块

### 新增文件

| 文件 | 用途 |
|------|------|
| `backend/skills/similarity.py` | embedding 相似度计算 |
| `backend/skills/scoring.py` | 多维质量评分 |
| `backend/skills/progressive_loader.py` | 三级渐进加载 |
| `backend/skills/feedback.py` | 执行反馈采集与存储 |
| `backend/skills/evolution.py` | 自进化服务 |
| `backend/api/skill_evolution_routes.py` | 进化相关 API |
| `src/widgets/skills/SkillScoreBadge.tsx` | 质量评分 UI 组件 |
| `src/widgets/skills/SkillEvolutionPanel.tsx` | 进化建议面板 |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `backend/skills/consolidator.py` | 注入相似度预筛 |
| `backend/skills/registry.py` | 支持分层加载接口 |
| `backend/skills/usage.py` | 扩展使用统计字段 |
| `backend/api/legacy_skill_draft_routes.py` | 新增进化 API |
| `src/shared/api/types/domainEntityTypes.ts` | 新增 `SkillScore`、`EvolutionProposal` 类型 |
| `src/widgets/skills/SkillCard.tsx` | 展示质量评分 |

---

## 五、实施步骤

### 里程碑 M1：结构化去重（P0）— ✅ 已完成

- [x] 1.1 实现 `SkillSimilarityService`（embedding 计算 + 余弦相似度）
- [x] 1.2 增强 `ConsolidationService.scan()` 注入相似度证据
- [ ] 1.3 前端技能页展示相似度提示（待集成到 SkillCard）
- [x] 1.4 单元测试 + 集成测试（16 通过，3 跳过）

### 里程碑 M2：质量评分（P1）— ✅ 已完成

- [x] 2.1 实现 `SkillScoringService`（5 维评分 + 热/冷分层）
- [x] 2.2 评分 API（`GET /skills/scores` + `GET /skills/{name}/score`）
- [x] 2.3 前端 `SkillScoreBadge` 组件
- [x] 2.4 热/冷路径分层逻辑
- [x] 2.5 Electron IPC 路由 + 前端 API 客户端
- [x] 2.6 单元测试（22 通过）

### 里程碑 M3：渐进式发现（P2）— ✅ 已完成

- [x] 3.1 实现 `ProgressiveSkillLoader`（三级加载 + token 预算控制）
- [x] 3.2 上下文分层（hot path 优先，warm 补充，cold 按需搜索）
- [x] 3.3 技能上下文注入策略（`GET /skills/context`）
- [x] 3.4 冷路径搜索 API（`POST /skills/search`）
- [x] 3.5 单元测试（10 通过）

### 里程碑 M4：反馈与自进化（P3）— ✅ 已完成

- [x] 4.1 实现 `SkillFeedbackStore`（反馈采集 + 统计聚合）
- [x] 4.2 实现 `SkillEvolutionService`（触发条件评估 + 建议生成）
- [x] 4.3 进化检查 API（`POST /skills/evolution/check`）+ 反馈 API（`POST /skills/feedback`）
- [x] 4.4 前端 `SkillEvolutionPanel`（审阅/批准/拒绝面板）
- [ ] 4.5 自动修订 SKILL.md 流程（需用户批准后接入 draft-approve 流程，待后续迭代）
- [x] 4.6 单元测试（12 通过）

---

## 六、风险评估与依赖

### 风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| embedding 模型未配置 | 中 | 降级到关键词匹配（TF-IDF） |
| 质量评分权重不合理 | 低 | 提供环境变量覆盖默认权重 |
| 渐进式加载导致技能选中延迟 | 中 | 预加载 hot path，异步预取 warm |
| 自进化修改 SKILL.md 引入回归 | 高 | 严格走审计台账 + 人工批准 |

### 依赖

- **embedding 服务**：复用现有 `embedding_client`（若已配置）或新增轻量模型
- **SQLite**：复用现有 `backend.data.database` 基础设施
- **审计台账**：扩展现有 `SkillAuditLog`，新增 `evolution_proposal` / `evolution_decision` 事件类型

---

## 七、与现有系统的整合

### 7.1 与 ConsolidationService 的关系

```
现有巡检（LLM 文本分析）
     ↓ 增强
结构化预筛（embedding） + LLM 确认
     ↓ 扩展
+ 执行反馈注入（成功率低的技能优先复审）
     ↓ 进化
+ 自动修订建议（不再只是 merge/archive，还包括内容优化）
```

### 7.2 与审计台账的整合

新增事件类型：

```python
# audit.py 扩展
AUDIT_ACTIONS = [
    ...existing...,
    "evolution_proposal",     # 进化建议产出
    "evolution_approved",     # 用户批准
    "evolution_rejected",     # 用户拒绝
    "score_recalculated",     # 评分重算
]
```

### 7.3 与前端技能页的整合

- 技能卡片增加质量评分徽章（绿/黄/红）
- 新增「进化建议」Tab（类似现有的「审计台账」Drawer）
- 相似度提示：「检测到 X 与 Y 功能重叠（相似度 87%），建议合并」

---

## 八、预期收益

| 指标 | 当前 | 目标 |
|------|------|------|
| 去重准确率 | ~60%（纯 LLM） | >85%（embedding + LLM） |
| 技能发现 token 消耗 | 全量加载 | 降低 60–70% |
| 零使用技能占比 | 未知 | 可量化 + 自动标记 |
| 技能修订周期 | 人工发现 | 自动触发 + 人工批准 |

---

## 九、优先级建议

**推荐实施顺序**：M1 → M2 → M3 → M4

- M1（结构化去重）投入小、收益明确，可快速验证
- M2（质量评分）为后续分层提供数据基础
- M3（渐进式发现）在技能数量增长后价值凸显
- M4（自进化）是长期目标，依赖 M1–M3 的数据积累
