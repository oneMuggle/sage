# 模型目录与成本估算 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立支持离线同步和逐条审核的模型目录，统一上下文解析并接入既有成本统计。

**Architecture:** SQLite 分离目录来源、端点探测、用户覆盖和审核快照；后端负责生效值解析，前端展示并提交操作。复用现有模型发现、聊天请求和 UsageTracker，不新增第二套统计系统。

**Tech Stack:** Python 3.10、FastAPI、Pydantic 2、SQLite、Decimal、React、TypeScript、pytest、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-09-15-model-catalog-design.md`

## Global Constraints

- 当前 worktree：`/home/fz/project/sage/.claude/worktrees/model-catalog-design`；不修改主 checkout 或 release/win7。
- Python 使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`；不向共享环境安装依赖。
- 用户覆盖 > 服务实际探测 > 已审核同步目录 > 内置目录 > 未知，按字段解析。
- 同步仅手动触发；导入必须在本地逐条审核。
- 首版每百万 token 输入/输出价格，不计算缓存和阶梯价格。
- 每项任务执行 RED → GREEN → 回归 → review；commit/push 另需用户授权。
- 本文只表示实施计划，尚未实现或验证业务功能。

## 现状校正与需审阅的细化

代码核查发现已有 `backend/services/usage_tracker.py` 硬编码价格与成本计算，以及 `src/shared/lib/modelWindows.ts` 硬编码窗口。设计文档“无法估算成本”的背景不准确，本次应替换数据来源而非重复实现。

实施口径：

1. 先分别解析 native/service 字段，再取安全最小值。被覆盖纠正的旧来源值不能再次截短结果。
2. service 限制只属于 `(endpoint_id, model_id)`，不得作为跨端点目录值。
3. 协议不等于提供商。OpenRouter 价格限定其报价作用域，不能因同名模型套用到本地或其他收费商。
4. 开源不等于免费。只有用户明确选择“不计 API 成本”才写零价覆盖；未知为 null。
5. 自动模式默认 false，保留现有 maxContext。当前小于 20000 的值部分路径被忽略，修正后会实际生效，需说明这一行为变化。
6. 当前成本算法固定将缓存输入按 10% 收费；首版改为标记 `basic_io` 的基础估算，保留缓存 token 指标，不重算历史费用。
7. “管理员”指已有本地授权的操作者，不新增 RBAC。
8. SHA-256 只校验完整性，不认证来源；导入的“已审核”标记不授予本地生效资格。
9. 首版只接受 USD，自定义 JSON 其他币种明确拒绝，不隐式换汇。

以上细化随本计划一起审阅，未开始实施。

## 文件职责与任务依赖

新增 `backend/model_catalog/`：schemas 数据契约、resolver 纯解析、repository SQL、snapshots 审核、transfer 文件格式、sources 外部来源转换、probes 服务探测、pricing 计价、context 请求窗口。API 放 `backend/api/model_catalog_routes.py`。

前端新增 `src/entities/model-catalog/{types,api}.ts`、`src/pages/ModelCatalog.tsx`、`src/widgets/model-catalog/{CatalogTable,ModelDetails,SnapshotReview}.tsx`。

依赖：Task 1 → 2 → 3；Task 4、5 基于前三项；Task 6 集成；Task 7 验收。各任务的测试和 review 可独立否决，不在未通过时继续叠加。

## Task 1：身份、字段解析和纯计算

**Files:** 创建 `backend/model_catalog/{__init__,schemas,resolver,pricing,context}.py`；测试 `backend/tests/unit/test_model_catalog_core.py`。

**Interfaces:**

```python
class ModelKey(BaseModel):
    provider: str
    model_id: str

class EndpointKey(BaseModel):
    endpoint_id: str
    model_id: str

class Price(BaseModel):
    input_per_million: Decimal | None = None
    output_per_million: Decimal | None = None
    currency: Literal['USD'] = 'USD'

class ContextLimits(BaseModel):
    native: int | None = None
    service: int | None = None

class LayerValues(BaseModel):
    limits: ContextLimits
    price: Price
    source: str
    revision: int

class EffectiveModel(BaseModel):
    limits: ContextLimits
    price: Price
    provenance: dict[str, str]
```

产生 `resolve_layers(layers: list[LayerValues]) -> EffectiveModel`、`estimate_basic(price: Price, input_tokens: int, output_tokens: int) -> Decimal | None`、`effective_window(limits: ContextLimits, automatic: bool, fixed: int) -> int`。layers 按高到低优先级传入，只使用非空字段；repository 在调用前按报价作用域过滤。

- [ ] 写失败测试：字段独立覆盖、删除覆盖恢复继承、同名端点隔离、未知与零价区别。

