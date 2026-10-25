# R127：depends_on 拓扑工具 + 审计事件文件适配器单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；编排 P1（spec 2026-08-21 确定性分波）、
  审计事件 spec §6.1
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`orchestration/topology.py`（105 行，depends_on 的 Kahn 分层波次 + DFS
环检测 + 级联闭包——dispatch 确定性分波的核心，环/外部引用语义必须
钉死）与 `adapters/out/event/file_adapter.py`（100 行，5 类审计事件
JSONL 落盘：路径解析顺序 / envelope 形状 / 追加写）此前零测试。

## 覆盖矩阵（约 24 例）

### `backend/tests/unit/orchestration/test_topology.py`（14 例）

find_cycle：
1. 无环 → None；2. 双节点环 → 路径首尾相同（["t2","t3","t2"]）；
3. 自环 → ["t1","t1"]；4. **外部引用视为已满足**（dep 不在图中不算
环、不参与）；5. 从其他起点进入才可达的环也能找到。

build_waves：
6. 全独立任务 → 单波（保持输入顺序）；7. 链 a→b→c → 三波；
8. 菱形 a→(b,c)→d → 中波按输入序；9. 外部依赖任务落在第 0 波；
10. 环 → DependencyCycleError 且 .cycle 含环路径；
11. 部分节点成环部分独立 → 抛错（done_count < total 分支）。

downstream_closure：
12. 直接下游单跳；13. 传递闭包含间接、**不含 seeds 自身**；
14. 多 seed 并集；seed 不在图中 → 空集。

### `backend/tests/unit/adapters/test_file_event_adapter.py`（10 例）

1. AuditEventType.all() = 5 类审计常量；run_lifecycle() 顺序契约；
2. emit 落盘 JSONL：单行 JSON、envelope 五键（schema/format_version/
ts/type/payload）；3. 追加写（两次 emit 两行）；4. 显式 log_path 且
父目录自动创建；5. 默认路径解析顺序：SAGE_USER_DATA_DIR 命中 →
`<dir>/audit/audit.jsonl`，env 未设 → dev fallback；6. 中文 payload
ensure_ascii=False 原样落盘；7. json.loads 往返。

## 验证

- pytest 新文件 + 邻近用例；ruff（CI 同版本 0.4.4）。

## 明确不做

- 不测 dispatch 消费波次的编排层（其 I/O 域另有用例）。
