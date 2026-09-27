# R169：Node.js 运行时适配器单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；runtime 适配器协议（tools/adapters）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/adapters/node_adapter.py`（279 行，Node.js 适配器：PATH 候选
发现、版本探测、npm/pnpm/yarn/bun 工具链、package.json/tsconfig 清单
识别、NODE_RUNTIME_MISSING 诊断、_mark_default 去重与默认标记）此前
零测试。

## 覆盖矩阵（约 17 例）

1. discover：PATH 目录中的 node 被发现、版本号解析（v20.5.0 →
   20.5.0）、can_execute=True；2. 非零退出/无版本号跳过；3. 路径去重；
4. include_paths 直接注入候选；5. 工具链（npm 等）发现为 TOOLCHAIN
   且 can_package_check；6. _mark_default 首个 Node.js 标 is_default、
   同名去重；7. build_command：argv=[node, -] + stdin_payload=code；
8. inspect：platform JSON 解析进 raw、非法 JSON → platform None；
9. discover_manifests：package.json（engines_node/scripts 排序）+
   tsconfig；坏 JSON 兜底；10. diagnose：有 package.json 无 node →
   NODE_RUNTIME_MISSING ERROR + UNSATISFIED、有 node → SATISFIED +
   recommended；11. _pick_default 回退首元素。

fake safe_run 按 argv 分派返回，PATH 指向 tmp 目录放假 node 文件。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