```python
def test_price_and_unknown():
    p = Price(input_per_million='2', output_per_million='8')
    assert estimate_basic(p, 1000, 500) == Decimal('0.006')
    assert estimate_basic(Price(), 1000, 500) is None

def test_unknown_auto_has_conservative_default():
    assert effective_window(ContextLimits(), True, 128000) == 4096
```

- [ ] RED：`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_model_catalog_core.py -q`，预期模块缺失失败。
- [ ] 实现：Decimal 字符串序列化；拒绝负价、NaN、Infinity；上下文正整数。精确身份及显式别名，不模糊合并量化模型。auto 取已知限制最小值，未知用 4096；manual 加入 fixed 取最小值；缺任一单价返回 None。
- [ ] GREEN：重跑同一测试，增加用户将错误 native 从 4096 改为 32768、service=8192 时结果 8192 的断言。
- [ ] review；获授权后提交 `feat(model-catalog): add metadata resolution core`。

## Task 2：目录持久化及事务审核

**Files:** 创建 `backend/model_catalog/{repository,snapshots}.py`；修改 `backend/data/database.py` 的 `init_db()`；测试 `backend/tests/integration/test_model_catalog_repository.py`。

**Interfaces:** `CatalogRepository(db)` 提供 `resolve(endpoint: EndpointKey) -> EffectiveModel`、`set_override(endpoint, patch, expected_revision)`、`stage(records, source) -> str`、`diff(snapshot_id) -> list[SnapshotDiff]`、`apply(snapshot_id, item_id, fields: list[str], expected_revision: int)`、`ignore(snapshot_id, item_id)`。

`CandidateModel` 包含 ModelKey、native、Price、capabilities、architecture、quantization、source、source_updated_at、pricing_scope；不包含端点密钥。`SnapshotDiff` 包含 id、base_revision、before、after、classification、status。冲突使用 `CatalogConflict` 异常，映射 HTTP 409。

表：model_catalog_entries（身份/来源/版本），bindings（端点到模型与报价作用域），probes（端点数据/状态/时间），overrides（端点字段覆盖/版本），snapshots（source/digest/time），snapshot_items（候选数据/base_revision/审核状态/应用前值）；均使用 model_catalog_ 前缀。时间 UTC RFC3339，例如 `2026-09-15T12:00:00Z`。

- [ ] 使用临时真实 SQLite 写测试，不 mock DB。

```python
def test_stale_review_rejected(repo, candidate):
    snap = repo.stage([candidate], 'custom_json')
    item = repo.diff(snap)[0]
    repo.apply(snap, item.id, ['native'], item.base_revision)
    with pytest.raises(CatalogConflict):
        repo.apply(snap, item.id, ['native'], item.base_revision)
```

- [ ] RED：固定 conda 解释器运行新增测试文件。
- [ ] 实现幂等建表，沿用 get_connection/锁模式。CAS 校验和应用在一个事务中；应用只改选中来源字段，不改用户覆盖。忽略不改变目录；回退用应用前值生成新的待审核快照。
- [ ] GREEN：覆盖初始化两次、重启、并发更新、事务回滚、字段部分应用及缺失字段不清空旧值。
- [ ] review；授权后提交 `feat(model-catalog): persist catalog and review snapshots`。

## Task 3：文件同步、OpenRouter 与本地 API

**Files:** 创建 `backend/model_catalog/{transfer,sources}.py`、`backend/api/model_catalog_routes.py`；修改 `backend/main.py` router 注册；测试 `backend/tests/unit/test_model_catalog_transfer.py`、`backend/tests/integration/test_model_catalog_routes.py`。

**Interfaces:** `encode_bundle(records, source) -> bytes`、`decode_bundle(data: bytes) -> list[CandidateModel]`、`map_openrouter(data: dict) -> list[CandidateModel]`，输入错误抛 `BundleValidationError`。

JSON envelope：formatVersion=1、payload={generatedAt,source,records}、sha256。只对 payload 的 UTF-8 `json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)` 计算 hash；最大 10 MiB、10000 条，拒绝重复身份和未知版本。

路由 `/api/v1/model-catalog`：GET `/models`（每页最多100）、GET `/effective`（端点/模型参数）、PUT `/overrides`、POST `/snapshots/import`、GET `/snapshots`、GET `/snapshots/{id}/diff`、POST `/snapshots/{id}/items/{item}/apply` 和 `/ignore`、GET `/snapshots/{id}/export`、POST `/sync/openrouter`。无本地授权拒绝，冲突409，schema422，超限413，上游失败502。

- [ ] 写失败测试。

```python
def test_roundtrip(candidate):
    assert decode_bundle(encode_bundle([candidate], 'custom_json')) == [candidate]
```

