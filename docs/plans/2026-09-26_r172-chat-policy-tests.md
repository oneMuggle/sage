# R172：chat_request_policy 窗口策略单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；C2b 聊天请求窗口策略（五份重复收敛为
  唯一实现）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`api/chat_request_policy.py`（158 行）收敛了五份重复的窗口解析与超窗
拒绝逻辑。`_check_request_within_window` 是纯函数可直接测；
`_resolve_effective_window` 的 fail-safe 回退路径（settings 非 dict /
endpoints 非 list / 无 endpoint_id）可在 patch SettingsRepository 后
覆盖。

## 覆盖矩阵（约 13 例）

_check_request_within_window：
1. window None → no-op；2. window ≤ 0 → no-op；3. 总 token 未超窗 →
no-op；4. 超窗 → HTTPException 400 含 token 数与窗口值。

_resolve_effective_window（fail-safe 回退，patch SettingsRepository）：
5. settings 非 dict → max_context 或 None；6. endpoints 非 list →
max_context；7. 无 model_id → max_context；8. 全缺 → None；
9. monkeypatch CatalogRepository/effective_window 走 auto_context=True
catalog 路径（min 窗口）。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
