# R135：Compute mock 适配器 + ReviewQueue 装配单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；ComputePort 内存实现（六边形测试基建）/
  PR-C §5.2 ReviewQueue 协作对象 early-bind
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`adapters/out/compute/mock_adapter.py`（63 行，ComputePort 内存实现：
specs 副本返回、按 operation 查 responses、未配置回退 default、调用
记录）与 `skills/review_bootstrap.py`（65 行，ReviewQueue 协作对象
启动期装配：三个可注入参数 + 全局单例默认解析）此前零测试。

## 覆盖矩阵（约 14 例）

### `backend/tests/unit/adapters/test_mock_compute_adapter.py`（9 例）

1. list_operations 返回 specs 副本（外部修改不影响）；
2. execute 按 operation 命中 responses；3. 未配置 operation → default
（OPERATION_NOT_FOUND）；4. 显式 default_result 生效；5. calls 记录
ComputeRequest 顺序；6. reset 清空调用记录；7. 结构一致（实例可赋
ComputePort 注解）；8. 空构造默认可用；9. 多 operation 各自命中。

### `backend/tests/unit/skills/test_review_bootstrap.py`（5 例）

1. 显式注入：queue.set_review_service / set_draft_store 均被调用；
2. 参数缺省 → 解析三个全局单例（patch 三个 getter 断言调用）；
3. queue 缺省时仍可注入自定义 service/store；
4. 重复调用（同一实例）→ 幂等不抛错；
5. 返回 None（纯副作用装配函数）。

## 验证

- pytest 新文件 + 邻近用例；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