- [ ] RED：运行上述两个新测试文件。
- [ ] 实施前查官方文档确认 OpenRouter schema，per-token 字符串乘 Decimal('1000000')；缺价保持未知，负数特殊值不当免费，pricing_scope=openrouter。
- [ ] 网络请求复用 `backend/api/llm_proxy_routes.py` 的 URL/DNS/有界响应读取安全策略；必要时抽取共享 helper，不降低重定向或 DNS 重绑定防护。Custom JSON 首版仅文件，不抓任意 URL。
- [ ] GREEN：补充 hash 篡改、未知版本、超限、错误币种、重复记录、无授权、导入审核状态不授信、导出无 secret、同步不直接生效、CAS 冲突测试。
- [ ] security/code review；授权后提交 `feat(model-catalog): add reviewed synchronization`。

## Task 4：服务探测与模型发现接线

**Files:** 创建 `backend/model_catalog/probes.py`、`builtin.json`；修改 `src/features/manage-endpoints/api.ts`、`src/pages/settings/EndpointsTab.tsx`；扩展 router；测试 `backend/tests/unit/test_model_catalog_probes.py`、既有前端 `src/features/manage-endpoints/__tests__/api.test.ts`。

**Interfaces:** `parse_probe(service: str, response: dict) -> ProbeValues`，输出 native/service/architecture/quantization 和 provenance；`probe_endpoint(endpoint_id: str, model_id: str) -> ProbeResult` 从已保存端点配置取凭据。新增 POST `/probe`，结果状态 success/unsupported/error。

- [ ] 为 Ollama、LM Studio、llama.cpp、vLLM、Xinference、LocalAI 及通用兼容服务写合成响应 fixture；实施前查证官方路径和版本，不支持时明确 unsupported。

```python
def test_file_metadata_is_not_runtime_limit():
    result = parse_probe('ollama', {'model_info': {'llama.context_length': 32768}})
    assert result.native == 32768
    assert result.service is None
```

- [ ] RED：运行探测与前端发现测试。
- [ ] 实现服务类型显式分流，只有确切 runtime 字段写 service。保留量化 ID，服务失败标 stale 不删除原成功值；端点 URL/模型配置变化使旧探测失效。
- [ ] GGUF 优先消费服务暴露元数据；远端文件不可读时明确未知。本机补充读取必须经用户显式选择和现有文件授权路径，有界读取元数据，不从文件推断 runtime 配置。
- [ ] 内置种子使用查证后的精确 ID 与来源日期，不搬入旧家族前缀价格；离线启动不访问外网。
- [ ] GREEN：发现成功后 enrich、失败保留模型列表、跨端点隔离、量化字段、恶意 URL 和错误响应回归。
- [ ] security/code review；授权后提交 `feat(model-catalog): probe endpoint metadata`。

## Task 5：上下文及现有成本链路统一

**Files:** 修改 `src/entities/setting/{types,storage}.ts`、`backend/api/settings_models.py`、`backend/data/settings_canonicalizer.py`、`src/shared/lib/modelWindows.ts`、`src/features/send-message/useChat.ts`、`src/shared/api/chatApi.ts`、`backend/api/legacy_routes.py`、`src/widgets/chat/ContextMeter.tsx`；成本修改 `backend/services/usage_tracker.py`、`backend/core/legacy/llm_client.py`、`backend/api/usage_routes.py`、`backend/data/database.py`。

**Interfaces:** 新设置 autoContext=false，maxContext 保留手动值。聊天请求/实际 LLM 配置/记账贯通 endpoint_id，缺身份不猜报价。PriceSnapshot 包含单价字符串、scope、revision、source、currency、method=basic_io、computed_at；UsageTracker.record 增加可选 endpoint_id、price_snapshot，每次实际请求开始固定快照。

- [ ] 新增 `backend/tests/unit/test_model_catalog_context.py`、`test_model_catalog_usage.py`；扩展 settings schema parity 与前端 storage 测试。

```python
def test_small_service_window():
    assert effective_window(ContextLimits(native=32768, service=4096), True, 128000) == 4096
```

- [ ] RED：运行新增测试。
- [ ] 同步设置 schema/白名单；普通发送、重发、会话覆盖均使用实际端点。移除硬编码前缀窗口解析，ContextMeter 与请求同源；异步解析结果不得串模型。
- [ ] 后端移除 >=20000 门槛和历史预算最少4000的逻辑。总窗口减系统/工具/当前输入及输出预留，再把非负剩余交给历史裁剪；必需内容本身超限明确拒绝，不把总窗口当纯历史预算。
- [ ] 三处 usage_tracker.record 接线，fallback 按实际端点/模型重新固定快照；usage_events 幂等增加可空端点与快照列；旧记录不重算。
- [ ] 新记录不再应用统一0.1缓存折扣，保留缓存计数。API/CSV 未知保持null/空白；汇总给 known_cost、unknown_count，标部分估算。消费限额继续拦截已知费用，同时显示未知部分未纳入。
- [ ] GREEN：运行 `test_usage_tracker.py`、`test_usage_cache_aware.py`、`test_usage_persistence.py`、`test_settings_schema_parity.py` 和前端 storage/useChat/ContextMeter 回归；验证改价不改历史、流式/同步/fallback一致。
- [ ] Python/TypeScript/code review；授权后分别提交上下文接线和成本快照。

