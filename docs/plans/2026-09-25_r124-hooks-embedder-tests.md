# R124：HTTP Hook 客户端 + 嵌入器路由单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；hooks Phase 5（fail-open 设计）/ B1-P11
  嵌入器切换
- **范围**：后端 only，两个测试文件新增（含 tests/unit/hooks 包初始化），
  零生产代码改动
- **附带回移**：main #1566（DNS 超时 except 补 asyncio.TimeoutError，py38
  逃逸修复）按对齐规则回移 release/win7 → PR #1575

## 0. 结论速览

`hooks/http_client.py`（94 行，HTTP hook fail-open 客户端：env 占位符
header、方法白名单、URL scheme 校验、256KB 响应上限、非 2xx/非 object
JSON/网络错误全 fail-open）与 `api/embedder_routes.py`（73 行，嵌入器
状态与运行时切换：503 未装配 / 422 非法 mode / settings 持久化 +
reconfigure 热重载 / onnx 缺失自动降级 hash）此前零测试。

## 覆盖矩阵

### `backend/tests/unit/hooks/test_http_client.py`（16 例）

1. resolve_header_value：env 替换、未设置 env → 空串、多占位符、
   未闭合 `${env:X` 原样返回；2. resolve_headers：非 dict → {}、
   非 str 键/值过滤；3. send_http_hook fail-open 全路径：非法方法、
   非 http(s) URL、非 str URL、响应超 256KB（常量压小验证）、非 2xx、
   非 object JSON（list）、连接错误、畸形 JSON → 全部 None；
4. 成功路径：返回 dict、Content-Type + env 替换后的 header、payload
   原样传递、follow_redirects=False；5. env 未设置时 header 值为空串。
   fake AsyncClient（async context manager + 捕获实参）替代真实网络。

### `backend/tests/unit/api/test_embedder_routes.py`（9 例）

handler 直调（fake Request = SimpleNamespace(app.state)）：

1. status：payload 七键（type/semantic/dimensions/table/model_dir/
   model_ready + 修饰）；2. adapter 未装配 → 503；3. embedder 未初始化
   → 503；4. select 非法 mode → 422；5. select adapter 缺 reconfigure
   → 503；6. select 成功：settings 持久化（patch
   backend.data.settings_repo.SettingsRepository）、
   create_embedder(preferred_mode=mode)、reconfigure 收到工厂返回的
   embedder、结果含 mode 键；7. mode 大写/带空白归一化；8. 空体 mode
   → 422。

## 验证

- pytest 新文件 + hooks/api 邻近用例；ruff（CI 同版本 0.4.4）。

## 明确不做

- 不测 ONNX 真实模型加载（工厂降级逻辑属 embedder_factory 用例域）。
