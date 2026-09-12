# 自进化体系总览（Self-Evolution Architecture）

> Sage 的「自我进化」能力面总览：学习循环各组件、数据流与环境变量。
> 对标参照：[hermes-agent](https://github.com/NousResearch/hermes-agent)。
> 本文由 2026-09 对标批次（Round 1-16）沉淀，来源计划见 `docs/plans/`。

## 组件地图

```
对话轮次（legacy run_loop / hex ChatService）
   │
   ├─ 循环守卫 ──────── 空响应重试（两侧）/ 工具复读拦截（legacy）
   │                     SAGE_EMPTY_RESPONSE_MAX_RETRIES / SAGE_TOOL_REPEAT_*
   │
   ├─ 记忆写入 ──────── MemoryExtractor（LLM 事实抽取）→ 三层记忆
   │   │                 └─ VectorStore（OnnxEmbedder 512 / ModelEmbedder
   │   │                    HTTP / HashEmbedder 256，按 embedder 维度分表）
   │   └─ 审阅信号 ──── 复读/复杂回合 → ReviewQueue
   │
   ├─ 会话检索 ──────── session_search 工具（messages_fts，jieba 分词）
   │
   └─ 压缩 ─────────── replace_prefix_with_continuation
                         └─ 前缀归档进派生会话（session_lineage 谱系）

后台（每 tick / cron）
   ├─ ReviewQueue worker ── LLM 初筛（needs_screening）→ SkillDraft
   │                          → 人工审批 → safe_writer 落盘
   │                          → provenance frontmatter + 审计台账
   ├─ 巡检 cron（每周六）── ConsolidationService.scan → merge/revise 建议
   │                          → 自动生成修订草稿（pending 待批）+
   │                          archive 建议落 consolidation_note 台账
   ├─ 偏好学习 cron ────── 关键词基线 + LLM 用户消息采样 → 偏好落库
   └─ 随时手动 ────────── GET/POST /skills/consolidation/*、
                            POST /skills/{name}/rollback、
                            GET /skills/{name}/audit
```

## 学习闭环（hermes 对照）

| 环节 | hermes | Sage |
| --- | --- | --- |
| 记忆 | agent 自主编辑 MEMORY.md/USER.md + nudge | Mem0 式抽取 + preferences 表 + 巡检建议 |
| 技能创建 | 复杂回合后自动 + 人工确认 | 审阅初筛 → 草稿 → **人工审批**（哲学差异点） |
| 技能改进 | 使用中就地 patch | 巡检建议 → 修订草稿 → 审批 |
| 技能维护 | curator（备份/台账/回滚/pin） | Round 3/5 对齐：台账/回滚/pin/provenance |
| 会话检索 | FTS5 + LLM 综合 | session_search 工具（FTS5 + LIKE 回退） |
| 远程 | 25+ 平台网关 | Telegram MVP（对话/审批转发/命令） |

## 环境变量速查

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SAGE_EMBEDDER` | hash | `onnx` / `model`（HTTP）显式选择语义嵌入 |
| `EMBED_BASE_URL`/`EMBED_API_KEY`/`EMBED_MODEL` | — | ModelEmbedder 端点（同 wiki 约定） |
| `SAGE_VEC_BACKFILL_MAX` | 500 | 启动时向量回填上限 |
| `SAGE_EMPTY_RESPONSE_MAX_RETRIES` | 2 | legacy 空响应守卫重试次数（0 关闭） |
| `SAGE_TOOL_REPEAT_SOFT_LIMIT` / `HARD_LIMIT` | 3 / 5 | 复读守卫阈值（0 关闭） |
| `SAGE_GW_HISTORY_TOKEN_BUDGET` | 4000 | 网关对话历史 token 预算（<=0 关闭） |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_CHAT_IDS` | — | 网关启用 + 白名单（必需，缺一不启动） |

## 剩余已知差距（Round 22 时点）

1. **hex-legacy 双栈**：行为对齐进行中（空响应守卫已对齐），结构性
   收敛（单一循环实现）仍是大工程；
2. **网关平台**：BaseGateway 抽象基类（#663）与配置持久化（#682）已铺路，
   Discord/Slack 适配仍未接入；
3. **curator LLM 巡检**：cron 每周一次 + 手动触发（#681）；增量/事件驱动
   仍未做。

## 已收口差距（Round 17-18）

- ~~consolidation/pin 管理面~~：技能 pin 钉住 + 固化巡检前端接入（#668 R17-A1）；
- ~~压缩谱系「查看归档」入口~~：compact toast 直达归档弹窗（#668 R17-A2）；
- **codebase_search 检索质量**：函数边界分块 v2（#686）→ FTS5+加权 RRF
  混合检索（#693）→ end_line 透出/嵌入并行/单批重试（#696）。

## 集成验证记录（Round 16，2026-09-11）

15 轮交付叠加后的跨组件回归验证（本轮 diff 之外全部既有面）：

- 范围：Round 1-15 全部新增模块的 34 个测试文件 + 关键集成面
  （审批 API、provenance 注入、技能回滚、压缩谱系、管理面、wiki 流）；
- 结果：**281 passed, 0 failed**；
- 已知环境性失败（与本体系无关）：`test_bash_tool.py` 17 例
  （Windows safe_writer fail-closed）、wiki 流 4 例（O_NOFOLLOW
  Windows 不可用）、`test_review_queue.py` 14 例（Windows 文件锁）——
  均与 main 基线逐一对齐确认；
- CI（ubuntu）全部绿色，覆盖率门禁 ≥80% 持续满足。