## Task 6：管理页面、审核与设置展示

**Files:** 新增 `src/entities/model-catalog/{types,api}.ts`、`src/pages/ModelCatalog.tsx`、`src/widgets/model-catalog/{CatalogTable,ModelDetails,SnapshotReview}.tsx`；修改 `src/App.tsx`、`src/pages/settings/ModelsTab.tsx`、`src/widgets/settings/{UsagePanel,UsageRequestsTable}.tsx`。

**Interfaces:** TS 与后端 JSON 对齐，Decimal 保持字符串，不在浏览器计算费用。API client 消费 Task 3 路由，分页查询，不复制后端优先级算法。

- [ ] 新增 `src/pages/__tests__/ModelCatalog.test.tsx`、`src/widgets/model-catalog/__tests__/SnapshotReview.test.tsx`，使用现有网络 mock 模式提供合成 snapshot。

```tsx
it('requires review before applying imported data', async () => {
  render(<SnapshotReview snapshotId="synthetic-snapshot" />);
  expect(await screen.findByText('待审核')).toBeVisible();
  expect(screen.getByRole('button', { name: '应用所选字段' })).toBeEnabled();
});
```

- [ ] RED：`npm run test:run -- src/pages/__tests__/ModelCatalog.test.tsx src/widgets/model-catalog/__tests__/SnapshotReview.test.tsx`。
- [ ] 实现 `/model-catalog` 页面和设置入口；搜索/过滤、端点绑定、显式别名、增改覆盖、删除覆盖恢复继承、探测状态、快照列表、导入导出及同步。
- [ ] 审核展示逐字段来源/旧值/新值/保护状态。409刷新差异并重新确认；提交期间防重复；键盘可操作，不仅以颜色标状态。
- [ ] 设置自动开关保留固定值，未知显示未知；费用区分未知与0，标明基础估算不含缓存和阶梯折扣。
- [ ] GREEN：空目录、断网、导入失败、部分应用、并发冲突、快速切换模型、端点删除及手动值恢复测试；`npm run typecheck`。
- [ ] 使用 run-desktop 技能启动 worktree 独立端口，浏览器实际测试并检查 console/network。不能运行时报告阻塞，不宣称UI通过。
- [ ] accessibility/TypeScript/code review；授权后提交 `feat(model-catalog): add catalog management UI`。

## Task 7：端到端验收与文档收口

**Files:** 新增 `backend/tests/integration/test_model_catalog_lifecycle.py`、`tests/model-catalog.spec.ts`；更新技术/用户手册的 README 和对应模型配置/统计章节。

- [ ] 写生命周期测试：合成在线目录→待审核→部分应用→导出→第二个离线数据库导入→本地审核→端点绑定→自动上下文→记账→改价→历史费用不变。
- [ ] RED：运行新增生命周期/E2E测试，确认缺失接线会失败。
- [ ] 修复集成缺口，不扩展至定时同步、缓存阶梯计费或RBAC。
- [ ] GREEN：全新增测试及相关回归覆盖率至少80%；`npm run typecheck`、`npm run test:smoke`；离线测试阻断所有外部互联网请求，验证本地目录/导入/审核可用。
- [ ] 手动验证小窗口、量化模型、两个同名端点不同价格/限制、未知/免费、模式切换、服务不支持、过期审核冲突，记录实际证据。
- [ ] 文档说明优先级、离线审核、自动模式、估算不等于账单和固定缓存折扣移除。新增章节采用手册下一个空闲编号并更新总览，不预占其他任务编号。
- [ ] 最终review通过且功能验收后，将内容并入技术/用户手册，再删除已被替代的计划/设计文档；未完成时持续更新本文件复选框。

## 自检映射与风险

Spec §1–4→Task1/2/4；§5→Task3；§6→Task4；§7–8→Task5；§9→Task6；§10–11→Task2/3；§12–13→Task7。

主要风险：旧聊天路径未贯通端点身份、小窗口预算语义改变、缓存计价行为变化、供应商报价误套、服务API版本差异。各风险均由上述隔离、明确口径、协议fixture和端到端回归约束；所有未受服务明确支持的信息保留未知，不做名称猜测。
