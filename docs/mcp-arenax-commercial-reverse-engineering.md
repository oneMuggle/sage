# ArenaX_Commercial 静态逆向分析报告

## 结论

`reference/ArenaX_Commercial` 不是待反编译的单一可执行文件，而是一个 Python/FastAPI 项目：入口和浏览器扩展源码可直接阅读；核心逻辑被编译为 CPython 3.12、Windows x86-64 的 Cython 扩展（`.cp312-win_amd64.pyd`）。因此本次完成的是静态结构恢复、符号/字符串提取和数据流分析，不是把 `.pyd` 还原成等价 Python 源码。

## 项目结构

- `run_server.py`：启动 FastAPI 服务，默认端口 9090，并尝试释放占用端口。
- `web/api_server.cp312-win_amd64.pyd`：HTTP API、控制台、商业授权中间件、OpenAI/Anthropic/Responses 协议适配。
- `arenax/bridge.cp312-win_amd64.pyd`：上游 Arena 会话请求、流式聊天、会话列表和会话检查。
- `arenax/store.cp312-win_amd64.pyd`：Token、Cookie、模型和缓存状态。
- `arenax/session_probe.cp312-win_amd64.pyd` / `session_scout.cp312-win_amd64.pyd`：会话探测、模型识别、创建或扫描会话。
- `arenax/trigger_trace.cp312-win_amd64.pyd` / `trace_parser.cp312-win_amd64.pyd`：Trigger.dev trace 读取、模型/Token/推理信息解析。
- `arenax/anthropic_relay.cp312-win_amd64.pyd`：Anthropic `/v1/messages` 转换和 SSE 流适配。
- `arenax/responses_relay.cp312-win_amd64.pyd`：OpenAI Responses API `/v1/responses` 转换和 SSE 适配。
- `arenax/account_manager.cp312-win_amd64.pyd`：账户池、JWT/Cookie、会话和路由管理。
- `arenax/auth_login.cp312-win_amd64.pyd`：Playwright/Chrome 登录与同步。
- `arenax/auto_register.cp312-win_amd64.pyd`：通过 mail.cx 临时邮箱执行 Arena 账户注册流程。
- `extension/`：Chrome MV3 扩展，用于从 arena.ai 页面获取 Cookie、认证信息、reCAPTCHA token 和模型数据，并推送到本地服务。

## 已恢复的主要符号

### 上游与会话

`chat_with_model`、`stream_chat_generator`、`probe_agent_mode`、`list_user_sessions`、`inspect_session`、`detect_sessions`、`detect_session_model`、`detect_all_models`、`create_new_session`、`auto_scout_top_model`。

### 中继协议

`parse_anthropic_request`、`anthropic_stream_adapter`、`parse_responses_request`、`responses_stream_adapter`、`build_*_non_stream_response`。这些符号表明服务将内部 Arena 流转换成 Anthropic、OpenAI Chat Completions 和 OpenAI Responses 三类协议。

### 授权与凭据

`commercial_license_middleware`、`license_info`、`license_activate`、`extract_raw_jwt`、`parse_token_or_cookie`、`build_cookie_header_from_dict`、`get_session_token`、`trigger_token_is_usable`。

## 数据流

1. 扩展在 `arena.ai` 页面运行。
2. `background.js` 读取 `arena.ai` 域 Cookie，并合并分片形式的 `arena-auth-prod-v1`。
3. `injector.js` 从页面调用 `grecaptcha.execute`，提取 Cookie 和页面内模型数据。
4. 扩展保存最近的 v3 token，并向 `http://127.0.0.1:9090` 推送。
5. FastAPI 中继从本地状态中选择 Token、Cookie 或会话。
6. `bridge` 访问 Arena 上游；流经 `trace_parser` 和 `trigger_trace` 做会话/模型信息解析。
7. relay 模块向客户端输出标准 OpenAI/Anthropic SSE 或非流式响应。

## 暴露的 HTTP 接口（由文档和符号交叉确认）

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/messages`
- `POST /v1/responses`
- `POST /v1/extension/push`
- `GET /v1/relay/config`
- `POST /v1/relay/pin`
- `POST /v1/relay/unpin`
- `GET /v1/agent/sessions`
- `GET /v1/agent/session/{id}`
- 以及授权、状态、路由同步和上下文清理接口。

## 二进制特征

- 文件格式：PE32+ DLL，x86-64。
- ABI：CPython 3.12 Windows 扩展。
- 编译产物痕迹：每个模块包含对应的 `.c` 路径和原始 `.py` 模块名，例如 `arenax/bridge.c`、`arenax/bridge.py`。
- 可提取内容：模块名、函数名、文档字符串、常量字符串、异常文本和部分控制流线索。
- 不可直接获得：完整 Python 源码、局部变量名的全部语义、原始注释和精确控制流。

## 配置状态

- `configs/accounts_pool.json` 当前为空账户池。
- `configs/arena_model_catalog.json` 当前模型列表为空。
- `configs/relay_config.json` 默认模式为 `direct`，默认模型字段为 `gpt-5.6-luna`，未设置默认会话。

## 关键观察

- 扩展权限包含 `cookies`、`storage`、`tabs`，并允许访问 `arena.ai` 与本地 9090 服务。
- `background.js` 会读取并保存认证 Cookie，解析其中的邮箱，维护 Token 池并定期推送。
- `injector.js` 暴露页面侧 reCAPTCHA 执行、Cookie 读取和模型提取接口。
- 二进制模块中存在自动注册、临时邮箱、会话创建、模型探测、Trace 读取和授权校验相关实现。
- `COMMERCIAL_USER_GUIDE.md` 声称核心业务模块已编译为原生机器码；目录实际也验证了这一点。

## 当前结果

已完成：目录盘点、源码阅读、Pyd 符号提取、PE 类型确认、字符串/文档字符串提取、模块关系和凭据/会话数据流恢复。

未完成：将所有 `.pyd` 还原成可重新运行的 Python 源码。若要继续到函数级伪代码，需要在 Windows 环境对目标扩展进行反汇编/调试，优先分析 `web/api_server`、`bridge`、`store`、`trigger_trace` 和 `extension/background.js` 的交界面。
