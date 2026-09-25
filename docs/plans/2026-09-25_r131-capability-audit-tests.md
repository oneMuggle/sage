# R131：multimodal 能力基类 + 内置审计钩子单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；hooks Phase 1（观察型审计钩子）
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`services/multimodal/capability.py`（105 行，AICapability 模板方法基类：
execute 构建→发送→解析链路 + load_config 从 app_settings 解析端点的
七分支矩阵）与 `hooks/builtin_audit.py`（78 行，post_tool_use 审计
钩子：永不阻断 fail-open + 50MB 轮转）此前零测试。能力子类
（TTS/ASR/ImageGen）已在 r118/r120/r125 覆盖，本轮钉住基类与钩子本体。

## 覆盖矩阵（约 22 例）

### `backend/tests/unit/services/test_capability_base.py`（13 例）

1. CapabilityKind 三个枚举值；2. CapabilityConfig/AIHttpRequest/
AIHttpResponse frozen 不可变；3. AIHttpRequest 缺省（POST/timeout 60/
空 headers）；4. AIHttpResponse 缺省（json None）；
5-10. load_config 矩阵：settings 空 → None；无 modelSelections → None；
selection 缺 endpointId → None；endpointId 匹配 → baseUrl rstrip("/")
+ apiKey + model（selection 优先，缺省回退 endpoint modelId，双缺 →
空串）；endpointId 未命中 → None；
11-13. execute 模板方法（fake AsyncClient）：请求实参完整透传
（method/url/headers/body/data/files/timeout）、JSON content-type →
parse_response 收到已解析 json、非 JSON → json=None、**kwargs 双向
透传（build_request 与 parse_response 同参）。

### `backend/tests/unit/hooks/test_builtin_audit.py`（9 例）

1. 正常记录：JSONL 单行、timestamp（utc isoformat）/event/tool_name/
tool_input 四键、返回 allow；2. payload 缺 hook_event_name → 默认
post_tool_use；3. 自定义 log_dir/log_file（tmp_path）；4. 轮转：超
max_size_mb → 旧文件改名 .jsonl.1、新记录写新文件；已有备份先删；
5. fail-open：log_dir 指向普通文件 → mkdir 抛错被吞，仍返回 allow 且
带 reason；6. payload 字段缺省 → tool_name=""、tool_input=None。

## 验证

- pytest 新文件 + 邻近用例；ruff（CI 同版本 0.4.4）从**仓库根**跑
  `ruff check backend/`（对齐 CI 计数口径，吸取 r130 教训）。

## 明确不做

- 不测真实 httpx 网络与 ONNX 模型（集成域）。
